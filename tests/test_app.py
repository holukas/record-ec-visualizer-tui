"""Headless smoke tests: the app must actually ingest and draw."""
import asyncio
import math

import pytest

from rich.style import Style

from record_ec_visualizer_tui import __version__
from record_ec_visualizer_tui.codec import VariableMap
from record_ec_visualizer_tui.model import LiveState, SeriesBuffer
from record_ec_visualizer_tui.simulator import RecordSimulator, SimulationConfig
from record_ec_visualizer_tui.sources import simulated_lines
from record_ec_visualizer_tui.tui.app import (
    PALETTES,
    WIDTH_FOR_DEVIATIONS,
    WIDTH_FOR_META,
    WIDTH_FOR_TURBULENCE,
    WINDOW_STEPS,
    StreamPanel,
    VisualizerApp,
    _header_line,
)
from record_ec_visualizer_tui.tui.plot import (
    BLOCK_FULL,
    BLOCK_LOWER,
    BLOCK_UPPER,
    BLOCKS,
    BRAILLE,
    BRAILLE_BASE,
    GlyphSet,
)

BRAILLE_BLANK = chr(BRAILLE_BASE)


def _build(glyphs: GlyphSet = BRAILLE) -> tuple[VisualizerApp, LiveState]:
    config = SimulationConfig()
    state = LiveState(
        gas_var="CO2",
        sonic_map=VariableMap(config.sonic_var_map),
        gas_map=VariableMap(config.var_map),
    )
    app = VisualizerApp(
        simulated_lines(RecordSimulator(config), speedup=40.0),
        state,
        subtitle="test",
        glyphs=glyphs,
    )
    return app, state


def _plain(widget) -> str:
    rendered = widget.render()
    return rendered.plain if hasattr(rendered, "plain") else str(rendered)


def _rightmost_ink(widget) -> int:
    """The last plot column holding anything, or -1. Blank braille is U+2800."""
    rightmost = -1
    for line in _plain(widget).splitlines():
        _, sep, cells = line.partition("│")
        if not sep:
            continue
        for column, glyph in enumerate(cells):
            if glyph != BRAILLE_BLANK:
                rightmost = max(rightmost, column)
    return rightmost


async def _settle(pilot) -> None:
    """Pause ingestion and wait out the records already in flight.

    Pressing space stops the reader, but records queued before it are still
    delivered, and each one bumps the message count that the redraw gate keys
    on. Without waiting for that to finish, a test meant to prove a keypress
    reached the plot would instead be riding on an arrival.
    """
    await pilot.press("space")
    await asyncio.sleep(0.4)
    await pilot.pause()


def _colours(widget) -> set[tuple[int, int, int]]:
    """Every colour the widget actually drew with, as rgb.

    Textual spells a rendered style two ways depending on where the colour
    came from — ``ansi_bright_green`` for a named one, ``rgb(0,200,150)``
    for a hex one — and a palette holds both kinds. Comparing rgb keeps the
    assertions about the colour rather than about the spelling.
    """
    return {
        _rgb(str(span.style).removesuffix(" bold"))
        for span in widget.render().spans
        if span.style is not None
    }


def _rgb(colour: str) -> tuple[int, int, int]:
    return tuple(Style.parse(colour.removeprefix("ansi_")).color.get_truecolor())


def test_app_ingests_and_renders_both_streams():
    async def scenario() -> tuple[LiveState, str, str]:
        app, state = _build()
        async with app.run_test(size=(100, 32)) as pilot:
            await asyncio.sleep(2.0)
            await pilot.pause()
            wind = _plain(app.query_one("#wind-plot", StreamPanel))
            gas = _plain(app.query_one("#gas-plot", StreamPanel))
        return state, wind, gas

    state, wind, gas = asyncio.run(scenario())

    assert state.sonic_health.messages > 0, "no sonicshow messages ingested"
    assert state.gas_health.messages > 0, "no analyzer records ingested"
    assert state.sonic_health.errors == 0
    assert state.gas_health.errors == 0

    # Something was actually drawn, not just an empty braille grid.
    assert any(ch > BRAILLE_BLANK for ch in wind), "wind plot is blank"
    assert any(ch > BRAILLE_BLANK for ch in gas), "gas plot is blank"


def test_blocks_glyphs_reach_the_panels():
    """``--glyphs blocks`` has to survive the trip from the CLI to the cells.

    The mode exists for the Linux virtual console attached to the logging host,
    where a braille plot draws as rows of replacement boxes. A plot that still
    contained one braille character would be just as unreadable there, so the
    check is that none is left, not that blocks appeared.
    """

    async def scenario() -> tuple[str, str]:
        app, _ = _build(glyphs=BLOCKS)
        async with app.run_test(size=(100, 32)) as pilot:
            await asyncio.sleep(2.0)
            await pilot.pause()
            wind = _plain(app.query_one("#wind-plot", StreamPanel))
            gas = _plain(app.query_one("#gas-plot", StreamPanel))
        return wind, gas

    wind, gas = asyncio.run(scenario())

    for name, drawn in (("wind", wind), ("gas", gas)):
        assert not any(ch >= BRAILLE_BLANK for ch in drawn), f"{name} plot still has braille"
        assert any(ch in (BLOCK_UPPER, BLOCK_LOWER, BLOCK_FULL) for ch in drawn), f"{name} plot is blank"


def test_wind_header_reports_turbulence():
    async def scenario() -> str:
        app, _ = _build()
        async with app.run_test(size=(120, 32)) as pilot:
            await asyncio.sleep(2.0)
            await pilot.pause()
            return _plain(app.query_one("#wind-plot", StreamPanel)).splitlines()[0]

    header = asyncio.run(scenario())
    assert "TKE" in header, header
    assert "sw" in header, header


class TestHeaderDegradation:
    """The header must shed parts rather than wrap: a second row costs a plot row."""

    CHIPS = [
        ("U", "  2.15", "bright_cyan"),
        ("V", "  0.08", "bright_magenta"),
        ("W", "  0.21", "bright_yellow"),
    ]
    PARTS = [
        ("m s-1   sd 0.40 0.32 0.24", WIDTH_FOR_DEVIATIONS),
        ("sw 0.24  TKE 0.31", WIDTH_FOR_TURBULENCE),
    ]
    META = "1 Hz sonicshow  ·  last 180 s"

    def _header(self, width: int) -> str:
        return _header_line("wind", self.CHIPS, self.PARTS, self.META, width).plain

    def test_fits_the_width_it_is_given(self):
        # Below the width of the value chips themselves nothing can be dropped
        # any further; that floor is unchanged by what the parts cost.
        floor = 34
        too_wide = [
            width
            for width in range(floor, 400)
            if len(_header_line("wind", self.CHIPS, self.PARTS, self.META, width)) > width
        ]
        assert not too_wide, f"header overflowed at widths {too_wide[:5]}"

    def test_turbulence_outlives_the_per_component_deviations(self):
        header = self._header(WIDTH_FOR_DEVIATIONS - 1)
        assert "TKE" in header
        assert " sd " not in header

    def test_widest_layout_carries_everything(self):
        header = self._header(WIDTH_FOR_DEVIATIONS)
        assert " sd " in header and "TKE" in header and "m s-1" in header

    def test_metadata_is_the_last_to_go(self):
        assert "sonicshow" in self._header(WIDTH_FOR_META)
        assert "sonicshow" not in self._header(WIDTH_FOR_META - 1)


def test_pause_stops_ingestion():
    async def scenario() -> tuple[int, int]:
        app, state = _build()
        async with app.run_test(size=(100, 32)) as pilot:
            await asyncio.sleep(1.0)
            await pilot.press("space")
            await pilot.pause()
            paused_at = state.gas_health.messages
            await asyncio.sleep(1.0)
            await pilot.pause()
            after = state.gas_health.messages
        return paused_at, after

    paused_at, after = asyncio.run(scenario())
    assert paused_at > 0, "nothing arrived before pausing"
    assert after == paused_at, "records kept arriving while paused"


def test_reset_clears_the_series():
    async def scenario() -> tuple[int, int]:
        app, state = _build()
        async with app.run_test(size=(100, 32)) as pilot:
            await asyncio.sleep(1.5)
            await pilot.pause()
            before = len(state.gas)
            await pilot.press("r")
            await pilot.pause()
            after = len(state.gas)
        return before, after

    before, after = asyncio.run(scenario())
    assert before > 0
    assert after < before


def test_the_header_names_the_build():
    # A screenshot from a logging host has to say which version drew it.
    async def scenario() -> str:
        app, _ = _build()
        async with app.run_test(size=(100, 32)):
            return str(app.sub_title)

    subtitle = asyncio.run(scenario())
    assert f"v{__version__}" in subtitle
    assert "test" in subtitle, "the source description survives alongside it"


class TestSharedWindow:
    """Both plots must span the same seconds, or peaks cannot be compared."""

    @staticmethod
    def _metas(app) -> tuple[str, str]:
        wind = _plain(app.query_one("#wind-plot", StreamPanel)).splitlines()[0]
        gas = _plain(app.query_one("#gas-plot", StreamPanel)).splitlines()[0]
        return wind, gas

    @staticmethod
    def _reported(meta: str) -> float:
        return float(meta.split("last ")[1].split(" s")[0])

    def test_both_panels_report_the_same_range(self):
        async def scenario() -> tuple[str, str, float, float]:
            app, _ = _build()
            async with app.run_test(size=(100, 32)) as pilot:
                await asyncio.sleep(1.5)
                await pilot.pause()
                wind, gas = self._metas(app)
                return wind, gas, app.window_seconds, app.visible_seconds(app.state.elapsed)

        wind, gas, selected, visible = asyncio.run(scenario())
        assert selected == 60.0, "the default range is one minute"
        assert self._reported(wind) == self._reported(gas), "the panels disagree"
        assert self._reported(wind) == pytest.approx(visible, abs=1.0)

    def test_the_window_opens_as_the_data_arrives(self):
        """It grows into the selected range instead of starting at full width.

        A fresh start otherwise draws a few seconds of trace against the right
        edge of a minute of blank, which on a logging host reads as a stream
        that is not arriving.
        """

        async def scenario() -> tuple[float, list[float]]:
            app, _ = _build()
            async with app.run_test(size=(100, 32)) as pilot:
                await asyncio.sleep(1.0)
                await pilot.pause()
                # Sampled rather than waited out: the growth is a function of
                # elapsed time, so a test that slept through it would spend a
                # minute proving arithmetic.
                return self._reported(self._metas(app)[1]), [
                    app.visible_seconds(t) for t in (0.0, 1.0, 30.0, 59.0, 90.0)
                ]

        reported, curve = asyncio.run(scenario())
        assert reported < 60.0, "it started at the full range instead of growing"
        assert curve == [5.0, 5.0, 30.0, 59.0, 60.0]

    def test_widening_uncovers_history_the_narrower_view_was_hiding(self):
        # The buffers hold well past the longest window, so stepping up shows
        # data that was there all along rather than padding blank space.
        buffer = SeriesBuffer(12000)
        last = 0.0
        for index in range(4000):  # 200 s at 20 Hz
            last = index * 0.05
            buffer.append(last, 1.0)
        narrow = buffer.window_values(60.0, now=last)
        wide = buffer.window_values(120.0, now=last)
        assert len(wide) == pytest.approx(2 * len(narrow), rel=0.01)
        assert not any(math.isnan(value) for value in wide), "padded instead of digging"

    def test_the_range_keys_move_both_panels_together(self):
        async def scenario() -> list[tuple[float, str, str]]:
            app, state = _build()
            seen = []
            async with app.run_test(size=(100, 32)) as pilot:
                await asyncio.sleep(1.5)
                # Paused, so nothing arrives to redraw the panels for us: the
                # keys have to reach the plot on their own.
                await _settle(pilot)
                arrivals = state.gas_health.messages
                for key in ("minus", "minus", "plus", "equals_sign"):
                    await pilot.press(key)
                    await asyncio.sleep(0.3)
                    await pilot.pause()
                    seen.append((app.window_seconds, *self._metas(app)))
                assert state.gas_health.messages == arrivals, "not actually paused"
            return seen

        seen = asyncio.run(scenario())
        assert [window for window, _, _ in seen] == [30.0, 15.0, 30.0, 60.0]
        for _, wind, gas in seen:
            # The number itself is capped by how long there has been to fill
            # it; what must hold at every step is that both panels agree.
            assert self._reported(wind) == self._reported(gas)

    def test_the_range_stops_at_both_ends(self):
        async def scenario() -> tuple[float, float]:
            app, _ = _build()
            async with app.run_test(size=(100, 32)) as pilot:
                await asyncio.sleep(0.5)
                for _ in range(len(WINDOW_STEPS) + 2):
                    await pilot.press("minus")
                await pilot.pause()
                shortest = app.window_seconds
                for _ in range(len(WINDOW_STEPS) + 2):
                    await pilot.press("plus")
                await pilot.pause()
                return shortest, app.window_seconds

        shortest, longest = asyncio.run(scenario())
        assert shortest == min(WINDOW_STEPS)
        assert longest == max(WINDOW_STEPS)


    def test_a_silent_stream_scrolls_out_instead_of_freezing(self):
        """The window ends now, not at whatever moment the stream stopped.

        Anchored to the last arrival, a dead analyzer keeps drawing a full,
        healthy-looking trace against the right edge while the header claims
        the same seconds as the panel above it — the two plots then disagree
        about when things happened, silently.
        """

        async def scenario() -> tuple[int, int]:
            app, _ = _build()
            async with app.run_test(size=(100, 32)) as pilot:
                await asyncio.sleep(1.5)
                await pilot.press("minus")  # 15 s, so the trace recedes visibly
                await pilot.press("minus")
                await _settle(pilot)
                first = _rightmost_ink(app.query_one("#gas-plot", StreamPanel))
                await asyncio.sleep(3.0)
                await pilot.pause()
                return first, _rightmost_ink(app.query_one("#gas-plot", StreamPanel))

        first, later = asyncio.run(scenario())
        assert first > 0, "nothing was drawn to begin with"
        assert later < first, "the trace stayed put while the stream was silent"


class TestPalettes:
    def test_every_palette_offers_four_distinct_colours(self):
        for palette in PALETTES:
            colours = [*palette.wind, palette.gas]
            assert len(set(colours)) == 4, f"{palette.name} repeats a colour"

    def test_the_key_cycles_and_wraps(self):
        async def scenario() -> list[str]:
            app, _ = _build()
            async with app.run_test(size=(100, 32)) as pilot:
                await asyncio.sleep(0.5)
                names = [app.palette.name]
                for _ in range(len(PALETTES)):
                    await pilot.press("c")
                    await pilot.pause()
                    names.append(app.palette.name)
            return names

        names = asyncio.run(scenario())
        assert names[0] == PALETTES[0].name, "the ANSI-safe palette is the default"
        assert names[: len(PALETTES)] == [palette.name for palette in PALETTES]
        assert names[-1] == names[0], "cycling wraps back to the first"

    def test_the_new_colours_reach_the_plot_without_a_new_message(self):
        # The redraw gate keys on arrivals and size, so a palette change has to
        # be part of what it compares or the keypress would do nothing visible.
        async def scenario() -> tuple[set[tuple[int, int, int]], set[tuple[int, int, int]], str]:
            app, state = _build()
            async with app.run_test(size=(100, 32)) as pilot:
                await asyncio.sleep(1.5)
                # Paused first, or the simulator's next record would redraw the
                # panel regardless and the test would pass without the palette
                # ever having reached the redraw gate.
                await _settle(pilot)
                arrivals = state.gas_health.messages
                before = _colours(app.query_one("#gas-plot", StreamPanel))
                await pilot.press("c")
                await asyncio.sleep(0.3)
                await pilot.pause()
                after = _colours(app.query_one("#gas-plot", StreamPanel))
                assert state.gas_health.messages == arrivals, "not actually paused"
                return before, after, app.palette.gas

        before, after, gas_colour = asyncio.run(scenario())
        assert _rgb(PALETTES[0].gas) in before
        assert _rgb(gas_colour) in after
        assert _rgb(PALETTES[0].gas) not in after
