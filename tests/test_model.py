import math
import time

import pytest

from record_ec_visualizer_tui.codec import VariableMap
from record_ec_visualizer_tui.model import WIND_RAW_KEYS, LiveState, SeriesBuffer, StreamHealth


class TestSeriesBuffer:
    def test_keeps_only_the_most_recent_samples(self):
        buffer = SeriesBuffer(3)
        for index in range(5):
            buffer.append(float(index), float(index))
        assert buffer.values == [2.0, 3.0, 4.0]

    def test_none_is_stored_as_nan(self):
        buffer = SeriesBuffer(3)
        buffer.append(0.0, None)
        assert math.isnan(buffer.values[0])

    def test_latest_skips_missing_values(self):
        buffer = SeriesBuffer(4)
        buffer.append(0.0, 1.5)
        buffer.append(1.0, None)
        assert buffer.latest == 1.5

    def test_latest_is_nan_when_empty(self):
        assert math.isnan(SeriesBuffer(3).latest)

    def test_span_seconds(self):
        buffer = SeriesBuffer(4)
        buffer.append(10.0, 1.0)
        buffer.append(13.5, 1.0)
        assert buffer.span_seconds() == 3.5

    def test_span_of_single_sample_is_zero(self):
        buffer = SeriesBuffer(4)
        buffer.append(10.0, 1.0)
        assert buffer.span_seconds() == 0.0


class TestGapDetection:
    """An outage must leave a hole, not close up and compress the time axis."""

    @staticmethod
    def _fill(buffer: SeriesBuffer, count: int, interval: float, start: float = 0.0) -> float:
        elapsed = start
        for _ in range(count):
            buffer.append(elapsed, 1.0)
            elapsed += interval
        return elapsed

    def test_learns_the_cadence_from_the_stream(self):
        # The rate is a per-site setting this package does not hardcode, so it
        # is inferred from arrivals instead.
        buffer = SeriesBuffer(2000, detect_gaps=True)
        self._fill(buffer, 200, 0.05)
        assert buffer.interval == pytest.approx(0.05, rel=1e-6)

    def test_learns_a_slow_cadence_just_as_well(self):
        buffer = SeriesBuffer(2000, detect_gaps=True)
        self._fill(buffer, 30, 1.0)
        assert buffer.interval == pytest.approx(1.0, rel=1e-6)

    def test_late_arrival_fills_the_slots_it_missed(self):
        buffer = SeriesBuffer(2000, detect_gaps=True)
        elapsed = self._fill(buffer, 200, 0.05)
        buffer.append(elapsed + 4.0 - 0.05, 1.0)  # a 4 s outage at 20 Hz
        assert sum(1 for value in buffer.values if math.isnan(value)) == 79

    def test_no_padding_for_ordinary_jitter(self):
        buffer = SeriesBuffer(2000, detect_gaps=True)
        elapsed = self._fill(buffer, 200, 0.05)
        buffer.append(elapsed + 0.08, 1.0)  # late, but not by much
        assert not any(math.isnan(value) for value in buffer.values)

    def test_outage_does_not_corrupt_the_cadence_estimate(self):
        buffer = SeriesBuffer(2000, detect_gaps=True)
        elapsed = self._fill(buffer, 200, 0.05)
        buffer.append(elapsed + 4.0, 1.0)
        assert buffer.interval == pytest.approx(0.05, rel=1e-6)

    def test_padding_is_capped_at_the_buffer_length(self):
        # A machine left running over a weekend outage must not spin.
        buffer = SeriesBuffer(50, detect_gaps=True)
        elapsed = self._fill(buffer, 20, 0.05)
        buffer.append(elapsed + 3600.0, 1.0)
        assert len(buffer) == 50

    def test_disabled_by_default(self):
        buffer = SeriesBuffer(2000)
        elapsed = self._fill(buffer, 200, 0.05)
        buffer.append(elapsed + 4.0, 1.0)
        assert not any(math.isnan(value) for value in buffer.values)

    def test_clear_forgets_the_cadence(self):
        buffer = SeriesBuffer(2000, detect_gaps=True)
        self._fill(buffer, 200, 0.05)
        buffer.clear()
        assert buffer.interval is None

    def test_wind_series_stay_aligned_across_a_gap(self):
        # The three buffers learn independently; they must still pad in step,
        # or the components would be drawn shifted against each other.
        state = _state()
        for second in range(10):
            state.ingest_sonicshow({key: "1.00(0.10)" for key in WIND_RAW_KEYS})
            state._start -= 1.0  # advance the clock a second per message
        state._start -= 6.0  # a six second outage
        state.ingest_sonicshow({key: "2.00(0.10)" for key in WIND_RAW_KEYS})

        lengths = {key: len(state.wind[key]) for key in WIND_RAW_KEYS}
        assert len(set(lengths.values())) == 1, f"series drifted apart: {lengths}"
        assert any(math.isnan(value) for value in state.wind["Wc1"].values)


class TestStreamHealth:
    def test_starts_with_no_data_and_counts_as_stale(self):
        health = StreamHealth("x")
        assert health.age() is None
        assert health.is_stale

    def test_fresh_after_a_message(self):
        health = StreamHealth("x")
        health.mark_message()
        assert not health.is_stale
        assert health.age() < 0.5

    def test_goes_stale_after_the_threshold(self):
        health = StreamHealth("x", stale_after=0.05)
        health.mark_message()
        time.sleep(0.08)
        assert health.is_stale

    def test_errors_are_counted_separately_from_messages(self):
        health = StreamHealth("x")
        health.mark_message()
        health.mark_error("bad line")
        assert (health.messages, health.errors) == (1, 1)
        assert health.last_error == "bad line"


def _state() -> LiveState:
    return LiveState(
        gas_var="CO2",
        sonic_map=VariableMap({"Wc1": "U", "Wc2": "V", "Wc3": "W"}),
        gas_map=VariableMap({"Data": {"CO2": "CO2"}}),
    )


class TestSonicshowIngestion:
    def test_reads_means_and_deviations(self):
        state = _state()
        state.ingest_sonicshow({"Wc1": "2.50(0.40)", "Wc2": "-0.10(0.30)", "Wc3": "0.05(0.20)"})
        assert state.wind["Wc1"].latest == 2.5
        assert state.wind_stdev["Wc2"].latest == 0.3

    def test_series_stay_aligned_when_a_component_is_missing(self):
        # The plot maps sample index to x, so a series that skipped an entry
        # would be drawn shifted against the others for the rest of the run.
        state = _state()
        state.ingest_sonicshow({"Wc1": "1.00(0.10)", "Wc2": "1.00(0.10)", "Wc3": "1.00(0.10)"})
        state.ingest_sonicshow({"Wc1": "2.00(0.10)"})  # Wc2 and Wc3 absent
        state.ingest_sonicshow({"Wc1": "3.00(0.10)", "Wc2": "3.00(0.10)", "Wc3": "3.00(0.10)"})

        lengths = {key: len(state.wind[key]) for key in WIND_RAW_KEYS}
        assert set(lengths.values()) == {3}, f"series drifted out of alignment: {lengths}"
        assert math.isnan(state.wind["Wc2"].values[1])
        assert state.wind["Wc2"].values[2] == 3.0

    def test_series_stay_aligned_when_a_value_is_unparseable(self):
        state = _state()
        state.ingest_sonicshow({"Wc1": "1.00(0.10)", "Wc2": "1.00(0.10)", "Wc3": "1.00(0.10)"})
        state.ingest_sonicshow({"Wc1": "2.00(0.10)", "Wc2": "rubbish", "Wc3": "2.00(0.10)"})
        assert {len(state.wind[key]) for key in WIND_RAW_KEYS} == {2}
        assert state.sonic_health.errors == 1

    def test_buffer_fills_are_unpacked_diagnostics(self):
        state = _state()
        state.ingest_sonicshow({"sonic_buffer": "198/200", "irga_freq": 19.9})
        assert state.diagnostics["sonic_buffer"] == (198, 200)
        assert state.diagnostics["irga_freq"] == 19.9

    def test_unparseable_buffer_is_kept_verbatim(self):
        state = _state()
        state.ingest_sonicshow({"sonic_buffer": "weird"})
        assert state.diagnostics["sonic_buffer"] == "weird"


class TestTurbulence:
    """sw and TKE come free with every sonicshow message."""

    def test_tke_sums_the_three_deviations(self):
        state = _state()
        state.ingest_sonicshow({"Wc1": "2.50(0.40)", "Wc2": "0.10(0.30)", "Wc3": "0.05(0.20)"})
        assert state.tke == pytest.approx(0.5 * (0.16 + 0.09 + 0.04))
        assert state.sigma_w == pytest.approx(0.20)

    def test_no_tke_before_every_component_has_been_seen(self):
        # Two of three would look like a plausible number and read low.
        state = _state()
        state.ingest_sonicshow({"Wc1": "2.50(0.40)", "Wc2": "0.10(0.30)"})
        assert math.isnan(state.tke)
        assert math.isnan(state.sigma_w)

    def test_nothing_to_report_before_the_first_message(self):
        assert math.isnan(_state().tke)

    def test_calmer_air_gives_less_turbulent_energy(self):
        gusty, calm = _state(), _state()
        gusty.ingest_sonicshow({"Wc1": "2.50(0.90)", "Wc2": "0.10(0.80)", "Wc3": "0.05(0.60)"})
        calm.ingest_sonicshow({"Wc1": "2.50(0.09)", "Wc2": "0.10(0.08)", "Wc3": "0.05(0.06)"})
        assert gusty.tke > calm.tke


class TestGasIngestion:
    def test_plots_the_mapped_variable(self):
        state = _state()
        state.ingest_ga({"Data": {"CO2": 421.5}})
        assert state.gas.latest == 421.5

    def test_record_without_the_variable_breaks_the_line(self):
        state = _state()
        state.ingest_ga({"Data": {"CO2": 421.5}})
        state.ingest_ga({"Data": {"H2O": 12.0}})
        assert math.isnan(state.gas.values[-1])
        # It still counts as liveness: the analyzer is talking.
        assert state.gas_health.messages == 2

    def test_send_buffer_is_surfaced(self):
        state = _state()
        state.ingest_ga({"Data": {"CO2": 1.0}, "Auxiliary": {"BufferSize": 7}})
        assert state.diagnostics["ga_send_buffer"] == 7


class TestReset:
    def test_clears_series_but_keeps_counters(self):
        state = _state()
        state.ingest_sonicshow({"Wc1": "1.00(0.10)"})
        state.ingest_ga({"Data": {"CO2": 1.0}})
        state.reset()
        assert len(state.wind["Wc1"]) == 0
        assert len(state.gas) == 0
        assert state.sonic_health.messages == 1
        assert state.gas_health.messages == 1


class TestLabels:
    def test_uses_the_site_variable_name(self):
        assert _state().label_for("Wc1") == "U"

    def test_falls_back_to_the_raw_key(self):
        assert LiveState().label_for("Wc1") == "Wc1"
