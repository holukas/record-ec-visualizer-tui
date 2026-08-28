"""The Eddy Derby screen: lanes, a live CO2 meter, and a finish line.

A screen rather than a third panel. The live view is deliberately frugal --
every row it does not spend on decoration is a row of plot -- and a track
wedged into it would cost those rows permanently, for a game that is played for
ten minutes at an open day and never again that week. As a separate screen it
costs nothing at all while it is not up, and the plots underneath are not drawn
while it is.

The stream keeps arriving throughout either way: decoding runs as an app worker,
not as anything belonging to a screen, so the buffers behind the plots stay
correct and the derby is fed sample by sample rather than frame by frame.

Everything here is ASCII. The screen this is aimed at is the monitor attached to
the logging host, a Linux virtual console whose font holds 256 or 512 glyphs --
the same limitation that makes braille plots unreadable there and that
``--glyphs blocks`` exists for.
"""
from __future__ import annotations

import math
from collections.abc import Callable

from rich.text import Text
from textual.app import ComposeResult
from textual.screen import Screen
from textual.widgets import Footer, Header, Static

from record_ec_visualizer_tui.game import EddyDerby, Racer
from record_ec_visualizer_tui.model import LiveState

#: Top of the live meter, umol mol-1: the measurement range of an open-path
#: head, which is also where a real breath pins it. A meter scaled to the
#: reading instead would rescale on every puff and show nothing about how close
#: to saturation the number is.
METER_MAX_PPM = 3000.0

#: Cells of the CO2 meter bar.
METER_WIDTH = 30

#: Widest a lane's name column is allowed to get.
NAME_WIDTH = 12

#: Least track a lane is drawn on, however narrow the terminal.
MIN_TRACK = 12

#: Below this the title line drops its explanation rather than wrapping.
WIDTH_FOR_HINT = 88


class DerbyScreen(Screen[None]):
    """One screen: the meter, the lanes, and whatever the derby has to say."""

    DEFAULT_CSS = """
    DerbyScreen #derby {
        padding: 1 2;
    }
    """

    BINDINGS = [
        # On the screen rather than on the app, so they shadow the live view's
        # own r/space bindings while the derby is up: 'r' here is the derby, not
        # the plots.
        ("escape,g", "close", "Back to plots"),
        ("r", "reset_derby", "Restart derby"),
        ("a", "add_player", "Add lane"),
        ("x", "remove_player", "Drop lane"),
        ("n", "skip_turn", "Skip turn"),
    ]

    def __init__(
        self,
        state: LiveState,
        derby: EddyDerby,
        on_blow: Callable[[], None] | None = None,
        refresh_hz: float = 10.0,
    ) -> None:
        super().__init__()
        self.state = state
        self.derby = derby
        self._on_blow = on_blow
        self._interval = 1.0 / max(1.0, refresh_hz)

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(id="derby")
        yield Footer()

    def on_mount(self) -> None:
        self._board = self.query_one("#derby", Static)
        self.set_interval(self._interval, self._refresh)
        self._refresh()

    def action_close(self) -> None:
        self.app.pop_screen()

    def action_reset_derby(self) -> None:
        self.derby.reset()
        self._refresh()

    def action_add_player(self) -> None:
        self.derby.add_player()
        self._refresh()

    def action_remove_player(self) -> None:
        self.derby.remove_player()
        self._refresh()

    def action_skip_turn(self) -> None:
        self.derby.skip_turn()
        self._refresh()

    def _refresh(self) -> None:
        self._board.update(self.render_board(self.size.width))

    def render_board(self, width: int) -> Text:
        """The whole screen as one ``Text``, sized to ``width`` cells."""
        width = max(40, width - 4)
        state = self.state
        derby = self.derby
        threshold = derby.detector.threshold

        text = Text()
        text.append("EDDY DERBY", style="bold")
        if width >= WIDTH_FOR_HINT:
            # The rule of the game, and the only instruction a visitor needs.
            # Dropped rather than wrapped on a narrow terminal, where the lanes
            # are what has to fit.
            text.append(
                f"   breathe at the analyzer inlet - only {threshold:.0f}"
                f" {state.gas_units or 'ppm'} and above moves an animal",
                style="grey50",
            )
        text.append("\n\n")

        self._append_meter(text, threshold)
        text.append("\n")

        # The finish line is a score, and until the first breath has been taken
        # there may not be one yet. Saying so is better than drawing a track
        # with no end on it and leaving the player to guess.
        if derby.goal:
            text.append("finish line ", style="grey50")
            text.append(f"{derby.goal:,.0f}", style="bold")
            text.append(" ppm s", style="grey50")
        else:
            # Nothing has set a scale yet, so the lanes cannot show a position.
            # The score beside each lane still counts up while somebody blows,
            # which is the feedback that matters until there is a track.
            text.append("the first breath of the session sets the finish line", style="grey50")
        text.append("\n\n")

        name_width = min(NAME_WIDTH, max(len(racer.name) for racer in derby.racers))
        # Marker, name, two separating spaces, and the score column at the end.
        track_width = max(MIN_TRACK, width - name_width - 26)
        for racer in derby.racers:
            self._append_lane(text, racer, name_width, track_width)

        text.append("\n")
        self._append_verdict(text)
        return text

    def _append_meter(self, text: Text, threshold: float) -> None:
        """The current reading, as a number and as a bar against the range."""
        state = self.state
        value = state.gas.latest
        stale = state.gas_health.is_stale
        counting = not math.isnan(value) and value > threshold

        text.append(f"{state.gas_var:>4} ", style="grey50")
        if math.isnan(value):
            text.append("   ---- ", style="red")
        else:
            text.append(f"{value:7.0f} ", style="bold green" if counting else "grey85")

        filled = 0 if math.isnan(value) else int(min(1.0, value / METER_MAX_PPM) * METER_WIDTH)
        mark = int(min(1.0, threshold / METER_MAX_PPM) * METER_WIDTH)
        text.append("[", style="grey35")
        for cell in range(METER_WIDTH):
            if cell < filled:
                text.append("#", style="green" if cell >= mark else "grey62")
            elif cell == mark:
                # Where the scoring starts, kept visible even when the bar has
                # not reached it: it is the thing the player is aiming at.
                text.append("|", style="yellow")
            else:
                text.append("-", style="grey35")
        text.append("]", style="grey35")

        ambient = state.gas.latest if math.isnan(self.derby.detector.ambient) else self.derby.detector.ambient
        if not math.isnan(ambient):
            text.append(f"  ambient {ambient:.0f}", style="grey50")

        puff = self.derby.detector.active
        if puff is not None:
            text.append(f"   this breath {puff.score:,.0f} ppm s", style="bold")
            text.append(f" ({puff.duration:.1f} s)", style="grey50")
        elif getattr(self.app, "paused", False):
            # Space pauses the whole app, records included, which stops the
            # game dead. Saying so beats the staleness message below, which
            # would blame an analyzer that is delivering perfectly well.
            text.append("   PAUSED - space resumes", style="bold black on yellow")
        elif stale:
            # Without the analyzer there is no game, and an empty track looks
            # exactly like a player who has not blown yet.
            text.append("   analyzer silent", style="bold red")
        text.append("\n")

    def _append_lane(self, text: Text, racer: Racer, name_width: int, track_width: int) -> None:
        derby = self.derby
        is_turn = racer is derby.active

        text.append(">" if is_turn else " ", style="bold" if is_turn else "grey35")
        text.append(" ")
        text.append(
            racer.name[:name_width].ljust(name_width),
            style=f"bold {racer.color}" if is_turn else racer.color,
        )
        text.append(" ")

        # The track: trail behind, animal, open ground ahead, finish line. The
        # animal's nose is what reaches the line, so lanes stay comparable
        # however wide the different animals are.
        inner = max(1, track_width - 1)
        animal = racer.animal[:inner]
        start = round(derby.fraction_of(racer) * max(0, inner - len(animal)))
        text.append("." * start, style="grey35")
        text.append(animal, style=f"bold {racer.color}")
        text.append(" " * max(0, inner - start - len(animal)))
        text.append("|", style="grey50" if not racer.finished else f"bold {racer.color}")

        distance = derby.distance_of(racer)
        text.append(f" {distance:8,.0f}", style=racer.color if distance else "grey35")
        text.append(f" {racer.breaths:2d} breaths", style="grey50")
        if racer.place is not None:
            text.append(f"  #{racer.place}", style=f"bold {racer.color}")
        text.append("\n")

    def _append_verdict(self, text: Text) -> None:
        derby = self.derby
        if derby.over:
            winner = derby.standings[0]
            text.append("WINNER  ", style="bold")
            text.append(winner.name, style=f"bold {winner.color}")
            text.append(
                f"   best breath {winner.best_breath:,.0f} ppm s, peak {winner.peak:.0f}"
                f" in {winner.breaths} breaths   -   r starts a new derby\n",
                style="grey50",
            )
            return
        racer = derby.active
        if racer is not None:
            text.append("up next  ", style="grey50")
            text.append(racer.name, style=f"bold {racer.color}")
            if self._on_blow is not None:
                text.append("      b breathes for you (demo)", style="grey50")
            text.append("\n")
