# record-ec-visualizer-tui

A terminal dashboard that shows the data rECorD is measuring, as it measures it.

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

## Installing on the logging host

The streams stay on the machine rECorD runs on, so the visualizer has to be
installed there too. rECorD itself is installed with
[pipx](https://pypa.github.io/pipx/), which works here as well:

```bash
pipx install git+https://github.com/holukas/record-ec-visualizer-tui.git
```

If the host has no outbound network, build the wheel elsewhere and copy it over.
It is pure Python and about 40 kB:

```bash
uv build
```

```bash
scp dist/record_ec_visualizer_tui-*.whl user@logger:/tmp/
```

```bash
pipx install /tmp/record_ec_visualizer_tui-0.1.0-py3-none-any.whl
```

If the host's Python is older than 3.11, install it with uv instead. uv fetches
its own interpreter and leaves the system Python alone:

```bash
uv tool install --python 3.12 /tmp/record_ec_visualizer_tui-0.1.0-py3-none-any.whl
```

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
are given separately.

Each record is printed as a plain dictionary, so this is also how you find the
analyzer's real variable names. Pick the one you want and pass it as
`--gas-var`. Once records from both streams appear, drop `--dump` and start the
display.

### Running it day to day

```bash
tmux new -s ecvis 'nice -n 10 record-ec-visualizer-tui --record-config /path/to/record.toml --sonicshow-group <group> --sonicshow-port <port>'
```

Run it as the same user that runs rECorD. The socket sets `SO_REUSEPORT` so that
it can share the port with rECorD's own subscriber, and Linux allows that only
between processes belonging to the same user. From another account the program
fails at startup with `OSError: [Errno 98] Address already in use`, which looks
like a configuration mistake but is a permission problem.

Run it inside tmux or screen. Otherwise a dropped SSH connection takes the
display down with it.

Use `nice`. rECorD's 20 Hz loop warns whenever a cycle takes longer than 50 ms,
and the visualizer sits on the same machine. Redrawing costs roughly 20 ms per
second, so there is room to spare, but acquisition has priority.

Set a UTF-8 locale (`LANG=C.UTF-8` or similar), or the braille plots come out as
rows of boxes.

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
