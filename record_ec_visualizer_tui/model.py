"""In-memory state the TUI renders: rolling series plus per-stream health.

Everything above the wire format lives here, so the display never has to know
whether a value arrived from a simulator or from a real socket.
"""
from __future__ import annotations

import math
import time
from collections import deque
from collections.abc import Mapping
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
    stream itself is the most reliable statement of what it is. Normal arrivals
    feed an exponential moving average; a late one is measured against it and
    never pollutes it.
    """

    def __init__(
        self,
        maxlen: int,
        detect_gaps: bool = False,
        gap_factor: float = 3.0,
        smoothing: float = 0.2,
    ) -> None:
        """
        :param gap_factor: how many typical intervals late a sample must be
            before the silence counts as a gap rather than as jitter.
        :param smoothing: weight of each new interval in the cadence estimate.
        """
        self._points: deque[tuple[float, float]] = deque(maxlen=maxlen)
        self._detect_gaps = detect_gaps
        self._gap_factor = gap_factor
        self._smoothing = smoothing
        self._interval: float | None = None

    def append(self, elapsed: float, value: float | None) -> None:
        if self._points:
            previous = self._points[-1][0]
            delta = elapsed - previous
            if delta > 0:
                if self._interval is None:
                    self._interval = delta
                elif delta <= self._interval * self._gap_factor:
                    self._interval += self._smoothing * (delta - self._interval)
                elif self._detect_gaps:
                    self._fill_missed_slots(previous, delta)
        self._points.append((elapsed, math.nan if value is None else float(value)))

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

    @property
    def values(self) -> list[float]:
        return [value for _, value in self._points]

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

    :param wind_history: how many sonicshow messages to keep (1 per second).
    :param gas_history: how many gas analyzer records to keep (~20 per second).
    :param gas_var: the site variable name to plot, as produced by the gas
        analyzer's ``var_map`` — e.g. ``CO2`` for a mixing ratio in umol mol-1.
    """

    wind_history: int = 240
    gas_history: int = 1200
    gas_var: str = "CO2"
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

    def ingest_ga(self, record: Mapping[str, Any]) -> None:
        """Take one decoded raw gas analyzer record into the rolling state."""
        elapsed = self.elapsed
        self.gas_health.mark_message()
        self.last_gas_record = dict(record)

        mapped = self.gas_map.apply(record)
        value = mapped.get(self.gas_var)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            self.gas.append(elapsed, float(value))
        else:
            # A record without the plotted variable still counts as liveness,
            # but breaks the line rather than holding the previous value.
            self.gas.append(elapsed, None)

        auxiliary = record.get("Auxiliary")
        if isinstance(auxiliary, Mapping) and "BufferSize" in auxiliary:
            self.diagnostics["ga_send_buffer"] = auxiliary["BufferSize"]

    def reset(self) -> None:
        """Clear the series but keep counters, for the 'r' binding."""
        for buffer in self.wind.values():
            buffer.clear()
        for buffer in self.wind_stdev.values():
            buffer.clear()
        self.gas.clear()
        self._start = time.monotonic()
