import math
import random
import time

import pytest

from record_ec_visualizer_tui.codec import VariableMap
from record_ec_visualizer_tui.model import (
    MAX_WINDOW_SECONDS,
    WIND_RAW_KEYS,
    LiveState,
    SeriesBuffer,
    StreamHealth,
)


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

    @staticmethod
    def _stalled(buffer: SeriesBuffer, cycles: int = 40, burst: int = 5, stall: float = 0.25) -> None:
        """Feed a 20 Hz stream the way a consumer that cannot keep up sees it.

        A frame that takes longer than one sampling interval blocks the event
        loop; the records queued behind it then arrive back to back. The stream
        never changed rate — this program did.
        """
        elapsed = 0.0
        for _ in range(cycles):
            for _ in range(burst):
                elapsed += 0.0004  # drained from the backlog, near-simultaneous
                buffer.append(elapsed, 420.0)
            elapsed += stall

    def test_a_burst_does_not_drag_the_cadence_down(self):
        buffer = SeriesBuffer(2000, detect_gaps=True)
        elapsed = self._fill(buffer, 200, 0.05)
        for step in range(1, 6):  # five records straight out of a backlog
            buffer.append(elapsed + step * 0.0004, 420.0)
        # Loose because the first of the five is an ordinary arrival that only
        # happens to be followed by a burst, so it still moves the estimate a
        # little. Before the burst rule it landed near 0.016 instead.
        assert buffer.interval == pytest.approx(0.05, rel=0.01)

    def test_a_stalled_consumer_does_not_flood_the_buffer(self):
        # The failure this guards against was a one-way ratchet: each burst
        # pulled the estimate down, which made the next ordinary arrival look
        # like an outage, which padded hundreds of nan slots and never fed the
        # estimate back up. On the logging host it turned a minute of analyzer
        # data into a two-second window of mostly holes.
        buffer = SeriesBuffer(1200, detect_gaps=True)
        self._stalled(buffer)
        values = buffer.values
        nans = sum(1 for value in values if math.isnan(value))
        assert buffer.interval == pytest.approx(0.05, rel=0.3)
        assert nans < len(values) / 2, f"{nans} of {len(values)} slots are padding"
        assert buffer.span_seconds() == pytest.approx(10.0, rel=0.2)

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


def _or_low(value: float) -> float:
    """nan compares unhelpfully, and a padded window is full of it."""
    return -math.inf if math.isnan(value) else value


class TestWindowValues:
    """Both panels are asked for one duration, so each must answer in slots."""

    @staticmethod
    def _fill(buffer: SeriesBuffer, count: int, interval: float) -> None:
        elapsed = 0.0
        for index in range(count):
            buffer.append(elapsed, float(index))
            elapsed += interval

    def test_slot_count_follows_the_measured_cadence(self):
        fast = SeriesBuffer(4800)
        self._fill(fast, 2400, 0.05)
        assert len(fast.window_values(60.0)) == 1200

    def test_a_moment_lands_in_the_same_place_at_either_rate(self):
        """The point of the whole feature, tested on the thing a viewer does.

        Two streams 20x apart in rate see the same event; it has to land at the
        same fraction of the width in both, or the plots cannot be read against
        each other. Arrivals are jittered, because the slot count comes from an
        estimate and exact synthetic timestamps would never exercise it.
        """
        rng = random.Random(11)
        fast, slow = SeriesBuffer(12000), SeriesBuffer(600)
        spike_at = 150.0
        for buffer, interval in ((fast, 0.05), (slow, 1.0)):
            for index in range(int(200.0 / interval)):
                # Jitter around a fixed schedule, not a random walk: both these
                # streams are driven by a timer, so an arrival is late or early
                # against the nominal grid rather than against its predecessor.
                elapsed = index * interval + rng.uniform(-0.2, 0.2) * interval
                buffer.append(elapsed, 10.0 if abs(elapsed - spike_at) < interval else 0.0)

        places = []
        for buffer in (fast, slow):
            window = buffer.window_values(60.0, now=200.0)
            peak = max(range(len(window)), key=lambda i: _or_low(window[i]))
            places.append(peak / (len(window) - 1))
        # 200 - 60 = 140, so the spike at 150 belongs one sixth in.
        assert places[0] == pytest.approx(1 / 6, abs=0.03)
        assert places[1] == pytest.approx(places[0], abs=0.03)

    def test_a_stream_that_stops_scrolls_out_of_the_window(self):
        # Nothing is appended while nothing arrives, so without the clock the
        # dead trace would sit frozen against the right edge looking current.
        buffer = SeriesBuffer(12000)
        self._fill(buffer, 2000, 0.05)  # last sample at t = 99.95
        window = buffer.window_values(60.0, now=130.0)
        assert len(window) == 1200
        assert not math.isnan(window[0]), "the older half is still real data"
        assert math.isnan(window[-1]), "the silence since must show as silence"
        # Half the window is silence, give or take a slot of rounding.
        assert sum(math.isnan(value) for value in window) == pytest.approx(600, abs=2)

    def test_a_stream_dead_longer_than_the_window_goes_blank(self):
        buffer = SeriesBuffer(12000)
        self._fill(buffer, 2000, 0.05)
        window = buffer.window_values(60.0, now=4000.0)
        assert all(math.isnan(value) for value in window)

    def test_a_faster_site_is_not_padded_with_a_gap_it_never_had(self):
        """Headroom, not exact sizing. The slot count is measured, not nominal.

        The buffer is provisioned from a nominal 20 Hz, but the rate is a
        per-site value this package does not configure. A site running faster
        fits less time in the same slots, and asking for the longest window
        then wants more slots than exist — which pads as nan and draws an
        outage the analyzer never had, on the one display whose job is showing
        the real ones.
        """
        rng = random.Random(5)
        state = LiveState()
        buffer = SeriesBuffer(state.gas_history, detect_gaps=True)
        interval = 1 / 32  # a 32 Hz analyzer against a 20 Hz provisioning
        elapsed = 0.0
        for index in range(int(MAX_WINDOW_SECONDS * 1.5 / interval)):
            elapsed = index * interval + rng.uniform(-0.2, 0.2) * interval
            buffer.append(elapsed, 1.0)
        window = buffer.window_values(MAX_WINDOW_SECONDS, now=elapsed)
        assert not math.isnan(window[0]), "invented a gap at the start"
        assert not any(math.isnan(value) for value in window), "invented a gap"

    def test_it_is_the_tail_that_is_kept(self):
        buffer = SeriesBuffer(4800)
        self._fill(buffer, 2400, 0.05)
        assert buffer.window_values(60.0)[-1] == 2399.0

    def test_a_young_buffer_is_padded_on_the_left(self):
        # Not stretched across a span it never observed: the samples it does
        # have stay at the right edge, where the moments they describe are.
        buffer = SeriesBuffer(4800)
        self._fill(buffer, 200, 0.05)
        window = buffer.window_values(60.0)
        assert len(window) == 1200
        assert math.isnan(window[0])
        assert window[-1] == 199.0
        assert sum(math.isnan(value) for value in window) == 1000

    def test_without_a_cadence_it_returns_what_there_is(self):
        buffer = SeriesBuffer(100)
        buffer.append(0.0, 1.0)
        assert buffer.window_values(60.0) == [1.0]

    def test_buffers_are_sized_past_the_longest_window(self):
        # Strictly past it: sized to exactly the window, a cadence estimate
        # below nominal pads the difference with nan and draws a phantom gap.
        state = LiveState()
        assert state.gas_history > MAX_WINDOW_SECONDS * 20
        assert state.wind_history > MAX_WINDOW_SECONDS
