"""The simulator's job is to be indistinguishable from rECorD on the wire.

These tests therefore check the *bytes*, and push them through the real decode
path rather than inspecting the simulator's internals.
"""
import json
import math

from record_ec_visualizer_tui.codec import (
    VariableMap,
    parse_ga_message,
    parse_mean_stdev,
    parse_show_message,
)
from record_ec_visualizer_tui.model import LiveState
from record_ec_visualizer_tui.simulator import (
    SONICSHOW_STREAM,
    RecordSimulator,
    SimulationConfig,
)


def _run(ticks: int, **config_kwargs) -> list[tuple[str, bytes]]:
    simulator = RecordSimulator(SimulationConfig(**config_kwargs))
    return list(simulator.iter_lines(ticks))


class TestWireFormat:
    def test_sonicshow_is_a_python_repr_not_json(self):
        lines = _run(20)
        show = [payload for name, payload in lines if name == SONICSHOW_STREAM]
        assert show, "expected one sonicshow message after 20 records at 20 Hz"
        # Single-quoted, so it must fail as JSON and succeed as a Python literal.
        try:
            json.loads(show[0])
        except json.JSONDecodeError:
            pass
        else:  # pragma: no cover - would mean the format drifted
            raise AssertionError("sonicshow payload must not be valid JSON")
        assert isinstance(parse_show_message(show[0]), dict)

    def test_gas_analyzer_line_is_real_json(self):
        lines = _run(1)
        ga = [payload for name, payload in lines if name.startswith("ga:")]
        assert ga
        assert isinstance(json.loads(ga[0]), dict)

    def test_lines_carry_no_separator(self):
        # The separator is the transport's business, not the payload's.
        for _, payload in _run(40):
            assert b"\n" not in payload


class TestSonicshowContent:
    def test_reports_the_three_wind_components_as_mean_stdev(self):
        lines = _run(20)
        record = parse_show_message(
            next(payload for name, payload in lines if name == SONICSHOW_STREAM)
        )
        for key in ("Wc1", "Wc2", "Wc3"):
            mean, stdev = parse_mean_stdev(record[key])
            assert math.isfinite(mean)
            assert math.isfinite(stdev)

    def test_reports_buffer_fills_and_analyzer_frequency(self):
        lines = _run(20, ga_name="li7500rs")
        record = parse_show_message(
            next(payload for name, payload in lines if name == SONICSHOW_STREAM)
        )
        assert "/" in record["sonic_buffer"]
        assert "/" in record["li7500rs_buffer"]
        assert record["li7500rs_freq"] == 20.0

    def test_one_message_per_second(self):
        lines = _run(100)  # 5 s at 20 Hz
        count = sum(1 for name, _ in lines if name == SONICSHOW_STREAM)
        assert count == 5

    def test_wind_varies_between_intervals(self):
        # Turbulence has memory, so the 1 Hz means wander rather than sitting on
        # the long-run mean the way averaged white noise would.
        simulator = RecordSimulator(SimulationConfig(seed=7))
        means = [
            parse_mean_stdev(parse_show_message(payload)["Wc3"])[0]
            for name, payload in simulator.iter_lines(2000)
            if name == SONICSHOW_STREAM
        ]
        assert max(means) - min(means) > 0.02, "vertical wind means look constant"


class TestGasAnalyzerContent:
    def test_carries_a_co2_mixing_ratio_in_a_plausible_range(self):
        lines = _run(200)
        values = [
            parse_ga_message(payload)["Data"]["CO2"]
            for name, payload in lines
            if name.startswith("ga:")
        ]
        assert values
        assert all(380.0 < value < 460.0 for value in values)

    def test_nested_the_way_a_var_map_expects(self):
        config = SimulationConfig()
        var_map = VariableMap(config.var_map)
        _, payload = next(item for item in _run(1) if item[0].startswith("ga:"))
        mapped = var_map.apply(parse_ga_message(payload))
        assert "CO2" in mapped
        assert "T_CELL" in mapped

    def test_records_arrive_at_the_configured_rate(self):
        lines = _run(100, dropout_every_s=0.0)
        count = sum(1 for name, _ in lines if name.startswith("ga:"))
        assert count == 100


class TestDropouts:
    def test_analyzer_stream_goes_quiet_and_comes_back(self):
        lines = _run(1400, dropout_every_s=45.0, dropout_length_s=4.0)
        ga_ticks = [name.startswith("ga:") for name, _ in lines]
        assert not all(ga_ticks), "expected a dropout"
        assert any(ga_ticks), "expected data outside the dropout"

    def test_dropout_is_reported_as_zero_frequency(self):
        simulator = RecordSimulator(SimulationConfig(dropout_every_s=45.0, dropout_length_s=4.0))
        frequencies = [
            parse_show_message(payload)["li7500rs_freq"]
            for name, payload in simulator.iter_lines(1400)
            if name == SONICSHOW_STREAM
        ]
        assert 0.0 in frequencies
        assert 20.0 in frequencies

    def test_disabled_dropouts_never_interrupt(self):
        ticks = 1400
        lines = _run(ticks, dropout_every_s=0.0)
        ga_count = sum(1 for name, _ in lines if name.startswith("ga:"))
        assert ga_count == ticks, "every sonic record should carry an analyzer record"


class TestDeterminism:
    def test_same_seed_gives_same_bytes(self):
        assert _run(60, seed=3) == _run(60, seed=3)

    def test_different_seed_gives_different_bytes(self):
        assert _run(60, seed=3) != _run(60, seed=4)


class TestEndToEndIntoState:
    def test_simulated_lines_populate_live_state(self):
        config = SimulationConfig()
        state = LiveState(
            gas_var="CO2",
            sonic_map=VariableMap(config.sonic_var_map),
            gas_map=VariableMap(config.var_map),
        )
        simulator = RecordSimulator(config)
        for name, payload in simulator.iter_lines(100):
            if name == SONICSHOW_STREAM:
                state.ingest_sonicshow(parse_show_message(payload))
            else:
                state.ingest_ga(parse_ga_message(payload))

        assert len(state.wind["Wc1"]) == 5
        assert len(state.gas) == 100
        assert math.isfinite(state.wind["Wc1"].latest)
        assert 380.0 < state.gas.latest < 460.0
        # The sonic var_map should relabel raw keys with the site's names.
        assert state.label_for("Wc1") == "U"
        assert state.label_for("Wc3") == "W"


class TestBreath:
    """``blow()`` is how the Eddy Derby is rehearsed away from a site.

    It has to produce the same thing a real breath does, which for a game
    scored on the area under the peak means one property above all: it clips at
    the configured ceiling. A simulated puff that ran on to 9000 unclipped would
    make a peak-based score look like it worked.
    """

    def test_a_breath_lifts_the_co2_stream_and_comes_back_down(self):
        config = SimulationConfig(seed=1)
        config.dropout_every_s = 0.0
        simulator = RecordSimulator(config)
        map_ = VariableMap(config.var_map)

        def co2_values(ticks):
            values = []
            for name, payload in simulator.iter_lines(ticks):
                if name != SONICSHOW_STREAM:
                    values.append(map_.apply(parse_ga_message(payload))["CO2"])
            return values

        before = co2_values(40)
        simulator.blow(strength=1.0)
        during = co2_values(20)
        after = co2_values(200)

        assert max(before) < 500.0
        assert max(during) > 2000.0, "a breath has to be unmistakable"
        assert after[-1] < 500.0, "and it has to clear again"

    def test_a_breath_saturates_the_analyzer(self):
        config = SimulationConfig(seed=1)
        config.dropout_every_s = 0.0
        simulator = RecordSimulator(config)
        map_ = VariableMap(config.var_map)

        simulator.blow(strength=1.5)
        peak = 0.0
        for name, payload in simulator.iter_lines(100):
            if name != SONICSHOW_STREAM:
                peak = max(peak, map_.apply(parse_ga_message(payload))["CO2"])
        assert peak == config.co2_max_ppm

    def test_breaths_differ_from_each_other(self):
        """Two demo players must not tie by construction."""
        config = SimulationConfig(seed=7)
        simulator = RecordSimulator(config)
        strengths = set()
        for _ in range(5):
            simulator.blow()
            strengths.add(simulator._breath_strength)
        assert len(strengths) == 5
