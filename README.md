<picture>
  <source media="(prefers-color-scheme: dark)" srcset="images/logo_ecvis_lockup_dark.svg">
  <img alt="ecvis" src="images/logo_ecvis_lockup.svg" width="420">
</picture>

# record-ec-visualizer-tui

A terminal dashboard for rECorD (*Robust Eddy Covariance Data Acquisition*), the
eddy covariance raw data logger. Short name: **ecvis**.

rECorD reads a sonic anemometer over a serial port, merges in gas analyzer
records that arrive over UDP multicast, and writes the combined records to TOA5
or ICOS files. While it runs, it also broadcasts a summary of what it is
reading. This program subscribes to that summary and plots it.

## Status

Early development. The display runs against a simulated rECorD installation and
plots the three wind components and the CO2 mixing ratio. The code for the live
multicast streams is written and tested, but has not been tried at a real site
yet.

The demo needs no configuration and no rECorD installation:

```bash
uv run record-ec-visualizer-tui --demo
```

Without `--demo` the program expects a real site and exits with an error if you
give it no addresses. The refusal is deliberate: the bare command on a logging
host must never display simulated numbers.

The demo is also available as a plain script, for starting it from an editor:

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

The display has no borders and no separate panels for the numbers. Each stream
gets one header line, which shows the current values, names the components in
their plot colour and separates the two plots. The rest of the space is plot. In
a narrow window the header drops its units first and its status text second,
rather than wrapping onto a second line and costing a row of plot.

`sw` is the standard deviation of the vertical wind, `TKE` the turbulent
kinetic energy, `0.5·(σu²+σv²+σw²)`. Neither needs extra data, since every
`sonicshow` message already reports each wind component as `mean(stdev)`.
Treat them as a rough indicator of mixing, not as a measurement. Each standard
deviation covers a single second, so it misses the slower eddies that a 30
minute flux average includes, and both values come out too low. In the demo
`sigma_w` is set to 0.28 and the panel shows roughly half that. A wider
terminal also shows the standard deviation of each component.

To inspect the data rather than watch it, this example prints the raw bytes of
both streams next to the values they decode to:

```bash
uv run python examples/demo_wire_format.py
```

### Pointing it at real data

Live and simulated data take the same path through the program, and only the
source of the lines differs. A real site therefore needs three arguments:

```bash
uv run record-ec-visualizer-tui --record-config /path/to/record.toml --sonicshow-group <group> --sonicshow-port <port> --analyzer <name> --gas-var CO2
```

`--record-config` reads the site's `record.toml`, which supplies the analyzer
addresses and the `var_map`, so the values on screen use the site's own variable
names. The sonicshow address is not in that file; it is a default in rECorD's
code, and you pass it on the command line.

`--gas-var` selects the variable to plot and defaults to `CO2`. It must match
the name produced by the site's `var_map`, not the analyzer's own name for it. A
wrong name is easy to overlook, because records keep arriving and the panel
still reports the stream as live while the plot stays empty. Records without the
plotted variable leave a gap in the line instead of repeating the last value.

`--analyzer` is only relevant at sites that run more than one analyzer. Without
it, all analyzer streams are read and drawn as a single line using the first
analyzer's `var_map`.

Check that the streams arrive before starting the display, as described under
[Check the connection first](#check-the-connection-first).

## What it reads

rECorD sends several streams, all of them UDP multicast, one message per line,
separated by newlines.

| Source | Address | Rate | Format | Contents |
|---|---|---|---|---|
| `sonicshow` | rECorD default, host-local group | 1 Hz | Python `dict` repr | Wind components (mean/stdev), sonic temperature, inclinometer, sonic error code, buffer fill, per-analyzer frequency and buffer fill |
| `analyzershow` | rECorD default, same group, next port | ~1 Hz | Python `dict` repr | Per-gas-analyzer aggregates (avg/last/min/max) |
| Raw analyzer stream | per analyzer, from the site config | ~20 Hz | JSON | Full-rate gas analyzer records (CO2, H2O, cell temperature and pressure, …) |
| Data file | flat in `<root_dir>` | 20 Hz | TOA5 CSV | Everything, aligned and written to disk |

Some properties of these streams limit what the program can do:

- `sonicshow` and `analyzershow` send a Python dictionary printed with `repr()`,
  not JSON. It uses single quotes, so `json.loads` rejects it. Parse it with
  `ast.literal_eval`.
- There is no high-rate sonic stream. Wind data arrives at 1 Hz from
  `sonicshow`. The full 20 Hz exists only in the data file, which has no
  timestamp column, so record times must be reconstructed from the file name and
  the fixed 20 Hz rate.
- By default the streams use TTL 0 and are bound to loopback, so they never
  leave the logging host. Reading them from another machine means either
  reconfiguring rECorD onto a LAN multicast group with a TTL above 0, or reading
  the data files from a share.

The actual groups and ports are deliberately not in this repository. The
defaults are in rECorD's source, and the values a site really uses are in its
`record.toml`, together with the analyzers it runs, their addresses and their
variable names.

## Requirements

- Python 3.11 or newer. 3.11 is the floor because the site config is read with
  `tomllib`. Debian 12 ships 3.11, which is what the logging hosts run.
- [uv](https://docs.astral.sh/uv/) for development.

This project does not import rECorD. rECorD and its two helper packages, `pygl`
and `udpmulticast`, are published on an internal package index and cannot be
installed from PyPI, so the multicast client and the parsers are reimplemented
here. The client needed rewriting anyway: the one in `udpmulticast` uses
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
installed there as well. There are four steps: install, run the demo, check the
connection with `--dump`, then start the display. Keeping them separate means a
failure points at one cause rather than several.

Two things to check first. The Python version has to be 3.11 or newer:

```bash
python3 --version
```

Debian 12 ships 3.11, so on the usual logging host this passes; if it does not,
use the uv fallback at the end of this section. Second, run everything below as
the user that runs rECorD, for the reasons given under
[Running it day to day](#running-it-day-to-day).

### Install

rECorD itself is installed with [pipx](https://pypa.github.io/pipx/), and that
works here too:

```bash
pipx install git+https://github.com/holukas/record-ec-visualizer-tui.git
```

On a host without outbound network access, build the wheel elsewhere and copy it
over together with its dependencies. The wheel on its own is not enough, since
installing it makes pip fetch textual and rich from PyPI. All packages involved
are pure Python, so wheels downloaded on any machine work on the logger:

```bash
uv build
```

```bash
pip download dist/record_ec_visualizer_tui-0.2.1-py3-none-any.whl -d wheelhouse
```

```bash
scp -r wheelhouse user@logger:/tmp/wheelhouse
```

```bash
pipx install --pip-args "--no-index --find-links /tmp/wheelhouse" /tmp/wheelhouse/record_ec_visualizer_tui-0.2.1-py3-none-any.whl
```

If the host's Python is older than 3.11, install with uv instead. uv downloads
its own interpreter and leaves the system Python untouched, but the download
needs network access:

```bash
uv tool install --python 3.12 /tmp/record_ec_visualizer_tui-0.2.1-py3-none-any.whl
```

### Run the demo once

The demo needs no addresses and no config, so it tests the installation without
involving the streams:

```bash
record-ec-visualizer-tui --demo
```

If two plots draw and move, the installation, the terminal and the locale are
all fine. If the plots appear as rows of boxes instead of braille, set a UTF-8
locale (`LANG=C.UTF-8` or similar).

### Check the connection first

`--dump` prints the decoded records without starting the display, so you can
see whether the streams reach you at all:

```bash
record-ec-visualizer-tui --record-config /path/to/record.toml --sonicshow-group <group> --sonicshow-port <port> --dump
```

The analyzer addresses come from `record.toml`. The sonicshow group and port are
defaults in rECorD's code (`sonicshow_ip` and `sonicshow_port` in
`BaseReader.__init__`) and not entries in the config file, so you pass them
separately. The easiest way to read them off a logging host is the `sonicshow`
program installed alongside rECorD; its `-g` and `-p` defaults are the same
values:

```bash
sonicshow --help
```

The dump also gives you the correct value for `--gas-var`. Analyzer records are
printed twice: first as they arrive, with the instrument's own variable names,
then again after the site's `var_map`, with the site's names. `--gas-var` has to
come from the second line, since the raw names will never match. If the `after
var_map` line does not appear at all, the `var_map` in the config does not fit
what the analyzer sends, and the display would stay empty for the same reason.
Once records from both streams appear, drop `--dump` and start the display.

### Running it day to day

```bash
tmux new -s ecvis 'nice -n 10 record-ec-visualizer-tui --record-config /path/to/record.toml --sonicshow-group <group> --sonicshow-port <port> --gas-var <var>'
```

`--gas-var` takes the name confirmed in the `--dump` step. Omitting it selects
the default `CO2`, which is only correct if the site's `var_map` produces that
exact name.

Run the visualizer as the user that runs rECorD. That user can already read
`record.toml`, and the session then belongs to the account operating the logger.
Port access is not the reason. The visualizer shares the analyzer ports with
rECorD's own subscriber, and both programs set `SO_REUSEADDR` and `SO_REUSEPORT`
on the socket, which is what Linux requires for a shared UDP bind. Port sharing
therefore works from any account. A startup failure with `OSError: [Errno 98]
Address already in use` means the port is held by something other than rECorD.

Run it inside tmux or screen, otherwise a dropped SSH connection takes the
display down with it.

Use `nice`. rECorD's 20 Hz loop warns whenever a cycle takes longer than 50 ms,
and the visualizer runs on the same machine. Redrawing costs roughly 20 ms per
second, so there is room to spare, but acquisition has priority.

### If nothing arrives

Multicast has to be enabled on the loopback interface. It usually is, since
rECorD receives its own analyzer data that way, but check first:

```bash
ip route show | grep 224
```

There should be a `224.0.0.0/4 dev lo` route. The `udpmulticast` README explains
how to add it, together with `ip link set multicast on lo`.

If the route exists and nothing arrives, name the interface. `--interface`
defaults to `0.0.0.0`, which leaves the choice to the kernel. On a host with a
network card as well as loopback the kernel may pick the card, while these
streams exist only on loopback:

```bash
record-ec-visualizer-tui --record-config /path/to/record.toml --sonicshow-group <group> --sonicshow-port <port> --interface 127.0.0.1 --dump
```

The setting applies to every stream, sonicshow as well as analyzers.

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

`sources.py` is the boundary between live and simulated data. Everything above
it sees `(stream_name, payload_bytes)` and cannot distinguish the two. The
simulator produces real rECorD bytes rather than ready-made objects, so
simulated data is decoded by exactly the code that will decode live data.

## Documentation

[CLAUDE.md](CLAUDE.md) documents rECorD in detail: the acquisition loop, the
multicast transport and its portability problems, record alignment and
buffering, the status bit fields, the sonic `StaA`/`StaD` encoding, the layout
of the TOA5 files, and the configuration format.

## License

GPL-3.0
