# record-ec-visualizer-tui

Real-time terminal visualizer for incoming data from the rECorD eddy covariance
logging script.

rECorD (*Robust Eddy Covariance Data Acquisition*) reads a sonic anemometer over
a serial port, merges in gas analyzer records arriving over UDP multicast, and
writes aligned TOA5/ICOS raw data files. While it runs, it broadcasts status and
summary information that is otherwise only visible as scrolling text. This
project turns those streams into a live terminal dashboard.

## Status

Early development. A working TUI runs against a **simulated** rECorD
installation, showing the three wind components and the CO2 mixing ratio live.
The live multicast path is implemented and tested, but has not yet been run
against a real site.

```bash
uv run record-ec-visualizer-tui
```

That starts the demo — no rECorD, no configuration, no network needed. The same
thing as a plain script, if you would rather run it from an editor:

```bash
uv run python examples/demo_simulated.py
```

```
wind  U   2.15 V   0.08 W   0.21  m s-1   sd 0.40 0.32 0.24 ──── 1 Hz sonicshow  ·  last 180 s
    3.82 │⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢀⡠⠊⠢⡀⠀⠀⠀⠀⠀⠀⠀
         │⣀⠀⠀⠀⠀⢀⣀⣀⣀⡀⠀⠀⣀⡠⠤⠤⠤⠤⠤⣀⣀⡠⠔⠒⠉⠑⠒⠢⠤⣀⠀⠀⢀⣀⠀⠀⠀⡠⠔⠒⠊⠉⠒⠒⠤⢄⣀⣀⡠⠤⠔⠁⠀⠈⠢
   -0.60 │⠀⠉⠉⠒⠒⠒⠊⠉⠁⠀⠈⠉⠑⠒⠉⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠉⠒⠊⠉⠁⠉⠒⠢⠔⠊⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠉⠉⠉⠒
gas  CO2  418.34  umol mol-1 ────────────────────────────────── analyzer stream  ·  last 60 s
   427.7 │⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢀⢀⡆⢸⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⣀⠀⠀⠀⠀⠀⣀⢰⡀⠀⠀⠀⠀
         │⠾⣸⢸⡾⠉⡇⠀⢀⣰⠀⠀⣠⠀⣠⢰⡀⡇⠁⢸⡇⢸⡄⢀⡀⠀⢰⢿⠀⡼⠙⢣⠀⢀⡜⢸⠀⢰⡎⠀⢇⡀⠀⣦⠀⢰⢀⢦⣰⢹⠀⡄⠀⣆⣾⠈
   414.2 │⠀⠀⠀⠀⠀⠸⡿⠋⠈⢿⣦⣴⣼⠋⠃⠀⠘⠀⠀⠀⠀⠀⠀⠀⠀⠉⠁⠸⠎⠃⠀⡿⠀⠀⠀⠀⠀⠀⠀⠘⠇⠀⠀⠀⠀⠀⠀⠀⠃⠉⠀⠀⠀⢻⠸
sonicshow  0.4s ago  analyzer  0.0s ago  li7500rs_buffer 198/200  li7500rs_freq 20.0 Hz
```

Key bindings: `q` quit, `space` pause, `r` reset the series.

The layout has no borders or separate readout panels: each stream's header line
carries its current values, doubles as the legend (component names are drawn in
their series colour) and separates the two plots, so nearly all the terminal
height goes to data. The header sheds its units, then its metadata, as the
window narrows, rather than wrapping and costing a plot row.

To see the data itself rather than watch it — the raw bytes of both streams next
to what they decode to, which is what you would compare against a real site:

```bash
uv run python examples/demo_wire_format.py
```

### Pointing it at real data

Simulated and live data go through the *same* decode and display path — only
the line source differs — so connecting to a site is a matter of arguments, not
code:

```bash
uv run record-ec-visualizer-tui --source multicast --record-config /var/local/record.toml --sonicshow-group <group> --sonicshow-port <port>
```

`--record-config` reads the site's rECorD TOML for the analyzer addresses and
its `var_map`, so plotted values carry the site's own variable names. The
sonicshow address is a rECorD code default rather than a config entry, so it is
passed separately. To check a connection before opening the TUI:

```bash
uv run record-ec-visualizer-tui --source multicast --record-config /var/local/record.toml --dump
```

## What it reads

rECorD exposes several streams; all are UDP multicast, newline-delimited, one
message per line.

| Source | Address | Rate | Format | Contents |
|---|---|---|---|---|
| `sonicshow` | rECorD default, host-local group | 1 Hz | Python `dict` repr | Wind components (mean/stdev), sonic temperature, inclinometer, sonic error code, buffer fill, per-analyzer frequency and buffer fill |
| `analyzershow` | rECorD default, same group, next port | ~1 Hz | Python `dict` repr | Per-gas-analyzer aggregates (avg/last/min/max) |
| Raw analyzer stream | per analyzer, from the site config | ~20 Hz | JSON | Full-rate gas analyzer records (CO2, H2O, cell temperature and pressure, …) |
| Data file | flat in `<root_dir>` | 20 Hz | TOA5 CSV | Everything, aligned and written to disk |

Three caveats that shape the design:

- The `sonicshow` and `analyzershow` payloads are **Python dict reprs, not
  JSON** — they must be parsed with `ast.literal_eval`.
- rECorD publishes **no high-rate sonic stream**. Wind data is available at 1 Hz
  from `sonicshow`, or at the full 20 Hz only by tailing the current data file —
  which carries no timestamp column, so record times have to be reconstructed
  from the filename and the fixed 20 Hz rate.
- With rECorD's default settings the multicast streams use **TTL 0 and are bound
  to loopback**, so they never leave the logging host. Reaching them from
  another machine requires reconfiguring rECorD onto a LAN-scoped multicast
  group with a non-zero TTL, or reading data files from a share.

The concrete multicast groups and ports are deliberately not listed here. The
defaults are in rECorD's own source, and the site's actual values — which
analyzers exist, their multicast addresses, and the variable names — live in
rECorD's global `record.toml`.

## Requirements

- Python 3.12
- [uv](https://docs.astral.sh/uv/)

This project does not depend on rECorD itself: rECorD and its `pygl` and
`udpmulticast` dependencies are hosted on an internal package index and are not
installable from PyPI. The multicast client and parsers are reimplemented here —
also because `udpmulticast`'s client socket setup is Linux-only
(`SO_REUSEPORT`).

## Setup

```bash
uv sync
```

Tests and linting:

```bash
uv run pytest -q && uv run ruff check .
```

## Layout

| Module | Responsibility |
|---|---|
| `codec.py` | Decodes rECorD's two wire formats and its `var_map` translation |
| `simulator.py` | Generates rECorD-shaped stream lines for the demo |
| `sources.py` | Supplies `(stream, line)` pairs — simulated or live multicast |
| `model.py` | Rolling series and per-stream liveness |
| `tui/plot.py` | Braille line plots rendered into a `rich.text.Text` |
| `tui/app.py` | The Textual application |

The seam is `sources.py`: everything above it sees the same
`(stream_name, payload_bytes)` regardless of origin, and the simulator emits
real rECorD-format bytes rather than convenient objects, so simulated data is
decoded by exactly the code that will decode live data.

## Documentation

[CLAUDE.md](CLAUDE.md) documents how rECorD works in detail — the acquisition
loop, the multicast transport and its portability traps, record alignment and
buffering, status bitfields, the sonic `StaA`/`StaD` encoding, the TOA5 file
layout, and the configuration format.

## License

GPL-3.0
