"""A stand-in for a running rECorD installation.

The point of this module is that it produces **bytes in rECorD's own wire
format**, not convenient Python objects. Simulated data therefore travels the
same decode path as real data, and switching to a live site means swapping the
line source in :mod:`record_ec_visualizer_tui.sources` — nothing downstream
changes.

Two streams are emitted, matching what rECorD actually publishes:

``sonicshow``
    Once per second, a Python dict repr with the wind components as
    ``"mean(stdev)"`` over the preceding second, plus buffer fills and the
    estimated analyzer frequency. This is the only wind data rECorD exports.

``ga``
    At the analyzer rate, a JSON object per record, nested the way an
    analyzer's stream is nested, carrying the CO2 mixing ratio.

The physics is deliberately shallow but not white noise: wind components are
AR(1) processes so the traces look like turbulence, and the CO2 fluctuation is
anti-correlated with the vertical wind so that w'c' has the sign of daytime
uptake. It is a plausible-looking test signal, not a model of anything.

:meth:`RecordSimulator.blow` adds a breath to the CO2 stream on demand, which
is how the Eddy Derby is rehearsed and tested away from a site. It is the only
thing here that anything downstream may ask for, and what it produces is still
wire bytes: a simulated puff reaches the game through the decoder a live one
would.
"""
from __future__ import annotations

import asyncio
import json
import math
import random
import statistics
import time
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass, field

SONICSHOW_STREAM = "sonicshow"


@dataclass
class SimulationConfig:
    """Knobs for :class:`RecordSimulator`."""

    ga_name: str = "li7500rs"
    sonic_freq_hz: float = 20.0
    ga_freq_hz: float = 20.0
    show_interval_s: float = 1.0
    buffer_size: int = 200
    seed: int | None = 0

    #: Mean horizontal wind and turbulence intensity, m s-1.
    wind_speed: float = 2.5
    sigma_u: float = 0.55
    sigma_v: float = 0.45
    sigma_w: float = 0.28
    #: Lag-1 autocorrelation of the wind fluctuations at the sonic rate.
    wind_memory: float = 0.85

    #: Background CO2 mixing ratio, umol mol-1, and its variability.
    co2_background: float = 421.0
    sigma_co2: float = 1.1
    #: Strength of the w'/c' coupling. Positive gives a downward (uptake) flux.
    co2_flux_coupling: float = 2.2

    #: Top of the analyzer's measurement range, umol mol-1. An open-path head
    #: reads to roughly here and no further, and simulating that limit is the
    #: point rather than a detail: exhaled breath is over ten times it, so a
    #: real blow pins the reading, and the Eddy Derby is built around a score
    #: that still discriminates once it has. A simulator that let a puff run to
    #: 9000 would make the game look like it worked when it did not.
    co2_max_ppm: float = 3000.0

    #: Shape of a simulated breath: how high it would go unclipped, how long it
    #: takes to get there, and the time constant of the decay afterwards.
    breath_peak_ppm: float = 9000.0
    breath_rise_s: float = 0.4
    breath_fall_s: float = 1.1

    #: Drop the analyzer stream for this long, this often, to exercise the
    #: staleness display. Set either to 0 to disable.
    dropout_every_s: float = 45.0
    dropout_length_s: float = 4.0

    @property
    def ga_stream(self) -> str:
        return f"ga:{self.ga_name}"

    @property
    def var_map(self) -> dict[str, dict[str, str]]:
        """The ``var_map`` a site TOML would carry for this simulated analyzer."""
        return {
            "Data": {
                "CO2": "CO2",
                "CO2D": "CO2_CONC",
                "H2O": "H2O",
                "H2OD": "H2O_CONC",
                "Temp": "T_CELL",
                "Pres": "PRESS_CELL",
            }
        }

    @property
    def units(self) -> dict[str, str]:
        """What a site TOML's ``[datafile] units`` would say for these names.

        rECorD's notation, and ASCII: the display quotes them verbatim and the
        Linux console it runs on has no superscripts.
        """
        return {
            "CO2": "umol mol-1",
            "CO2_CONC": "umol m-3",
            "H2O": "mmol mol-1",
            "H2O_CONC": "mmol m-3",
            "T_CELL": "degC",
            "PRESS_CELL": "kPa",
        }

    @property
    def sonic_var_map(self) -> dict[str, str]:
        """The sonic ``var_map`` a site TOML would carry."""
        return {"Wc1": "U", "Wc2": "V", "Wc3": "W", "StaA": "SA_DIAG_TYPE", "StaD": "SA_DIAG_VALUE"}


@dataclass
class _WindState:
    u: float = 0.0
    v: float = 0.0
    w: float = 0.0
    co2: float = 0.0


@dataclass
class RecordSimulator:
    """Generate rECorD-shaped stream lines.

    :meth:`step` advances one sonic record and returns the lines that record
    produced — zero or more, since sonicshow only speaks once per second. It is
    synchronous and deterministic given a seed, which makes it directly
    testable; :meth:`run` wraps it with real-time pacing for the TUI.
    """

    config: SimulationConfig = field(default_factory=SimulationConfig)

    def __post_init__(self) -> None:
        self._rng = random.Random(self.config.seed)
        self._state = _WindState()
        self._tick = 0
        self._interval_u: list[float] = []
        self._interval_v: list[float] = []
        self._interval_w: list[float] = []
        self._interval_sos: list[float] = []
        self._records_since_show = 0
        self._sonic_buffer_fill = 0
        self._ndx = 0.0
        self._breath_start: float | None = None
        self._breath_strength = 1.0

    @property
    def dt(self) -> float:
        return 1.0 / self.config.sonic_freq_hz

    def blow(self, strength: float | None = None) -> None:
        """Breathe at the simulated inlet, starting from the next record.

        The one place anything upstream of this module can be asked to do
        something, and it exists so the Eddy Derby can be rehearsed and tested
        without an analyzer. It stays a demo-only path: what it produces is
        ordinary wire bytes, indistinguishable downstream from a real puff, so
        the game is exercised through exactly the code a site would run.

        :param strength: multiplier on :attr:`SimulationConfig.breath_peak_ppm`.
            Random around 1 by default, so two demo breaths differ the way two
            real ones do and the derby does not end in a dead heat.
        """
        self._breath_start = self._tick * self.dt
        self._breath_strength = self._rng.uniform(0.7, 1.3) if strength is None else strength

    def _breath_excess(self, elapsed: float) -> float:
        """CO2 the current simulated breath is adding, umol mol-1.

        A linear rise to the peak and an exponential decay after it -- the
        shape an open-path head sees when a plume passes it, near enough for a
        game. The tail is cut off once it is negligible so a breath cannot go
        on contributing arithmetic forever.
        """
        if self._breath_start is None:
            return 0.0
        cfg = self.config
        age = elapsed - self._breath_start
        if age < 0.0:  # pragma: no cover - blow() never schedules backwards
            return 0.0
        if age < cfg.breath_rise_s:
            # The cutoff below belongs to the decay only. Applied here it would
            # fire on the first record of every breath, where the shape is
            # legitimately zero, and cancel the breath before it began.
            shape = age / cfg.breath_rise_s
        else:
            shape = math.exp(-(age - cfg.breath_rise_s) / cfg.breath_fall_s)
            if shape < 0.001:
                self._breath_start = None
                return 0.0
        return cfg.breath_peak_ppm * self._breath_strength * shape

    def _advance_wind(self) -> tuple[float, float, float, float]:
        """One AR(1) step of the turbulence, returning u, v, w and CO2."""
        cfg = self.config
        memory = cfg.wind_memory
        kick = math.sqrt(max(0.0, 1.0 - memory * memory))
        state = self._state

        state.u = memory * state.u + kick * self._rng.gauss(0.0, 1.0)
        state.v = memory * state.v + kick * self._rng.gauss(0.0, 1.0)
        state.w = memory * state.w + kick * self._rng.gauss(0.0, 1.0)
        state.co2 = memory * state.co2 + kick * self._rng.gauss(0.0, 1.0)

        u = cfg.wind_speed + cfg.sigma_u * state.u
        v = cfg.sigma_v * state.v
        w = cfg.sigma_w * state.w

        # Anti-correlate the scalar with w so the covariance looks like uptake,
        # then add an independent part so it is not a pure mirror of w.
        elapsed = self._tick * self.dt
        drift = 1.5 * math.sin(2.0 * math.pi * elapsed / 600.0)
        co2 = (
            cfg.co2_background
            + drift
            - cfg.co2_flux_coupling * (w / max(cfg.sigma_w, 1e-9)) * cfg.sigma_co2
            + cfg.sigma_co2 * state.co2 * 0.6
            + self._breath_excess(elapsed)
        )
        # Clipped where the instrument clips, so a simulated breath saturates
        # the reading exactly as a real one does.
        return u, v, w, min(co2, cfg.co2_max_ppm)

    def _in_dropout(self) -> bool:
        cfg = self.config
        if cfg.dropout_every_s <= 0 or cfg.dropout_length_s <= 0:
            return False
        phase = (self._tick * self.dt) % cfg.dropout_every_s
        return phase < cfg.dropout_length_s and self._tick * self.dt > cfg.dropout_every_s

    def step(self) -> list[tuple[str, bytes]]:
        """Advance one sonic record; return ``(stream_name, line)`` pairs."""
        cfg = self.config
        u, v, w, co2 = self._advance_wind()
        # Speed of sound, reported by the sonic in place of a temperature.
        sos = 343.0 + 0.6 * self._rng.gauss(0.0, 1.0)

        self._tick += 1
        self._ndx += self.dt

        self._interval_u.append(u)
        self._interval_v.append(v)
        self._interval_w.append(w)
        self._interval_sos.append(sos)
        self._records_since_show += 1
        self._sonic_buffer_fill = min(cfg.buffer_size, self._sonic_buffer_fill + 1)

        lines: list[tuple[str, bytes]] = []

        if not self._in_dropout():
            lines.append((cfg.ga_stream, self._ga_line(co2)))

        records_per_show = max(1, round(cfg.show_interval_s * cfg.sonic_freq_hz))
        if self._records_since_show >= records_per_show:
            lines.append((SONICSHOW_STREAM, self._sonicshow_line()))
            self._reset_interval()

        return lines

    def _ga_line(self, co2: float) -> bytes:
        """One raw analyzer record: real JSON, nested like an analyzer stream."""
        temp = 24.5 + 0.05 * self._rng.gauss(0.0, 1.0)
        pressure = 96.2 + 0.02 * self._rng.gauss(0.0, 1.0)
        h2o = 12.4 + 0.15 * self._rng.gauss(0.0, 1.0)
        # Mixing ratio (umol mol-1) to molar density (umol m-3) via the ideal
        # gas law, so the two CO2 columns are at least mutually consistent.
        molar_density = pressure * 1000.0 / (8.314 * (temp + 273.15))
        record = {
            "Ndx": round(self._ndx, 4),
            "Data": {
                "CO2": round(co2, 4),
                "CO2D": round(co2 * molar_density * 1e-3, 4),
                "H2O": round(h2o, 4),
                "H2OD": round(h2o * molar_density, 3),
                "Temp": round(temp, 3),
                "Pres": round(pressure, 4),
                "Cooler": round(1.8 + 0.01 * self._rng.gauss(0.0, 1.0), 4),
            },
            "Auxiliary": {"BufferSize": 0},
        }
        return json.dumps(record).encode("utf-8")

    def _sonicshow_line(self) -> bytes:
        """One sonicshow message: a Python dict repr, exactly as rECorD sends it."""
        cfg = self.config
        show: dict[str, object] = {}
        for key, samples in (
            ("Wc1", self._interval_u),
            ("Wc2", self._interval_v),
            ("Wc3", self._interval_w),
            ("SOS", self._interval_sos),
        ):
            show[key] = _mean_stdev_string(samples)

        show["sonic_buffer"] = f"{self._sonic_buffer_fill}/{cfg.buffer_size}"
        if self._in_dropout():
            observed_freq = 0.0
            ga_fill = 0
        else:
            observed_freq = round(cfg.ga_freq_hz * 10) / 10
            ga_fill = cfg.buffer_size - self._rng.randint(0, 3)
        show[f"{cfg.ga_name}_freq"] = observed_freq
        show[f"{cfg.ga_name}_buffer"] = f"{ga_fill}/{cfg.buffer_size}"

        # f"{dict}\n".encode() — a Python repr, single quotes, not JSON.
        return f"{show}".encode("utf-8")

    def _reset_interval(self) -> None:
        self._interval_u.clear()
        self._interval_v.clear()
        self._interval_w.clear()
        self._interval_sos.clear()
        self._records_since_show = 0

    def iter_lines(self, ticks: int) -> Iterator[tuple[str, bytes]]:
        """Synchronously produce the lines of ``ticks`` sonic records."""
        for _ in range(ticks):
            yield from self.step()

    async def run(self, speedup: float = 1.0) -> AsyncIterator[tuple[str, bytes]]:
        """Yield lines paced in real time, as a live installation would."""
        if speedup <= 0:
            raise ValueError("speedup must be positive")
        interval = self.dt / speedup
        next_tick = time.monotonic()
        while True:
            for line in self.step():
                yield line
            next_tick += interval
            delay = next_tick - time.monotonic()
            if delay > 0:
                await asyncio.sleep(delay)
            else:
                # Fell behind: give the event loop a turn and resync.
                next_tick = time.monotonic()
                await asyncio.sleep(0)


def _mean_stdev_string(samples: list[float]) -> str:
    """Format like rECorD does: two decimals, and literal ``nan`` for n < 2."""
    if not samples:
        return "nan(nan)"
    mean = statistics.fmean(samples)
    try:
        stdev = statistics.stdev(samples)
    except statistics.StatisticsError:
        stdev = math.nan
    return f"{mean:.2f}({stdev:.2f})"
