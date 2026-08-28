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
plots the three wind components and the CO2 mixing ratio. The live multicast
code is written and tested, but has not been tried at a real site yet.

The demo needs no configuration and no rECorD installation:

```bash
uv run record-ec-visualizer-tui --demo
```

Without `--demo` the program expects a real site and exits with an error if you
give it no addresses. That refusal is deliberate: the bare command on a logging
host must never display simulated numbers.

The demo is also available as a plain script, for starting it from an editor:

```bash
uv run python examples/demo_simulated.py
```

```
wind  U   2.15 V   0.08 W   0.21  sw 0.24  TKE 0.31 ───────────── 1 Hz sonicshow  ·  last 60 s
    3.82 │⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢀⡠⠊⠢⡀⠀⠀⠀⠀⠀⠀⠀
         │⣀⠀⠀⠀⠀⢀⣀⣀⣀⡀⠀⠀⣀⡠⠤⠤⠤⠤⠤⣀⣀⡠⠔⠒⠉⠑⠒⠢⠤⣀⠀⠀⢀⣀⠀⠀⠀⡠⠔⠒⠊⠉⠒⠒⠤⢄⣀⣀⡠⠤⠔⠁⠀⠈⠢
   -0.60 │⠀⠉⠉⠒⠒⠒⠊⠉⠁⠀⠈⠉⠑⠒⠉⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠉⠒⠊⠉⠁⠉⠒⠢⠔⠊⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠉⠉⠉⠒
gas  CO2  418.34  umol mol-1 ────────────────────────────────── analyzer stream  ·  last 60 s
   427.7 │⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢀⢀⡆⢸⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⣀⠀⠀⠀⠀⠀⣀⢰⡀⠀⠀⠀⠀
         │⠾⣸⢸⡾⠉⡇⠀⢀⣰⠀⠀⣠⠀⣠⢰⡀⡇⠁⢸⡇⢸⡄⢀⡀⠀⢰⢿⠀⡼⠙⢣⠀⢀⡜⢸⠀⢰⡎⠀⢇⡀⠀⣦⠀⢰⢀⢦⣰⢹⠀⡄⠀⣆⣾⠈
   414.2 │⠀⠀⠀⠀⠀⠸⡿⠋⠈⢿⣦⣴⣼⠋⠃⠀⠘⠀⠀⠀⠀⠀⠀⠀⠀⠉⠁⠸⠎⠃⠀⡿⠀⠀⠀⠀⠀⠀⠀⠘⠇⠀⠀⠀⠀⠀⠀⠀⠃⠉⠀⠀⠀⢻⠸
sonicshow  0.4s ago  analyzer  0.0s ago  li7500rs_buffer 198/200  li7500rs_freq 20.0 Hz
```

Keys: `q` quits, `space` pauses, `r` clears the plots, `c` changes the trace
colours, `-` / `+` halve and double how much history is shown, and `g` opens
the [Eddy Derby](#the-eddy-derby).

Both plots always show the same stretch of time, one minute by default, and the
range keys move them together, so a CO2 peak sits directly below the gust that
carried it. The keys step through 15, 30, 60, 120 and 240 seconds and stop at
each end. The window opens as the data arrives, so the first minute fills the
plot rather than a sliver at the right edge, and widening later uncovers
history instead of padding blank space. A stream that stops scrolls out of the
window, which is what tells you it stopped.

The four colour sets are `classic` (the 16 ANSI colours, and the only set a
terminal limited to those renders faithfully), `okabe` (Okabe-Ito, which keeps
its separations under the common forms of colour blindness), `aurora` and
`dusk`. The title bar names the source and the running version, as
`simulated · li7500rs · v0.4.0`, so a screenshot says which build drew it.

The display has no borders and no separate panels for the numbers. Each stream
gets one header line: the current values, the components named in their plot
colour, and the rule that separates the plots. In a narrow window the header
drops its units first and its status text second rather than wrapping.

`sw` is the standard deviation of the vertical wind and `TKE` the turbulent
kinetic energy, `0.5·(σu²+σv²+σw²)`. Both come free from the `mean(stdev)`
every `sonicshow` message already carries. Read them as a rough indicator of
mixing rather than a measurement: each standard deviation covers a single
second, so it misses the slower eddies a 30 minute flux average includes and
both come out too low. The demo sets `sigma_w` to 0.28 and the panel shows
about half that. A wider terminal also shows each component's standard
deviation.

To inspect the data rather than watch it, this example prints the raw bytes of
both streams next to the values they decode to:

```bash
uv run python examples/demo_wire_format.py
```

### The Eddy Derby

`g` opens a game. Breathe at the analyzer's inlet and the CO2 reading jumps
from a few hundred umol mol-1 to thousands within a fraction of a second, which
is the shortest route there is from "this box measures air" to "I can move that
with my lungs". It is meant for open days and visitors, played on the
instrument that is already running.

```
EDDY DERBY   breathe at the analyzer inlet - only 1000 umol mol-1 and above moves an animal

 CO2    3000 [##############################]  ambient 426   this breath 413 ppm s (0.2 s)

finish line 20,000 ppm s

  P1 snail ......................................................@_/|   20,412  5 breaths  #2
> P2 fish  .........................................><>              |   16,336  4 breaths  #1
```

Each player takes a turn at the inlet and their animal runs while they blow.
Only readings above 1000 umol mol-1 count, which is clear of anything the
atmosphere does: ambient air is 400-450 and a canopy at night reaches 600. The
turn passes once the air is clear of the breath, and the meter says `clearing`
through that second or so, when the score and the animal both stand still.

**The score is the area under the peak**, in ppm s, and that is not a
decoration. The highest reading would be the obvious score and it does not
work: an open-path head measures to about 3000 umol mol-1 and breath is more
than ten times that, so everyone who leans close pins the sensor and every peak
ties at the top of the scale. An integral keeps ranking blows after the reading
saturates, and it is the same operation the flux processing performs, over one
breath instead of half an hour.

The finish line is 20,000 ppm s, about four or five hard breaths, so every
derby is the same length and the number can go on a sign next to the mast. A
mast that holds the head out of a player's reach scores less per breath and
makes a long derby; `--derby-goal` moves the line, `--derby-players` starts
with more than two lanes, and `--breath-threshold` moves the level that counts.

Players who cross on the same numbered breath are separated by their total
score, since P1 opens every round and ranking by the moment of crossing would
hand P1 anything that finished level. Getting there in fewer breaths still wins
outright.

On the derby screen, `r` starts a new derby, `a` and `x` add and drop a lane,
`n` passes a turn for a player who has stepped away, and `escape` goes back to
the plots. Nothing is drawn behind the derby while it is up, so the game costs
nothing on top of the display it replaces, and the plots pick up where they are
when you close it.

Under `--demo` there is no analyzer to breathe into, so `b` breathes for you.
It adds a breath to the simulated CO2 stream as bytes on the wire, which the
game reads through the same decoder a real one would, saturation included. A
breath is also a spike on the gas panel, worth looking at afterwards.

### Pointing it at real data

Live and simulated data take the same path through the program, and only the
source of the lines differs. A real site needs three arguments:

```bash
uv run record-ec-visualizer-tui --record-config /path/to/record.toml --sonicshow-group <group> --sonicshow-port <port> --analyzer <name> --gas-var CO2
```

`--record-config` reads the site's `record.toml` for the analyzer addresses and
the `var_map`, so the values on screen use the site's own variable names. The
sonicshow address is not in that file; it is a default in rECorD's code, and
you pass it on the command line.

`--gas-var` selects the variable to plot and defaults to `CO2`. It must match
the name the site's `var_map` produces, not the analyzer's own name for it. A
wrong name is easy to overlook, since records keep arriving and the panel still
reports the stream as live while the plot stays empty. Records without the
plotted variable leave a gap rather than repeating the last value.

The unit beside the value is the site's own, read from `[datafile]`'s
`variables` and `units` lists in the same file. Any variable the analyzer
carries can be plotted, cell temperature and pressure and flow rate included,
so the unit cannot be assumed. If the config does not name one, the header
shows the value without a unit.

`--analyzer` matters only at sites running more than one analyzer. Without it,
all analyzer streams are read and drawn as a single line using the first
analyzer's `var_map`.

`--glyphs blocks` draws the plots with half blocks instead of braille, for
terminals whose font has no braille block. The one that matters is the Linux
virtual console, the monitor attached to the logging host, where the
alternative is to give the console a braille font. Both are described under
[Run the demo once](#run-the-demo-once).

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

Three properties of these streams limit what the program can do:

- `sonicshow` and `analyzershow` send a Python dictionary printed with `repr()`,
  not JSON. It uses single quotes, so `json.loads` rejects it. Parse it with
  `ast.literal_eval`.
- There is no high-rate sonic stream. Wind data arrives at 1 Hz from
  `sonicshow`. The full 20 Hz exists only in the data file, which has no
  timestamp column, so record times must be reconstructed from the file name
  and the fixed 20 Hz rate.
- The streams use TTL 0 and are bound to loopback by default, so they never
  leave the logging host. Reading them from another machine means either
  reconfiguring rECorD onto a LAN multicast group with a TTL above 0, or
  reading the data files from a share.

The actual groups and ports are deliberately not in this repository. The
defaults are in rECorD's source, and the values a site really uses are in its
`record.toml`, along with the analyzers it runs and their variable names.

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
installed there too. There are five steps: install, run the demo, find the
site's `record.toml`, check the connection with `--dump`, then start the
display. Keeping them separate means a failure points at one cause rather than
several.

Check the Python version first:

```bash
python3 --version
```

Debian 12 ships 3.11 and Ubuntu 24.04 ships 3.12, so the usual logging host
passes; if it does not, use the uv fallback at the end of this section. Run
everything below as the user that runs rECorD, for the reasons under
[Running it day to day](#running-it-day-to-day).

### Install

rECorD itself is installed with [pipx](https://pypa.github.io/pipx/), and that
works here too:

```bash
pipx install git+https://github.com/holukas/record-ec-visualizer-tui.git
```

On Ubuntu 24.04 pipx is the only option, not just the tidy one: the system
Python is marked externally managed, so `pip install` into it is refused.

On a host without outbound network access, build the wheel elsewhere and copy
it over with its dependencies. The wheel alone is not enough, since installing
it makes pip fetch textual and rich from PyPI. Everything involved is pure
Python, so wheels downloaded on any machine work on the logger:

```bash
uv build
```

```bash
pip download dist/record_ec_visualizer_tui-0.4.0-py3-none-any.whl -d wheelhouse
```

```bash
scp -r wheelhouse user@logger:/tmp/wheelhouse
```

```bash
pipx install --pip-args "--no-index --find-links /tmp/wheelhouse" /tmp/wheelhouse/record_ec_visualizer_tui-0.4.0-py3-none-any.whl
```

If the host's Python is older than 3.11, install with uv instead. It downloads
its own interpreter and leaves the system Python alone, but the download needs
network access:

```bash
uv tool install --python 3.12 /tmp/record_ec_visualizer_tui-0.4.0-py3-none-any.whl
```

### Run the demo once

The demo needs no addresses and no config, so it tests the installation without
involving the streams:

```bash
record-ec-visualizer-tui --demo
```

If two plots draw and move, the installation, the terminal and the locale are
all fine.

If the plots appear as rows of boxes instead of braille, the terminal cannot
draw the characters the plots are made of. There are two causes, and the second
is what you get on the machine's own monitor.

The cheap one is the locale. Check it with `locale`; if `LANG` is `C` or
`POSIX` rather than something ending in `UTF-8`, set `LANG=C.UTF-8`, which is
built into glibc and needs nothing generated first.

The other is the font. The Linux virtual console does not use the system's
fonts: it draws with a console font of at most 512 glyphs, and the default one
has no braille block. No locale setting changes that. Tell the two apart with

```bash
printf 'braille: [⠀⠁⣿]  blocks: [█▄▀]  box: [─│]\n'
```

Whatever comes out as a box is missing from the font. If that is the braille,
install a console font that has it, or draw the plots with something else.

#### Give the console a braille font

This keeps the full 2x4 resolution, and on Ubuntu it is one package. Debian and
Ubuntu ship the braille console fonts separately from `console-setup`, which is
why the example in `/etc/default/console-setup` refers to a file that is not
there:

```bash
apt-get install -y console-braille
```

It installs font data only, under `/usr/share/consolefonts/`. No daemon, no
service restart, nothing touching Python or rECorD.

The files are named `brl-HEIGHTxWIDTH.psf`, height first. Pick the one matching
your console's cell, which `showconsolefont -i` reports as rows, columns and
glyph count, and which `/etc/default/console-setup` states as `FONTSIZE` in the
opposite order: `FONTSIZE="8x16"` is 8 wide and 16 high, so the braille font is
`brl-16x8.psf`.

`setfont` combines several font files into one table, and every file has to
have the same character height:

```bash
setfont /usr/share/consolefonts/Lat15-Fixed16.psf.gz /usr/share/consolefonts/brl-16x8.psf
```

Nothing is permanent yet, so re-run the `printf` line and look at it. To keep
the pair, set it as `FONT` in `/etc/default/console-setup`, which overrides
`FONTFACE` and `FONTSIZE`:

```
FONT='Lat15-Fixed16.psf.gz brl-16x8.psf'
```

```bash
setupcon && update-initramfs -u
```

`setupcon` on its own restores whatever the file says, which is the way back if
a font looks wrong.

Watch the arithmetic when picking the Latin half. The console holds 512 glyphs
and braille alone is 256, so it pairs with a 256-glyph font whose remaining
glyphs must still cover the box-drawing `─` and `│` the plot uses for its axis
and header rule. That is what the `box:` part of the `printf` line checks.
Verified on Ubuntu 24.04 with `Lat15-Fixed16.psf.gz` and `brl-16x8.psf` on an
8x16 console.

#### Or draw the plots without braille

```bash
record-ec-visualizer-tui --demo --glyphs blocks
```

Half blocks are in every console font, so this needs no font work. It costs
half the resolution each way, because a half block carries 1x2 dots where a
braille cell carries 2x4, which is why it is never chosen automatically.
Nothing else changes: the same data, axes, header and gaps. It works with a
live site too, and applies to both plots.

Over SSH from a workstation neither of these is needed, since the font then
comes from your own terminal.

### Find the site's record.toml

Everything below needs the site's config, and its location is not fixed: rECorD
takes it as its second argument, so the running process is what knows. Ask it:

```bash
ps -eo pid,user,args | grep -i "[r]ecord"
```

The command line reads `record <SonicType> <path/to/record.toml>`. If that path
is relative it resolves against the process's working directory:

```bash
sudo ls -l /proc/$(pgrep -f "record .*\.toml" | head -1)/cwd
```

If rECorD is started by systemd, the unit spells it out instead:

```bash
systemctl cat 'record*'
```

Failing all of that, search for it:

```bash
sudo find / -name "record.toml" -not -path "*/site-packages/*" 2>/dev/null
```

The `-not -path` keeps the example config shipped inside the `record` package
out of the results. That one is stale, writing the timestamp keys in a form
rECorD no longer reads, and it holds no site's real addresses. Use the file on
the command line.

### Check the connection first

`--dump` prints the decoded records without starting the display, so you can
see whether the streams reach you at all:

```bash
record-ec-visualizer-tui --record-config /path/to/record.toml --sonicshow-group <group> --sonicshow-port <port> --dump
```

The analyzer addresses come from `record.toml`. The sonicshow group and port
are defaults in rECorD's code (`sonicshow_ip` and `sonicshow_port` in
`BaseReader.__init__`) rather than config entries, so you pass them separately.
The easiest way to read them off a logging host is the `sonicshow` program
installed alongside rECorD, whose `-g` and `-p` defaults are the same values:

```bash
sonicshow --help
```

The dump also gives you the right value for `--gas-var`. Analyzer records are
printed twice, first as they arrive with the instrument's own variable names,
then again after the site's `var_map` with the site's names. `--gas-var` has to
come from the second line, since the raw names never match. If the `after
var_map` line does not appear at all, the `var_map` does not fit what the
analyzer sends, and the display would stay empty for the same reason. Once
records from both streams appear, drop `--dump` and start the display.

### Running it day to day

```bash
tmux new -s ecvis 'nice -n 10 record-ec-visualizer-tui --record-config /path/to/record.toml --sonicshow-group <group> --sonicshow-port <port> --gas-var <var>'
```

`--gas-var` takes the name confirmed in the `--dump` step. Omitting it selects
the default `CO2`, which is only right if the site's `var_map` produces that
exact name. Add `--glyphs blocks` on the machine's own console rather than an
SSH session, for the reason under
[Run the demo once](#run-the-demo-once).

Run the visualizer as the user that runs rECorD, who can already read
`record.toml`. Port access is not the reason: both programs set `SO_REUSEADDR`
and `SO_REUSEPORT`, which is what Linux requires for a shared UDP bind, so
sharing the analyzer ports works from any account. A startup failure with
`OSError: [Errno 98] Address already in use` means the port is held by
something other than rECorD.

Run it inside tmux or screen, otherwise a dropped SSH connection takes the
display down with it.

Use `nice`. rECorD's 20 Hz loop warns whenever a cycle takes longer than 50 ms,
and the visualizer runs on the same machine. Redrawing both plots costs roughly
50 ms per second at the default 60 s range and less at the longest, so there is
room, but acquisition has priority.

### If nothing arrives

Multicast has to be enabled on the loopback interface. It usually is, since
rECorD receives its own analyzer data that way, but check first:

```bash
ip route show | grep 224
```

There should be a `224.0.0.0/4 dev lo` route. The `udpmulticast` README
explains how to add it, together with `ip link set multicast on lo`.

If the route exists and nothing arrives, name the interface. `--interface`
defaults to `0.0.0.0`, which leaves the choice to the kernel, and on a host
with a network card as well as loopback the kernel may pick the card while
these streams exist only on loopback:

```bash
record-ec-visualizer-tui --record-config /path/to/record.toml --sonicshow-group <group> --sonicshow-port <port> --interface 127.0.0.1 --dump
```

The setting applies to every stream, sonicshow as well as analyzers.

If only one of the two streams stays silent, the interface is not the cause.
Check that stream's address: the sonicshow address comes from the command line,
the analyzer addresses from `record.toml`.

## Program layout

| Module | Responsibility |
|---|---|
| `codec.py` | Decodes the two formats rECorD sends, and applies its `var_map` |
| `simulator.py` | Produces rECorD-format data for the demo |
| `sources.py` | Delivers `(stream, line)` pairs, from the simulator or from multicast |
| `model.py` | Keeps the recent values of each series, and when each stream was last heard from |
| `game.py` | Scores breaths out of the CO2 stream, and runs the derby between them |
| `tui/plot.py` | Draws the line plots, in braille or half blocks |
| `tui/derby.py` | The Eddy Derby screen |
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
