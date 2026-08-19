"""The live TUI: wind components and CO2 mixing ratio, as they arrive.

The app knows nothing about where lines come from. It is handed an async
iterator of ``(stream_name, payload)`` — from the simulator or from real
multicast sockets — decodes each line according to which stream it belongs to,
and feeds :class:`~record_ec_visualizer_tui.model.LiveState`.

Layout is deliberately frugal: each stream is one widget that draws its own
single-line header followed by the plot, with no borders and no separate
readout panels. The header doubles as the current-value display, the legend
(component names are drawn in their series colour) and the separator between
the two stacked plots, so every row of terminal height that is not a plot is
carrying information.
"""
from __future__ import annotations

import math
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass

from rich.text import Text
from textual.app import App, ComposeResult
from textual.containers import Vertical
from textual.widgets import Footer, Header, Static

from record_ec_visualizer_tui import __version__
from record_ec_visualizer_tui.codec import DecodeError, parse_ga_message, parse_show_message
from record_ec_visualizer_tui.model import (
    MAX_WINDOW_SECONDS,
    WIND_RAW_KEYS,
    LiveState,
    StreamHealth,
)
from record_ec_visualizer_tui.simulator import SONICSHOW_STREAM
from record_ec_visualizer_tui.tui.plot import BRAILLE, GlyphSet, render_braille_plot

LABEL_WIDTH = 8


@dataclass(frozen=True)
class Palette:
    """The four trace colours: three wind components, then the gas.

    Four is the whole display, so a palette is judged as a set rather than
    colour by colour. Two things decide one. The three wind traces share a plot
    and overlap, and the renderer resolves an overlap by last writer wins, so
    they have to stay apart in hue rather than only in lightness; the gas has
    its own plot and only has to be legible. And every colour is drawn on the
    terminal's own dark background, which the app never paints over, so nothing
    here goes below roughly mid lightness.
    """

    name: str
    wind: tuple[str, str, str]
    gas: str


#: Cycled by the palette key, first entry first.
PALETTES = (
    # The 16 ANSI colours, and the only palette that survives a terminal which
    # has just those: on the Linux console the hex palettes below are
    # approximated to the nearest of eight, which collapses hues that were
    # chosen to be distinct. It is first because it is the one that always
    # works.
    Palette("classic", ("bright_cyan", "bright_magenta", "bright_yellow"), "bright_green"),
    # Okabe-Ito, the palette designed so that the common forms of colour
    # blindness keep the separations. The three wind values are canonical; the
    # gas is its bluish green lightened, since #009E73 reads as nearly black
    # against this background and it shares its plot with nothing.
    Palette("okabe", ("#56B4E9", "#E69F00", "#F0E442"), "#00C896"),
    # Cool and less saturated, for a long look at a screen.
    Palette("aurora", ("#7DD3FC", "#C4B5FD", "#FDE68A"), "#6EE7B7"),
    # Saturated and far apart, for a bright room or a projector.
    Palette("dusk", ("#F472B6", "#818CF8", "#FBBF24"), "#34D399"),
)

#: Seconds of history both panels show, halved and doubled from the default.
#: Both panels always take the same entry - reading one plot against the other
#: is the point of the window existing at all.
WINDOW_STEPS = (15.0, 30.0, 60.0, 120.0, MAX_WINDOW_SECONDS)
#: An index into the ladder, not a duration.
DEFAULT_WINDOW_INDEX = WINDOW_STEPS.index(60.0)

#: Below these widths the header sheds its least important parts rather than
#: wrapping, which would cost a plot row. Each optional part carries its own
#: threshold, and the thresholds are cumulative by construction: a part is
#: budgeted the width of everything that outranks it plus its own cost, so
#: parts disappear one at a time from the least important upwards.
WIDTH_FOR_META = 72
#: A panel's units, and any short detail alongside them.
WIDTH_FOR_EXTRAS = 94
#: Vertical-wind deviation and TKE — how vigorously the air is mixing, which
#: outranks the units it is quoted in.
WIDTH_FOR_TURBULENCE = 88
#: The wind panel's units and per-component deviations, which sit behind the
#: turbulence pair and so have to clear both. The last to earn its place: sw
#: already repeats the third of the three deviations.
WIDTH_FOR_DEVIATIONS = 116


class StreamPanel(Static):
    """A header line plus a plot, sized to whatever space it is given."""

    #: Set once by the app; the choice never changes while running.
    glyphs: GlyphSet = BRAILLE

    def draw(
        self,
        title: str,
        chips: Sequence[tuple[str, str, str]],
        parts: Sequence[tuple[str, int]],
        meta: str,
        series: Sequence[dict[str, object]],
        empty_message: str,
    ) -> None:
        width = max(20, self.size.width)
        plot_width = max(10, width - LABEL_WIDTH - 2)
        # One row goes to the header; the rest is plot.
        plot_height = max(3, self.size.height - 1)

        text = _header_line(title, chips, parts, meta, width)
        text.append("\n")
        text.append_text(
            render_braille_plot(
                series,
                width=plot_width,
                height=plot_height,
                label_width=LABEL_WIDTH,
                empty_message=empty_message,
                glyphs=self.glyphs,
            )
        )
        self.update(text)


class StatusBar(Static):
    """Stream liveness and rECorD's own buffer diagnostics."""

    def update_from(self, state: LiveState, paused: bool) -> None:
        text = Text()
        _append_health(text, "sonicshow", state.sonic_health)
        text.append("  ")
        _append_health(text, "analyzer", state.gas_health)

        for key in sorted(state.diagnostics):
            value = state.diagnostics[key]
            if key.endswith("_buffer") and isinstance(value, tuple):
                used, size = value
                text.append(f"  {key} ", style="grey50")
                text.append(f"{used}/{size}", style="yellow" if size and used < size * 0.5 else "grey85")
            elif key.endswith("_freq"):
                text.append(f"  {key} ", style="grey50")
                text.append(f"{value} Hz", style="red" if not value else "grey85")

        if paused:
            text.append("  PAUSED", style="bold black on yellow")
        self.update(text)


class VisualizerApp(App[None]):
    """Live view of incoming rECorD data."""

    CSS_PATH = "app.tcss"
    TITLE = "rECorD live"

    BINDINGS = [
        ("q", "quit", "Quit"),
        ("space", "toggle_pause", "Pause"),
        ("r", "reset", "Reset series"),
        ("c", "cycle_palette", "Colours"),
        # equals_sign as well as plus, so widening does not need the shift key.
        ("minus", "shrink_window", "Range -"),
        ("plus,equals_sign", "grow_window", "Range +"),
    ]

    def __init__(
        self,
        lines: AsyncIterator[tuple[str, bytes]],
        state: LiveState,
        subtitle: str = "",
        refresh_hz: float = 8.0,
        glyphs: GlyphSet = BRAILLE,
    ) -> None:
        super().__init__()
        self._lines = lines
        self.state = state
        self.glyphs = glyphs
        self.paused = False
        # Indices rather than the values themselves: both are cheap to fold
        # into the redraw tokens below, which is what makes a keypress show up
        # without a message having to arrive first.
        self._palette = 0
        self._window = DEFAULT_WINDOW_INDEX
        self._refresh_interval = 1.0 / max(0.5, refresh_hz)
        # The version rides in the header so that a screenshot from a
        # logging host says which build produced it.
        self.sub_title = f"{subtitle} · v{__version__}" if subtitle else f"v{__version__}"

    @property
    def palette(self) -> Palette:
        """The colours in force. Not ``theme``: Textual's ``App`` owns that."""
        return PALETTES[self._palette]

    @property
    def window_seconds(self) -> float:
        """How much history both panels draw."""
        return WINDOW_STEPS[self._window]

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical():
            for panel_id in ("wind-plot", "gas-plot"):
                panel = StreamPanel(id=panel_id, classes="plot")
                panel.glyphs = self.glyphs
                yield panel
            yield StatusBar(id="status")
        yield Footer()

    def on_mount(self) -> None:
        # Resolved once: _refresh runs several times a second and a DOM query
        # per panel per tick is pure overhead.
        self._wind_panel = self.query_one("#wind-plot", StreamPanel)
        self._gas_panel = self.query_one("#gas-plot", StreamPanel)
        self._status_bar = self.query_one("#status", StatusBar)
        self._wind_drawn: tuple[int, ...] | None = None
        self._gas_drawn: tuple[int, ...] | None = None

        self.run_worker(self._consume(), name="stream-reader", exclusive=True)
        self.set_interval(self._refresh_interval, self._refresh)

    async def _consume(self) -> None:
        """Decode incoming lines forever, routing by stream name."""
        async for name, payload in self._lines:
            if self.paused:
                continue
            try:
                if name == SONICSHOW_STREAM:
                    self.state.ingest_sonicshow(parse_show_message(payload))
                elif name.startswith("ga:"):
                    self.state.ingest_ga(parse_ga_message(payload))
            except DecodeError as exc:
                health = (
                    self.state.sonic_health if name == SONICSHOW_STREAM else self.state.gas_health
                )
                health.mark_error(str(exc))

    def _refresh(self) -> None:
        """Redraw whatever has changed.

        A panel is only re-rendered when its stream has delivered something new
        or the panel was resized. sonicshow speaks once per second, so without
        this the wind plot would be rebuilt several times per second to draw the
        identical picture — wasted work on a machine that is also running
        rECorD's 20 Hz acquisition loop.
        """
        state = self.state
        palette = self.palette
        window = self.window_seconds
        # One clock for both panels: the window each draws ends here rather
        # than at its own last arrival, which is what keeps a stalled stream
        # from drawing a healthy trace a whole window out of phase.
        now = state.elapsed

        # The palette and the window belong in the token because neither one
        # changes the message count or the size, and a keypress that redrew
        # nothing until the next message would look like it had not worked.
        # The whole second does too, and for the opposite reason: a stream that
        # has gone silent delivers no messages, and its trace has to keep
        # scrolling out of the window rather than freeze mid-plot.
        second = int(now)
        wind_token = (
            state.sonic_health.messages,
            *self._wind_panel.size,
            self._palette,
            self._window,
            second,
        )
        if wind_token != self._wind_drawn:
            self._wind_drawn = wind_token
            # Component names carry their series colour, so the header is the legend.
            deviations = " ".join(
                _number(state.wind_stdev[key].latest, ".2f") for key in WIND_RAW_KEYS
            )
            # sw and TKE say how vigorously the air is mixing, which is the
            # quantity a viewer can act on; the per-component deviations behind
            # them are the detail. Both come free with every sonicshow message.
            turbulence = (
                f"sw {_number(state.sigma_w, '.2f')}  TKE {_number(state.tke, '.2f')}"
            )
            self._wind_panel.draw(
                title="wind",
                chips=[
                    (state.label_for(key), _number(state.wind[key].latest, "6.2f"), color)
                    for key, color in zip(WIND_RAW_KEYS, palette.wind)
                ],
                parts=[
                    (f"m s-1   sd {deviations}", WIDTH_FOR_DEVIATIONS),
                    (turbulence, WIDTH_FOR_TURBULENCE),
                ],
                meta=f"1 Hz sonicshow  ·  last {window:.0f} s",
                series=[
                    {"y": state.wind[key].window_values(window, now), "color": color}
                    for key, color in zip(WIND_RAW_KEYS, palette.wind)
                ],
                empty_message="waiting for the first sonicshow message",
            )

        gas_token = (
            state.gas_health.messages,
            *self._gas_panel.size,
            self._palette,
            self._window,
            second,
        )
        if gas_token != self._gas_drawn:
            self._gas_drawn = gas_token
            self._gas_panel.draw(
                title="gas",
                chips=[(state.gas_var, _number(state.gas.latest, "7.2f"), palette.gas)],
                parts=[("umol mol-1", WIDTH_FOR_EXTRAS)],
                meta=f"analyzer stream  ·  last {window:.0f} s",
                series=[{"y": state.gas.window_values(window, now), "color": palette.gas}],
                empty_message="waiting for analyzer records",
            )

        # The status bar always redraws: staleness is a function of the clock,
        # not of arrivals, and it is one line.
        self._status_bar.update_from(state, self.paused)

    def action_toggle_pause(self) -> None:
        self.paused = not self.paused

    def action_reset(self) -> None:
        self.state.reset()
        # Force a redraw: the series changed without a new message arriving.
        self._wind_drawn = None
        self._gas_drawn = None

    def action_cycle_palette(self) -> None:
        self._palette = (self._palette + 1) % len(PALETTES)

    def action_grow_window(self) -> None:
        """Show twice as long a stretch, up to the longest one buffered."""
        self._window = min(self._window + 1, len(WINDOW_STEPS) - 1)

    def action_shrink_window(self) -> None:
        """Show half as long a stretch, down to the shortest one plottable."""
        self._window = max(self._window - 1, 0)


def _header_line(
    title: str,
    chips: Sequence[tuple[str, str, str]],
    parts: Sequence[tuple[str, int]],
    meta: str,
    width: int,
) -> Text:
    """Title, live values, and a rule filling out to right-aligned metadata.

    Parts are dropped from least to most important as the terminal narrows, so
    the header never wraps onto a second row. Each is a ``(text, min_width)``
    pair and is written in the order given; a part whose threshold is not met is
    left out and the ones that outrank it close up around the hole.
    """
    text = Text()
    text.append(f"{title} ", style="bold grey85")
    for label, value, color in chips:
        text.append(f" {label} ", style=f"bold {color}")
        text.append(value, style=color)
    for part, min_width in parts:
        if part and width >= min_width:
            text.append(f"  {part}", style="grey50")

    if not meta or width < WIDTH_FOR_META:
        text.append(" " + "─" * max(1, width - text.cell_len - 1), style="grey35")
        return text

    fill = width - text.cell_len - len(meta) - 2
    text.append(" " + "─" * max(1, fill) + " ", style="grey35")
    text.append(meta, style="grey50")
    return text


def _append_health(text: Text, label: str, health: StreamHealth) -> None:
    text.append(f"{label} ", style="grey50")
    age = health.age()
    if age is None:
        text.append("no data", style="red")
        return
    text.append(f"{age:4.1f}s ago", style="red" if health.is_stale else "green")
    if health.errors:
        text.append(f" ({health.errors} bad)", style="yellow")


def _number(value: float, spec: str, width: int = 0) -> str:
    """Format a number, showing a dash for a missing value."""
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "--".rjust(width)
    return format(value, spec)
