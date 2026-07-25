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
    """A fixed-length rolling series of ``(elapsed_seconds, value)`` samples."""

    def __init__(self, maxlen: int) -> None:
        self._points: deque[tuple[float, float]] = deque(maxlen=maxlen)

    def append(self, elapsed: float, value: float | None) -> None:
        self._points.append((elapsed, math.nan if value is None else float(value)))

    def clear(self) -> None:
        self._points.clear()

    @property
    def values(self) -> list[float]:
        return [value for _, value in self._points]

    @property
    def times(self) -> list[float]:
        return [elapsed for elapsed, _ in self._points]

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
        self.wind = {key: SeriesBuffer(self.wind_history) for key in WIND_RAW_KEYS}
        self.wind_stdev = {key: SeriesBuffer(self.wind_history) for key in WIND_RAW_KEYS}
        self.gas = SeriesBuffer(self.gas_history)
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

    def ingest_sonicshow(self, record: Mapping[str, Any]) -> None:
        """Take one decoded sonicshow message into the rolling state."""
        elapsed = self.elapsed
        self.sonic_health.mark_message()
        self.last_sonic_record = dict(record)

        for key in WIND_RAW_KEYS:
            if key not in record:
                continue
            try:
                mean, stdev = parse_mean_stdev(record[key])
            except DecodeError as exc:
                self.sonic_health.mark_error(str(exc))
                continue
            self.wind[key].append(elapsed, mean)
            self.wind_stdev[key].append(elapsed, stdev)

        diagnostics: dict[str, Any] = {}
        for key, value in record.items():
            if key in WIND_RAW_KEYS:
                continue
            if key.endswith("_buffer") or key == "sonic_buffer":
                try:
                    used, size = parse_buffer_fill(value)
                except DecodeError:
                    diagnostics[key] = value
                else:
                    diagnostics[key] = (used, size)
            else:
                diagnostics[key] = value
        self.diagnostics.update(diagnostics)

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
