"""Headless smoke tests: the app must actually ingest and draw."""
import asyncio

from record_ec_visualizer_tui.codec import VariableMap
from record_ec_visualizer_tui.model import LiveState
from record_ec_visualizer_tui.simulator import RecordSimulator, SimulationConfig
from record_ec_visualizer_tui.sources import simulated_lines
from record_ec_visualizer_tui.tui.app import StreamPanel, VisualizerApp
from record_ec_visualizer_tui.tui.plot import BRAILLE_BASE

BRAILLE_BLANK = chr(BRAILLE_BASE)


def _build() -> tuple[VisualizerApp, LiveState]:
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
