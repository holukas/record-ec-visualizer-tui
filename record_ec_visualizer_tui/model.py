"""In-memory state the TUI renders: rolling series plus per-stream health.

Everything above the wire format lives here, so the display never has to know
whether a value arrived from a simulator or from a real socket.
"""
from __future__ import annotations

import math
import time
from collections import deque
from collections.abc import Mapping
from itertools import islice
from dataclasses import dataclass, field
from typing import Any

from record_ec_visualizer_tui.codec import (
    DecodeError,
    VariableMap,
    parse_buffer_fill,
    parse_mean_stdev,
)

# rECorD hardcodes the sonic sampling rate; it is not read from the site TOML.
SONIC_FREQ_HZ = 20.0

#: The longest window the display can be asked to show. Buffers are sized from
#: it, because a window can only be drawn out of samples that were kept: asking
#: for four minutes of a stream that holds one is answered with three minutes
#: of nan. It bounds render cost too — the whole window goes through the
#: decimator on every frame — which is why the ladder stops here rather than
#: going on doubling.
MAX_WINDOW_SECONDS = 240.0

#: How much more than the longest window each buffer holds. Sizing a buffer to
#: exactly the window is the one thing that must not be done: the slot count is
#: derived from the *measured* cadence, so an estimate a few percent below
#: nominal asks for more slots than a nominal buffer holds, and the shortfall
#: is padded with nan. That draws a gap the stream never had, on a display
#: whose whole purpose is showing the real ones — and it drifts frame to frame
#: as the estimate wanders. The same headroom covers a site whose analyzer runs
#: faster than the rate the buffer was provisioned for. It costs memory only:
#: what reaches the renderer is the window, not the buffer.
WINDOW_HEADROOM = 2.5

#: Arrivals a run must reach before it may replace the published cadence. A
#: short run right after a gap carries almost as much jitter as a single delta,
#: which is the thing the run average exists to get away from.
MIN_RUN = 8

# The raw keys a Gill sonic reports for the three wind components, in u/v/w
# order. sonicshow sends raw keys, not site variable names.
WIND_RAW_KEYS = ("Wc1", "Wc2", "Wc3")


class SeriesBuffer:
    """A fixed-length rolling series of ``(elapsed_seconds, value)`` samples.

    With ``detect_gaps``, a sample that arrives far later than the established
    cadence first fills the slots it missed with ``nan``. Without that, an
    outage would leave no trace at all — nothing is appended while nothing is
    arriving, so the trace closes over the hole and the plot silently compresses
    time. For eddy covariance data a gap is exactly the thing worth seeing, so
    the missing slots are made explicit.

    The cadence is learned rather than configured: an analyzer's rate is a
    per-site setting this package deliberately does not hardcode, and the
    stream itself is the most reliable statement of what it is. It is averaged
    over a run of consecutive ordinary arrivals; an arrival that is far off the
    estimate in either direction ends the run instead of entering it. Both
    directions matter, because arrival times stop describing the stream as soon
    as this program is the slow one: a late arrival may only mean a frame took
    too long, and the records queued behind it then arrive in a burst.
    """

    def __init__(
        self,
        maxlen: int,
        detect_gaps: bool = False,
        gap_factor: float = 3.0,
        run_length: int = 200,
        warmup: float = 2.0,
    ) -> None:
        """
        :param gap_factor: how many typical intervals late a sample must be
            before the silence counts as a gap rather than as jitter. The same
            factor bounds the estimate from below: an arrival that early is a
            burst out of a backlog rather than a faster stream.
        :param run_length: arrivals the estimate averages over. See
            :meth:`_learn` for why this is an average over a run and not a
            moving average over every delta.
        :param warmup: seconds to estimate from the overall rate before
            switching to the run average.
        """
        self._points: deque[tuple[float, float]] = deque(maxlen=maxlen)
        self._detect_gaps = detect_gaps
        self._gap_factor = gap_factor
        self._warmup = max(0.0, warmup)
        self._interval: float | None = None
        self._first: float | None = None
        self._arrivals = 0
        #: Arrival times of the current unbroken run of ordinary arrivals.
        self._run: deque[float] = deque(maxlen=max(MIN_RUN, run_length))

    def append(self, elapsed: float, value: float | None) -> None:
        if self._points:
            previous = self._points[-1][0]
            delta = elapsed - previous
            if delta > 0:
                self._learn(previous, delta, elapsed)
        else:
            self._first = elapsed
        self._arrivals += 1
        self._points.append((elapsed, math.nan if value is None else float(value)))

    def _learn(self, previous: float, delta: float, elapsed: float) -> None:
        """Update the cadence estimate, or treat this arrival as a gap.

        Arrival times are not the stream's cadence whenever this program is the
        slow one. A frame that takes longer than one sampling interval blocks
        the event loop, and the records queued behind it are then delivered
        back to back: deltas far below the true interval, from a stream that
        never changed rate.

        **The estimate has to be steady, not merely unbiased**, because the
        window converts it into a slot count and the renderer spreads that many
        slots across the full width. A per-delta moving average is not: it
        inherits the arrival jitter, and jitter is a far larger share of 50 ms
        than of 1 s, so the analyzer trace slid sideways by over a tenth of the
        plot from one frame to the next while sonicshow sat still. What is
        averaged here is therefore a *run* of consecutive ordinary arrivals,
        which telescopes to ``(last - first) / (n - 1)`` and so carries the
        jitter of two arrivals spread over n of them rather than the jitter of
        the latest one. A burst or a gap ends the run instead of entering it,
        and the published estimate simply stands until a fresh run is long
        enough to replace it — under delivery too broken to measure, the last
        trustworthy answer beats a fresh untrustworthy one.
        """
        covered = elapsed - (self._first or 0.0)
        if self._arrivals < 3 or covered < self._warmup:
            # Warm-up takes the rate over every arrival so far rather than the
            # last delta. Under bursty delivery no single delta is the cadence
            # — each one is either far too short (inside a burst) or far too
            # long (across the stall that caused it) — but the count over the
            # whole span is neither, and seeding from one bad delta would
            # poison every judgement made afterwards. It is a duration rather
            # than a count of arrivals because what makes the rate trustworthy
            # is covering enough wall time to average a stall cycle out, which
            # a fixed count does only at one particular stream rate.
            self._interval = covered / self._arrivals
            self._run.append(elapsed)
            return

        interval = self._interval
        if not interval:  # pragma: no cover - defensive
            return
        if delta * self._gap_factor < interval:
            # A burst out of a backlog, not a stream that sped up. Excluded for
            # the same reason a late arrival is: it says something about this
            # process, not about the instrument. Leaving it in was a one-way
            # ratchet — each burst dragged the estimate down, which made the
            # next ordinary arrival look like a gap, which pushed hundreds of
            # nan slots into the buffer and never fed the estimate back up.
            self._restart_run(elapsed)
            return
        if delta <= interval * self._gap_factor:
            self._run.append(elapsed)
            if len(self._run) >= MIN_RUN:
                self._interval = (self._run[-1] - self._run[0]) / (len(self._run) - 1)
            return
        if self._detect_gaps:
            self._fill_missed_slots(previous, delta)
        self._restart_run(elapsed)

    def _restart_run(self, elapsed: float) -> None:
        """Begin a fresh run at ``elapsed``, keeping the published estimate."""
        self._run.clear()
        self._run.append(elapsed)

    def _fill_missed_slots(self, previous: float, delta: float) -> None:
        """Append a nan for each sample the stream should have delivered."""
        interval = self._interval
        if not interval:  # pragma: no cover - guarded by the caller
            return
        # Rounded, not truncated: the ratio is a float estimate, and an exact
        # four-second gap at 20 Hz evaluates to 79.999... which would drop a
        # slot. Capped at the buffer length so a long outage cannot spin, and
        # anything beyond maxlen would be discarded on arrival anyway.
        missed = min(round(delta / interval) - 1, self._points.maxlen or 0)
        for step in range(1, missed + 1):
            self._points.append((previous + step * interval, math.nan))

    @property
    def interval(self) -> float | None:
        """The learned inter-arrival time, or ``None`` before two samples."""
        return self._interval

    def clear(self) -> None:
        self._points.clear()
        self._interval = None
        self._first = None
        self._arrivals = 0
        self._run.clear()

    @property
    def values(self) -> list[float]:
        return [value for _, value in self._points]

    def window_values(self, seconds: float, now: float | None = None) -> list[float]:
        """The most recent ``seconds`` of samples, as many slots as that spans.

        Both panels are asked for the same duration so that a peak in one sits
        above the moment that produced it in the other. That alignment rests on
        the renderer's x axis being sample-indexed: it stretches whatever list
        it is given across the full width, so two panels line up only when each
        list covers the window exactly. Hence a count derived from the measured
        cadence rather than a slice by timestamp, and a pad of ``nan`` at
        whichever end is short — a stream that cannot account for the whole
        window draws the part it can, in the place where that part belongs,
        instead of being stretched across a span it never observed.

        ``now`` is what makes the two windows describe the same wall clock
        rather than each stream's own last arrival. Pass it. Slots are only
        ever appended when something arrives, so a stream that has stopped
        would otherwise sit frozen against the right edge, drawing a complete
        and healthy-looking trace one whole window out of phase with its
        neighbour while the header claimed both showed the same seconds.

        Before a cadence is known there is nothing to convert with, so the
        whole buffer is returned; that lasts for the first few samples only.
        """
        interval = self._interval
        if not interval or not self._points:
            return self.values
        # Two slots is the least that can draw a line at all.
        wanted = max(2, round(seconds / interval))
        start = max(0, len(self._points) - wanted)
        values = [value for _, value in islice(self._points, start, None)]
        if now is not None:
            # The slots this stream owes since its last sample. Capped at the
            # window, because a stream that died an hour ago owes more than the
            # plot can show and the answer is the same either way: blank.
            missing = min(round((now - self._points[-1][0]) / interval), wanted)
            if missing > 0:
                values.extend([math.nan] * missing)
                values = values[-wanted:]
        if len(values) < wanted:
            values = [math.nan] * (wanted - len(values)) + values
        return values

    @property
    def latest(self) -> float:
        for _, value in reversed(self._points):
            if not math.isnan(value):
                return value
        return math.nan

    def span_seconds(self) -> float:
        if len(self._points) < 2:
            return 0.0
        return self._points[-1][0] - self._points[0][0]

    def __len__(self) -> int:
        return len(self._points)


@dataclass
class StreamHealth:
    """Liveness of one stream, so the display can show staleness not silence."""

    name: str
    messages: int = 0
    errors: int = 0
    last_message: float | None = None
    last_error: str | None = None
    #: A stream is stale once nothing has arrived for this long. rECorD's own
    #: DeviceShow client uses a 1.2 s socket timeout for the 1 Hz streams.
    stale_after: float = 1.2

    def mark_message(self, now: float | None = None) -> None:
        self.messages += 1
        self.last_message = time.monotonic() if now is None else now

    def mark_error(self, message: str) -> None:
        self.errors += 1
        self.last_error = message

    def age(self, now: float | None = None) -> float | None:
        if self.last_message is None:
            return None
        return (time.monotonic() if now is None else now) - self.last_message

    @property
    def is_stale(self) -> bool:
        age = self.age()
        return age is None or age > self.stale_after


@dataclass
class LiveState:
    """Everything the TUI draws, fed by :meth:`ingest_sonicshow` / :meth:`ingest_ga`.

    :param wind_history: how many sonicshow messages to keep, enough for
        :data:`MAX_WINDOW_SECONDS` at 1 Hz plus :data:`WINDOW_HEADROOM`.
    :param gas_history: how many gas analyzer records to keep, enough for
        :data:`MAX_WINDOW_SECONDS` at a nominal 20 Hz plus the same headroom.
        The rate itself stays measured rather than configured; the nominal one
        only sizes the buffer.
    :param gas_var: the site variable name to plot, as produced by the gas
        analyzer's ``var_map`` — e.g. ``CO2`` for a mixing ratio in umol mol-1.
    :param gas_units: what the site calls that variable's unit. Empty when the
        site config does not say, which the header then leaves out: a live
        display must not put a confident unit under a number it cannot vouch
        for, and the analyzers carry mixing ratios, densities, temperatures and
        pressures behind names only the site's own config resolves.
    """

    wind_history: int = int(MAX_WINDOW_SECONDS * WINDOW_HEADROOM)
    gas_history: int = int(MAX_WINDOW_SECONDS * 20 * WINDOW_HEADROOM)
    gas_var: str = "CO2"
    gas_units: str = ""
    sonic_map: VariableMap = field(default_factory=VariableMap)
    gas_map: VariableMap = field(default_factory=VariableMap)

    def __post_init__(self) -> None:
        self._start = time.monotonic()
        # All three wind buffers see the same arrival times, so they learn the
        # same cadence and pad identically — the index alignment they rely on
        # survives a gap.
        self.wind = {
            key: SeriesBuffer(self.wind_history, detect_gaps=True) for key in WIND_RAW_KEYS
        }
        self.wind_stdev = {
            key: SeriesBuffer(self.wind_history, detect_gaps=True) for key in WIND_RAW_KEYS
        }
        self.gas = SeriesBuffer(self.gas_history, detect_gaps=True)
        self.sonic_health = StreamHealth("sonicshow")
        # The raw analyzer stream runs at ~20 Hz, so it goes stale much sooner.
        self.gas_health = StreamHealth("gas analyzer", stale_after=0.5)
        self.diagnostics: dict[str, Any] = {}
        self.last_sonic_record: dict[str, Any] = {}
        self.last_gas_record: dict[str, Any] = {}
        #: The last analyzer record after the site's var_map. Kept so the panel
        #: can say which names a site actually offers when the one asked for
        #: never appears — the raw record's names never match ``gas_var``, so
        #: only the mapped form can answer that question.
        self.last_gas_mapped: dict[str, Any] = {}

    @property
    def elapsed(self) -> float:
        return time.monotonic() - self._start

    def label_for(self, raw_key: str) -> str:
        """Site variable name for a raw sonic key, falling back to the raw key."""
        return self.sonic_map.file_var_for(raw_key) or raw_key

    @property
    def sigma_w(self) -> float:
        """Standard deviation of the vertical wind, m s-1.

        The most direct statement of how vigorously the air is mixing, and it
        arrives ready-made: sonicshow already reports each component as
        ``mean(stdev)``, so nothing is computed here beyond a lookup.
        """
        return self.wind_stdev[WIND_RAW_KEYS[2]].latest

    @property
    def tke(self) -> float:
        """Turbulent kinetic energy per unit mass, m2 s-2.

        ``0.5 * (su^2 + sv^2 + sw^2)`` over whatever interval the deviations
        cover, which for sonicshow is one second of 20 samples.

        **That interval is the caveat.** A one-second window sees only the
        fastest eddies; the low-frequency contribution that a 30-minute flux
        averaging period would include is missing, so this reads low against a
        properly computed TKE. It tracks the right quantity and moves the right
        way, which is what a live display is for — it is not a flux-grade
        number, and nothing downstream should treat it as one.

        ``nan`` until all three components have been seen, rather than a total
        quietly computed from two of them. After that it follows the same
        last-known-value rule as the header's readouts: a component that stops
        arriving keeps contributing its last deviation instead of erasing the
        total.
        """
        total = 0.0
        for key in WIND_RAW_KEYS:
            deviation = self.wind_stdev[key].latest
            if math.isnan(deviation):
                return math.nan
            total += deviation * deviation
        return 0.5 * total

    def ingest_sonicshow(self, record: Mapping[str, Any]) -> None:
        """Take one decoded sonicshow message into the rolling state."""
        elapsed = self.elapsed
        self.sonic_health.mark_message()
        self.last_sonic_record = dict(record)

        # Every component gets a sample every message, even a missing one. The
        # plot maps a sample's *index* to an x position, so letting one series
        # skip an entry would shift it against the others from then on.
        for key in WIND_RAW_KEYS:
            mean: float | None = None
            stdev: float | None = None
            if key in record:
                try:
                    mean, stdev = parse_mean_stdev(record[key])
                except DecodeError as exc:
                    self.sonic_health.mark_error(str(exc))
            self.wind[key].append(elapsed, mean)
            self.wind_stdev[key].append(elapsed, stdev)

        for key, value in record.items():
            if key in WIND_RAW_KEYS:
                continue
            if key.endswith("_buffer"):
                try:
                    self.diagnostics[key] = parse_buffer_fill(value)
                except DecodeError:
                    self.diagnostics[key] = value
            else:
                self.diagnostics[key] = value

    def ingest_ga(self, record: Mapping[str, Any]) -> tuple[float, float | None]:
        """Take one decoded raw gas analyzer record into the rolling state.

        Returns the ``(elapsed, value)`` it appended, which is what the Eddy
        Derby is fed from. It has to come from here rather than be read back off
        the buffer afterwards: the game scores an integral, so it needs every
        sample and the moment each one arrived, and a caller sampling the
        latest value at the display rate would both miss most of a 20 Hz stream
        and silently skip the ``None`` that marks a record with no reading in
        it.
        """
        elapsed = self.elapsed
        self.gas_health.mark_message()
        self.last_gas_record = dict(record)

        mapped = self.gas_map.apply(record)
        self.last_gas_mapped = mapped
        value = mapped.get(self.gas_var)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            appended: float | None = float(value)
            self.gas.append(elapsed, appended)
        else:
            # A record without the plotted variable still counts as liveness,
            # but breaks the line rather than holding the previous value.
            appended = None
            self.gas.append(elapsed, None)

        auxiliary = record.get("Auxiliary")
        if isinstance(auxiliary, Mapping) and "BufferSize" in auxiliary:
            self.diagnostics["ga_send_buffer"] = auxiliary["BufferSize"]
        return elapsed, appended

    def reset(self) -> None:
        """Clear the series but keep counters, for the 'r' binding."""
        for buffer in self.wind.values():
            buffer.clear()
        for buffer in self.wind_stdev.values():
            buffer.clear()
        self.gas.clear()
        self._start = time.monotonic()
