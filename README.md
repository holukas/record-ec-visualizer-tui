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
uv run record-ec-visualizer-tui --demo
```

That starts the demo — no rECorD, no configuration, no network needed. Without
`--demo` the command expects a live site, so that on the logging host the bare
invocation never quietly shows invented data. The same thing as a plain script,
if you would rather run it from an editor:

```bash
uv run python examples/demo_simulated.py
```

```
wind  U   2.15 V   0.08 W   0.21  sw 0.24  TKE 0.31 ──────────── 1 Hz sonicshow  ·  last 180 s
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

`sw` and `TKE` are how vigorously the air is mixing: the standard deviation of
the vertical wind, and the turbulent kinetic energy `0.5·(σu²+σv²+σw²)`. Both
come free with every `sonicshow` message, which already reports each component
as `mean(stdev)`. Read them as a live indicator, not as a measurement: the
deviations cover one second, so they miss the low-frequency eddies a 30-minute
flux averaging period would include and consistently read low — against the
demo's own configured `sigma_w` of 0.28, the panel shows about half that. On a
wider terminal the per-component deviations appear behind them.

To see the data itself rather than watch it — the raw bytes of both streams next
to what they decode to, which is what you would compare against a real site:

```bash
uv run python examples/demo_wire_format.py
```

### Pointing it at real data

Simulated and live data go through the *same* decode and display path — only
the line source differs — so connecting to a site is a matter of arguments, not
code. Three of them have to be right:

```bash
uv run record-ec-visualizer-tui --record-config /path/to/record.toml --sonicshow-group <group> --sonicshow-port <port> --analyzer <name> --gas-var CO2
```

- **The addresses.** `--record-config` reads the site's rECorD TOML for the
  analyzer addresses and their `var_map`, so plotted values carry the site's own
  variable names. The sonicshow address is a rECorD *code* default rather than a
  config entry, which is why it is passed separately.
- **The variable to plot.** `--gas-var` defaults to `CO2` and has to match the
  name the site's `var_map` maps *to*, not the analyzer's raw key for it. A
  wrong name fails quietly in a way worth recognising: records keep arriving and
  the panel keeps reporting the stream as live, but the trace stays empty,
  because a record without the plotted variable breaks the line rather than
  holding the last value.
- **Which analyzer**, at a site that runs more than one. Without `--analyzer`
  every analyzer stream is read, and they are all drawn on one trace under the
  first analyzer's `var_map` — two instruments interleaved into a single line.
  Name the one you want.

Before opening the TUI, confirm the streams are arriving at all with `--dump`,
which prints decoded records and nothing else — see
[Check the connection](#check-the-connection-before-starting-the-tui) below.

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

- Python 3.11 or newer (3.11 is the floor because the site config is read with
  `tomllib`; Debian 12 ships 3.11, which is what the logging hosts run)
- [uv](https://docs.astral.sh/uv/) for development

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

## Deployment on the logging host

Because rECorD publishes with TTL 0 bound to loopback, the live streams are
only reachable from the machine rECorD runs on — so this has to be installed
there. rECorD itself is deployed with [pipx](https://pypa.github.io/pipx/), and
the same works here.

Install from the repository:

```bash
pipx install git+https://github.com/holukas/record-ec-visualizer-tui.git
```

If the host has no outbound network, build a wheel elsewhere and copy it over.
The wheel is pure Python and about 40 kB:

```bash
uv build
```

```bash
scp dist/record_ec_visualizer_tui-*.whl user@logger:/tmp/
```

```bash
pipx install /tmp/record_ec_visualizer_tui-0.1.0-py3-none-any.whl
```

If the host's Python is older than 3.11, install with uv instead — it fetches
its own interpreter and leaves the system Python alone:

```bash
uv tool install --python 3.12 /tmp/record_ec_visualizer_tui-0.1.0-py3-none-any.whl
```

### Check the connection before starting the TUI

`--dump` prints decoded records and nothing else, which separates "the streams
are not reaching me" from "the display is wrong":

```bash
record-ec-visualizer-tui --record-config /path/to/record.toml --sonicshow-group <group> --sonicshow-port <port> --dump
```

The analyzer addresses come from `record.toml`. The sonicshow group and port are
rECorD code defaults rather than config entries (`sonicshow_ip` / `sonicshow_port`
in `BaseReader.__init__`), which is why they are passed separately.

`--dump` also answers the question the TUI cannot: it prints each decoded record
as a dictionary, so you can read the analyzer's actual variable names off the
wire and pass the right one as `--gas-var`. Once records from both streams
appear, drop `--dump` and add `--gas-var` (and `--analyzer`, at a site with more
than one) to start the TUI.

### Running it day to day

```bash
tmux new -s ecvis 'nice -n 10 record-ec-visualizer-tui --record-config /path/to/record.toml --sonicshow-group <group> --sonicshow-port <port>'
```

- **The same user account rECorD runs under.** The socket sets `SO_REUSEPORT`
  so it can share the port with rECorD's own subscriber, and Linux only lets
  sockets share a port that way when they have the same effective UID — an
  anti-hijacking rule. From another account the bind fails at startup with
  `OSError: [Errno 98] Address already in use`, which reads like a
  configuration mistake rather than a permissions one.
- **tmux or screen**, because a dropped SSH connection would otherwise kill a
  full-screen app.
- **`nice`**, because the visualizer shares the machine with rECorD's 20 Hz
  acquisition loop, which warns as soon as a cycle exceeds 50 ms. Redraw costs
  roughly 20 ms per second of wall clock, so this is comfortable rather than
  tight — but the logger's job comes first.
- **A UTF-8 locale** (`LANG=C.UTF-8` or similar), or the braille plots render as
  boxes.

### If nothing arrives

Multicast has to be enabled on the loopback interface. This is almost certainly
already the case, since rECorD receives its own gas analyzer data that way, but
it is the first thing to check:

```bash
ip route show | grep 224
```

That should show a `224.0.0.0/4 dev lo` route. The `udpmulticast` README covers
adding it, along with `ip link set multicast on lo`.

If the route is there and the process still sits silent, name the interface
explicitly. `--interface` defaults to `0.0.0.0`, which leaves the choice of
interface to join on to the kernel; on a host with a real NIC as well as
loopback that choice can go the other way, and these streams are loopback-only:

```bash
record-ec-visualizer-tui --record-config /path/to/record.toml --sonicshow-group <group> --sonicshow-port <port> --interface 127.0.0.1 --dump
```

It applies to every stream subscribed to, sonicshow and the analyzers alike —
an interface that reached only some of them would half-cure the silence while
looking like it had been applied.

If only *one* of the two streams stays silent, the interface is not the problem:
that points at the address for that stream, since sonicshow's comes from the
command line and the analyzers' from `record.toml`.

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
