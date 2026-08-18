<picture>
  <source media="(prefers-color-scheme: dark)" srcset="images/logo_ecvis_lockup_dark.svg">
  <img alt="ecvis" src="images/logo_ecvis_lockup.svg" width="420">
</picture>

# record-ec-visualizer-tui

A terminal dashboard that shows the data rECorD is measuring, as it measures it.
**ecvis** for short. The mark reads the same way the display does: the three wind
components as streamlines, the gas as discrete records arriving underneath.

rECorD (*Robust Eddy Covariance Data Acquisition*) reads a sonic anemometer over
a serial port, merges in gas analyzer records that arrive over UDP multicast,
and writes the combined records to TOA5 or ICOS files. While it runs it also
broadcasts a summary of what it is reading. Normally that summary is text
scrolling past in a terminal. This program turns it into a live display.

## Status

Early development. The display works against a simulated rECorD installation
and shows the three wind components and the CO2 mixing ratio. The code that
reads live multicast streams is written and tested, but has not yet been
pointed at a real site.

The demo needs nothing else installed or configured:

```bash
uv run record-ec-visualizer-tui --demo
```

Without `--demo` the program expects a real site and stops with an error if you
give it no addresses. That way the bare command on the logging host cannot show
invented numbers that look like measurements.

The same demo as a plain script, if you would rather start it from an editor:

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

Keys: `q` quits, `space` pauses, `r` clears the plots.

There are no borders and no separate panels for the numbers. Each stream gets
one header line, which shows the current values, names the components in their
plot colour, and separates the two plots. Everything else is plot. When the
window gets narrow the header drops its units first and its status text second,
instead of wrapping onto a second line and costing a row of plot.

`sw` is the standard deviation of the vertical wind. `TKE` is the turbulent
kinetic energy, `0.5·(σu²+σv²+σw²)`. Both come for free, because every
`sonicshow` message already reports each wind component as `mean(stdev)`. Read
them as a rough sign of how well the air is mixing, not as measurements: each
standard deviation covers one second, so it misses the slower eddies that a 30
minute flux average includes, and both values come out too low. The demo has
`sigma_w` set to 0.28 and the panel shows about half of that. A wider terminal
also shows the standard deviation of each component.

To read the data instead of watching it, this prints the raw bytes of both
streams next to the values they decode to:

```bash
uv run python examples/demo_wire_format.py
```

### Pointing it at real data

Live and simulated data take the same path through the program. Only the source
of the lines differs, so connecting to a real site is a matter of getting three
arguments right.

```bash
uv run record-ec-visualizer-tui --record-config /path/to/record.toml --sonicshow-group <group> --sonicshow-port <port> --analyzer <name> --gas-var CO2
```

`--record-config` reads the site's `record.toml`. The analyzer addresses and the
`var_map` come from there, so the values on screen carry the site's own variable
names. The sonicshow address is not in that file. It is a default inside
rECorD's code, which is why you pass it on the command line.

`--gas-var` chooses the variable to plot and defaults to `CO2`. It has to match
the name the site's `var_map` produces, not the analyzer's own name for it. A
wrong name is easy to miss: records keep arriving, the panel keeps reporting the
stream as live, and the plot stays empty. A record without the plotted variable
leaves a gap in the line rather than repeating the last value.

`--analyzer` matters at sites that run more than one analyzer. Without it, every
analyzer stream is read and drawn as one line, using the first analyzer's
`var_map`. Name the analyzer you want.

Before starting the display, check that the streams arrive at all. See
[Check the connection first](#check-the-connection-first).

## What it reads

rECorD sends several streams. All are UDP multicast, one message per line,
separated by newlines.

| Source | Address | Rate | Format | Contents |
|---|---|---|---|---|
| `sonicshow` | rECorD default, host-local group | 1 Hz | Python `dict` repr | Wind components (mean/stdev), sonic temperature, inclinometer, sonic error code, buffer fill, per-analyzer frequency and buffer fill |
| `analyzershow` | rECorD default, same group, next port | ~1 Hz | Python `dict` repr | Per-gas-analyzer aggregates (avg/last/min/max) |
| Raw analyzer stream | per analyzer, from the site config | ~20 Hz | JSON | Full-rate gas analyzer records (CO2, H2O, cell temperature and pressure, …) |
| Data file | flat in `<root_dir>` | 20 Hz | TOA5 CSV | Everything, aligned and written to disk |

A few properties of these streams shape what the program can do:

- `sonicshow` and `analyzershow` send a Python dictionary printed with `repr()`,
  not JSON. It uses single quotes, so `json.loads` rejects it. Parse it with
  `ast.literal_eval`.
- There is no high-rate sonic stream. Wind data arrives at 1 Hz from
  `sonicshow`. The full 20 Hz exists only in the data file, which has no
  timestamp column, so record times have to be worked out from the file name and
  the fixed 20 Hz rate.
- By default the streams use TTL 0 and are bound to loopback, so they never
  leave the logging host. Reading them from another machine means either
  reconfiguring rECorD onto a LAN multicast group with a TTL above 0, or reading
  the data files from a share.

The actual groups and ports are left out of this repository on purpose. The
defaults are in rECorD's source, and the values a site really uses are in its
`record.toml`: which analyzers exist, their addresses, and the variable names.

## Requirements

- Python 3.11 or newer. 3.11 is as low as it can go, because the site config is
  read with `tomllib`. Debian 12 ships 3.11, and that is what the logging hosts
  run.
- [uv](https://docs.astral.sh/uv/) for development.

This project does not import rECorD. rECorD and its two helper packages, `pygl`
and `udpmulticast`, live on an internal package index and cannot be installed
from PyPI, so the multicast client and the parsers are written again here. The
client had to be rewritten in any case: the one in `udpmulticast` uses
`SO_REUSEPORT` and runs on Linux only.

## Setup

```bash
uv sync
```

Tests and linting:

```bash
uv run pytest -q && uv run ruff check .
```

## Setting it up on the logging host

The streams stay on the machine rECorD runs on, so the visualizer has to be
installed there too. The path from a fresh host to a running display has four
steps — install, run the demo, check the connection with `--dump`, start the
display — and each step proves one thing, so a failure points at its own cause
rather than at everything at once.

Two checks before starting. The Python has to be 3.11 or newer:

```bash
python3 --version
```

Debian 12 ships 3.11, so on the usual logging host this passes. If it does not,
see the uv fallback at the end of this section. And do everything below as the
same user that runs rECorD — the reasons are under
[Running it day to day](#running-it-day-to-day).

### Install

rECorD itself is installed with [pipx](https://pypa.github.io/pipx/), which
works here as well:

```bash
pipx install git+https://github.com/holukas/record-ec-visualizer-tui.git
```

If the host has no outbound network, build the wheel elsewhere and copy it over
together with its dependencies. The wheel alone is not enough: installing it
would make pip fetch textual and rich from PyPI. Everything involved is pure
Python, so wheels downloaded on any machine work on the logger:

```bash
uv build
```

```bash
pip download dist/record_ec_visualizer_tui-0.1.0-py3-none-any.whl -d wheelhouse
```

```bash
scp -r wheelhouse user@logger:/tmp/wheelhouse
```

```bash
pipx install --pip-args "--no-index --find-links /tmp/wheelhouse" /tmp/wheelhouse/record_ec_visualizer_tui-0.1.0-py3-none-any.whl
```

If the host's Python is older than 3.11, install with uv instead. uv fetches
its own interpreter and leaves the system Python alone — though fetching it
does need network access:

```bash
uv tool install --python 3.12 /tmp/record_ec_visualizer_tui-0.1.0-py3-none-any.whl
```

### Run the demo once

The demo needs no addresses and no config, so it separates "the program runs
here" from "the streams reach it":

```bash
record-ec-visualizer-tui --demo
```

If two plots draw and move, the install, the terminal, and the locale are all
fine. If the plots come out as rows of boxes instead of braille, set a UTF-8
locale (`LANG=C.UTF-8` or similar) — better to find that out now than while
also wondering whether the streams arrive.

### Check the connection first

`--dump` prints the decoded records and starts no display, which tells you
whether the streams reach you at all, separately from whether the display is
right:

```bash
record-ec-visualizer-tui --record-config /path/to/record.toml --sonicshow-group <group> --sonicshow-port <port> --dump
```

The analyzer addresses come from `record.toml`. The sonicshow group and port are
defaults in rECorD's code (`sonicshow_ip` and `sonicshow_port` in
`BaseReader.__init__`) rather than entries in the config file, which is why they
are given separately. The quickest way to read them off a logging host is the
`sonicshow` program installed next to rECorD — its `-g` and `-p` defaults are
those same values:

```bash
sonicshow --help
```

The dump is also how you find the right value for `--gas-var`. Analyzer records are
printed twice: as they arrive, with the instrument's own names, and again after
the site's `var_map`, with the site's names. `--gas-var` has to come from the
second line — the raw names can never match. If the `after var_map` line does
not appear at all, the `var_map` in the config does not fit what the analyzer
sends, and the display would stay empty for the same reason. Once records from
both streams appear, drop `--dump` and start the display.

### Running it day to day

```bash
tmux new -s ecvis 'nice -n 10 record-ec-visualizer-tui --record-config /path/to/record.toml --sonicshow-group <group> --sonicshow-port <port> --gas-var <var>'
```

`--gas-var` is the name the `--dump` step confirmed. Leaving it off means the
default `CO2`, which is only right if the site's `var_map` produces exactly that
name.

Run it as the same user that runs rECorD — that user can already read
`record.toml`, and the session ends up owned by the account operating the
logger. The visualizer shares the analyzer ports with rECorD's own subscriber;
both programs set `SO_REUSEADDR` and `SO_REUSEPORT` on the socket, which is
what Linux requires for a shared UDP bind, so the sharing works even from
another account. If startup fails with `OSError: [Errno 98] Address already in
use`, whatever already holds the port is not one of rECorD's sockets — those
allow sharing.

Run it inside tmux or screen. Otherwise a dropped SSH connection takes the
display down with it.

Use `nice`. rECorD's 20 Hz loop warns whenever a cycle takes longer than 50 ms,
and the visualizer sits on the same machine. Redrawing costs roughly 20 ms per
second, so there is room to spare, but acquisition has priority.

### If nothing arrives

Multicast has to be enabled on the loopback interface. It probably already is,
since rECorD receives its own analyzer data that way, but check it first:

```bash
ip route show | grep 224
```

There should be a `224.0.0.0/4 dev lo` route. The `udpmulticast` README explains
how to add it, along with `ip link set multicast on lo`.

If the route is there and nothing arrives anyway, name the interface. The
default for `--interface` is `0.0.0.0`, which leaves the choice to the kernel.
On a host that has a network card as well as loopback the kernel can pick the
card, and these streams exist only on loopback:

```bash
record-ec-visualizer-tui --record-config /path/to/record.toml --sonicshow-group <group> --sonicshow-port <port> --interface 127.0.0.1 --dump
```

The setting applies to every stream, sonicshow and analyzers alike.

If only one of the two streams stays silent, the interface is not the cause.
Check the address of that stream: the sonicshow address comes from the command
line, the analyzer addresses from `record.toml`.

## Program layout

| Module | Responsibility |
|---|---|
| `codec.py` | Decodes the two formats rECorD sends, and applies its `var_map` |
| `simulator.py` | Produces rECorD-format data for the demo |
| `sources.py` | Delivers `(stream, line)` pairs, from the simulator or from multicast |
| `model.py` | Keeps the recent values of each series, and when each stream was last heard from |
| `tui/plot.py` | Draws the braille line plots |
| `tui/app.py` | The Textual application |

`sources.py` is where live and simulated data become the same thing. Everything
above it sees `(stream_name, payload_bytes)` and cannot tell which is which. The
simulator produces real rECorD bytes rather than ready-made objects, so
simulated data is decoded by exactly the code that will decode live data.

## Documentation

[CLAUDE.md](CLAUDE.md) describes rECorD in detail: the acquisition loop, the
multicast transport and where it is not portable, how records are aligned and
buffered, the status bit fields, the sonic `StaA`/`StaD` encoding, the layout of
the TOA5 files, and the configuration format.

## License

GPL-3.0
