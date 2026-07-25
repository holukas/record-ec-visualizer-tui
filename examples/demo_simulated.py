"""Run the visualizer against a simulated rECorD installation.

Nothing external is needed: no rECorD, no configuration, no network. The
simulator emits data in rECorD's own wire format, so what you see on screen has
travelled the same decode path that live data will.

Run it directly::

    python examples/demo_simulated.py

or, from a checkout that has not been installed::

    uv run python examples/demo_simulated.py

Keys: ``q`` quit, ``space`` pause, ``r`` reset the series.

The constants below are the interesting knobs. Everything else lives in
:class:`~record_ec_visualizer_tui.simulator.SimulationConfig`.
"""
from __future__ import annotations

from record_ec_visualizer_tui.codec import VariableMap
from record_ec_visualizer_tui.model import LiveState
from record_ec_visualizer_tui.simulator import RecordSimulator, SimulationConfig
from record_ec_visualizer_tui.sources import simulated_lines
from record_ec_visualizer_tui.tui.app import VisualizerApp

#: Seed the generator so a run is reproducible. None gives a different run each time.
SEED: int | None = 0

#: Faster than real time. Careful above ~5: staleness is measured against the
#: wall clock, so simulated dropouts stop registering as stale.
SPEEDUP = 1.0

#: Interrupt the analyzer stream now and then, to see the staleness display work.
#: Set DROPOUT_EVERY_S to 0 for an uninterrupted stream.
DROPOUT_EVERY_S = 45.0
DROPOUT_LENGTH_S = 4.0

#: Which analyzer variable to plot. "CO2" is the mixing ratio in umol mol-1;
#: "CO2_CONC" would be the molar density the same record also carries.
GAS_VAR = "CO2"


def build_app() -> VisualizerApp:
    """Wire a simulator, the decoding state, and the TUI together."""
    config = SimulationConfig(
        seed=SEED,
        dropout_every_s=DROPOUT_EVERY_S,
        dropout_length_s=DROPOUT_LENGTH_S,
    )

    # The var_maps are the same shape a site's record.toml carries, which is why
    # the display shows U/V/W rather than the sonic's raw Wc1/Wc2/Wc3 keys.
    state = LiveState(
        gas_var=GAS_VAR,
        sonic_map=VariableMap(config.sonic_var_map),
        gas_map=VariableMap(config.var_map),
    )

    lines = simulated_lines(RecordSimulator(config), speedup=SPEEDUP)
    return VisualizerApp(lines, state, subtitle=f"simulated · {config.ga_name}")


if __name__ == "__main__":
    build_app().run()
