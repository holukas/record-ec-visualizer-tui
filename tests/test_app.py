"""Headless smoke tests: the app must actually ingest and draw."""
import asyncio

from record_ec_visualizer_tui.codec import VariableMap
from record_ec_visualizer_tui.model import LiveState
from record_ec_visualizer_tui.simulator import RecordSimulator, SimulationConfig
from record_ec_visualizer_tui.sources import simulated_lines
from record_ec_visualizer_tui.tui.app import (
    WIDTH_FOR_DEVIATIONS,
    WIDTH_FOR_META,
    WIDTH_FOR_TURBULENCE,
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
