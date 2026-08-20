# CLAUDE.md

Guidance for Claude Code when working in this repository.

## What this project is

A terminal UI (Textual) that plots the data acquired by **rECorD** (*Robust
Eddy Covariance Data Acquisition*) in real time. rECorD is the eddy covariance
raw data logger developed at ETH Zurich (Grassland Sciences). This repo does
**not** log data; it only consumes what rECorD already broadcasts.

Stack: Python 3.11+, uv, hatchling, textual + rich, pytest + ruff. Development
happens on 3.12 (`.python-version`), but **the supported floor is 3.11 and
should stay there**: the logging hosts this is deployed to run Debian, which
ships 3.11, and a higher floor would force a second interpreter onto a machine
that is there to do acquisition. 3.11 is also the lower limit, because the site
config is read with `tomllib`. Both ends of the range are tested.

## Architecture

**Simulated and live data must travel the same path**, so that connecting to a
real site is a change of source and nothing else.

```
simulator.py ─┐
              ├─> sources.py ──> (stream_name, payload_bytes) ──> codec.py ──> model.py ──> tui/
multicast  ───┘
```

| Module | Responsibility |
|---|---|
| `codec.py` | `LineAssembler`, the two decoders, `mean(stdev)` / buffer-fill parsing, and `VariableMap` (rECorD's `var_map`, reimplemented) |
| `simulator.py` | `RecordSimulator` — emits rECorD-format **bytes**, not objects |
| `sources.py` | `simulated_lines()` / `multicast_lines()`, both yielding `(stream, line)` |
| `model.py` | `SeriesBuffer`, `StreamHealth`, `LiveState` — rolling state, no I/O |
| `tui/plot.py` | `render_braille_plot()` → `rich.text.Text`, same shape as bico's |
| `tui/app.py` | The Textual app; knows only about an async iterator of lines |

Rules that keep the two paths identical:

- **The simulator must produce real wire bytes.** If it yielded dicts instead, a
  format mistake would stay hidden until the first real connection. Its tests
  assert on the bytes, including that a sonicshow payload is *not* valid JSON.
- **Stream names are the routing key**: `"sonicshow"` and `"ga:<analyzer>"`.
  The app dispatches to the right decoder by name.
- **The simulator is opt-in, behind `--demo`.** Simulated and live data are
  indistinguishable downstream, so a simulated default would let the bare
  command on the logging host display invented numbers. Without `--demo` the CLI
  expects a live site and errors if given no addresses; options belonging to the
  source that was not selected are rejected rather than ignored, so a mistyped
  address cannot turn into a demo run.
- **No multicast group or port is defaulted anywhere in the package.** They are
  CLI arguments, or read from the site's `record.toml` via `--record-config`.
- `sources.open_multicast_socket` is the portable replacement for
  `udpmulticast.get_multicast_client_socket`, which cannot run on Windows. It is
  covered by a real loopback round-trip test in `tests/test_sources.py`.

The gas analyzer path applies the site's `var_map`, so the plotted variable is
named the way the site names it (`CO2` for a mixing ratio in umol mol-1). Its
**unit is read from the config too**, out of `[datafile]`'s parallel
`variables` / `units` lists, and the header prints nothing when the config
cannot answer. The unit used to be the literal `umol mol-1`, which is right for
a CO2 mixing ratio and wrong for everything else an analyzer carries — the same
`var_map` offers cell temperature, pressure, flow rate and a diagnostic code,
and a live display must not put a confident label under a number it cannot
vouch for. The
sonic `var_map` is applied to sonicshow's *raw* keys, which is how `Wc1/Wc2/Wc3`
get displayed as `U/V/W`.

When the analyzer panel has nothing to draw but records are arriving, it names
the variables the `var_map` produces (`_gas_empty_message`). That is the shape
of a mistyped `--gas-var`, and it is a silent failure otherwise: the stream
reads as live and the plot stays empty forever. The mapped names exist nowhere
else on screen, so without this the only way to find them is to stop the
display and run `--dump`.

Layout is frugal on purpose and should stay that way: no borders, no margins
between the plots, no separate readout panels. Each stream is one `StreamPanel`
that draws a single header line (current values, legend, and the rule that
separates it from the plot above) followed by braille rows. Borders would cost
four rows of plot for decoration. The header degrades by dropping parts instead
of wrapping. Each optional part is a `(text, min_width)` pair and carries its
own threshold; the thresholds are cumulative by construction, so a part is
budgeted the width of everything that outranks it plus its own cost.
Ranking, least important first: units, then per-component deviations, then
`sw`/`TKE`, then the metadata. Adding a part means recomputing the thresholds
of everything below it, or the header wraps and costs a plot row;
`TestHeaderDegradation` in `tests/test_app.py` asserts it fits at every width
down to the point where the value chips alone no longer do.

The trace colours come from a `Palette` in `tui/app.py`, cycled with `c`, and
two things about the set should survive future edits. **`classic` stays first**:
it is the only palette built from the 16 ANSI colours, and on a terminal
limited to those the hex palettes are approximated to the nearest of eight,
which merges hues chosen to be distinct. The default therefore has to be the
one that cannot degrade. And **within a palette the three wind colours are
separated by hue, not lightness** — they share a plot, they overlap, and the
renderer resolves an overlap by last writer wins, so two traces alike in hue
become one trace of ambiguous ownership. The gas has a plot to itself and only
has to be legible against the background the app never paints over.

`LiveState.sigma_w` and `LiveState.tke` are computed from data the parser
already has: sonicshow reports each component as `mean(stdev)`, so TKE is one
multiply-add over three numbers. **Any label that quotes them must mention the
averaging interval**: one second of 20 samples captures only the fastest eddies,
so both read low against properly computed values (the demo's configured
`sigma_w = 0.28` displays as ~0.14). They are a live indicator of mixing, not
flux-grade quantities. TKE stays `nan` until all three components have been
seen, instead of totalling only two.

**Render cost is a hard constraint on this project.** The intended deployment
is the logging host, where rECorD's 20 Hz loop warns as soon as a cycle exceeds
50 ms, so the TUI must stay out of its way. Four things keep it cheap. All
four should survive future edits:

- **A blank cell inherits the colour run it sits in rather than ending it.**
  This is the single largest saving on the path and it is not about drawing at
  all. Textual converts every `Span` with `Style.from_rich_style`, once per
  span per update, with no cache — that conversion was 48% of a `_refresh`. A
  trace weaving across a row leaves single coloured cells between blanks, and
  breaking the run at each blank turned one row into dozens of spans. A cell
  with no dots displays nothing, so what colour it carries cannot be seen; the
  run therefore crosses it. 756 spans a frame became 336, and 22% came off a
  frame. Never restore the break: the cost is Textual's, per span, and it
  scales with how wiggly the trace is.
- `plot._sample_points` walks each series once: it collapses anything denser
  than the dot grid to the per-column min/max envelope, and returns the axis
  bounds from the same pass. The picture is identical (a dense trace's vertical
  smear *is* its envelope), cost stops scaling with history length, and a dense
  series never materialises the points the grid could not have shown. The dense
  path walks a column at a time with the extremes in locals; tagging each
  sample with its column and filing it into a dict cost a tuple per sample and
  a lookup and store per column, which was most of the pass.
- `render_braille_plot` assembles the frame as one string plus a list of
  `Span`s and hands it to `Text` once. Appending was 29% of a frame: every call
  strips control codes and extends the span list. A row of cells is a
  `bytearray` of bit patterns turned into glyphs by one `translate`, and the
  coloured runs are slices of it. The two mappings from a sample to a dot are
  written out at the call site and `_draw_segment` writes its own dots rather
  than calling `set_dot`: both run tens of thousands of times a frame, where
  the call costs more than the arithmetic inside it. Keep the axis expressions
  in their original order — rearranging them algebraically moves a rounding
  boundary and a dot with it.
- `VisualizerApp._refresh` redraws only when the window has scrolled by a whole
  dot column, which is the smallest movement the grid can express. The rate then
  follows the range on display rather than the stream: a 15 s window steps on
  every frame, a 240 s one about twice a second.

Measure before changing anything on this path, and measure it **against a git
revision in one process, interleaved, best of many**. This machine's run-to-run
drift is larger than any of these effects: the same benchmark in two separate
runs made the same change look like a 2x win and a 36% regression. The first
guess about where the time goes has also been wrong three times — segment
drawing was not the dominant cost, neither was the per-cell loop, and the
largest single item turned out to be outside this package entirely, in
Textual's per-span style conversion. Profile a whole `_refresh` through
`App.run_test`, not `render_braille_plot` alone: half the cost of a frame is
downstream of the function under the microscope.

**Both panels are drawn from one token, or neither is.** They are stacked to be
read against each other, and two plots of the same seconds that scroll at
different moments are harder to compare than either alone. Gating each panel on
its own stream did that: the analyzer delivers at 20 Hz and stepped the lower
plot every frame, while sonicshow delivers once a second and the wind plot sat
still in between — reported from the logging host as the lower plot moving on
its own. `test_the_two_panels_step_together` counts draws rather than comparing
pictures, because two consecutive redraws can produce identical text.

The token carries the palette and window indices and each stream's first
message alongside the scroll position and both sizes. None of those changes the
scroll position, so a keypress would otherwise redraw nothing until the window
had moved on and would read as a dead key.

What the pair costs at the logging host's 230x30 geometry, measured as a whole
`_refresh` inside a running app: roughly 3.5-4 ms a frame at a 15 s window,
7 ms at 60 s and 11 ms at 240 s. Multiplied by the rate the step rule allows,
that is around 28 ms/s at 15 s, 49 ms/s at 60 s and 19 ms/s at 240 s. The
longest window is the cheapest, because it scrolls a dot column only twice a
second while a frame there is the most expensive one to draw. Figures to the
nearest few ms, for the reason above: the drift between runs is wider than the
differences.

**The worst point of the ladder is wherever the scroll step crosses the refresh
interval**, and at 230 columns and 8 Hz that is the 60 s default: the step is
about 138 ms against a 125 ms tick, so the window still redraws at very nearly
the full rate while a frame there already costs double a 15 s one. Past that
point every window is step-limited and a lower refresh rate buys nothing;
before it, the rate is what sets the cost.

What a cell is drawn from is a `plot.GlyphSet`: `BRAILLE` (2x4 dots per cell)
and `BLOCKS` (1x2, half blocks), selected with `--glyphs`. The fallback exists
because the Linux virtual console on the logging host renders with a
console-setup font of 256 or 512 glyphs containing no braille, so a braille
plot there is not merely plain but unreadable — its blank cell is U+2800, so
every empty cell of the grid becomes a replacement box and the trace vanishes
among them. Two things about it should survive future edits. **It is never
selected automatically**: nothing at this level distinguishes a terminal that
cannot draw braille from one that can, and guessing wrong would silently halve
the resolution of a display that was fine. **The console is fixable, though**,
and the README says how: `apt install console-braille` supplies
`brl-HEIGHTxWIDTH.psf`, which `setfont` combines with a 256-glyph Latin font of
the same height to fill the console's 512-glyph table. Verified on Ubuntu 24.04
with `Lat15-Fixed16.psf.gz` and `brl-16x8.psf`. So `BLOCKS` is the answer for a
console nobody wants to reconfigure, not the only answer. And **the geometry stays bound as
default arguments on `set_dot`**, not read off the dataclass per call — that
closure is the innermost operation in the renderer, and the reason the table
lookup is flattened in the first place is that attribute access there is not
free.

Two correctness rules follow from the plot's x axis being **sample-indexed**,
not time-indexed. Both are easy to undo by accident:

- Every wind component gets a sample from every sonicshow message, `nan` if
  absent or unparseable (`LiveState.ingest_sonicshow`). A series that skipped an
  entry would render shifted against the others for the rest of the run.
- A stream that goes silent must still occupy the slots it missed
  (`SeriesBuffer`, `detect_gaps=True`). Nothing is appended while nothing is
  arriving, so without this the trace closes over an outage and the axis
  silently compresses while the header still claims "last 54 s". For EC data,
  the gap is what an operator needs to see.

`SeriesBuffer` measures the cadence instead of taking it from configuration. An
analyzer's rate is a per-site value that this package does not hardcode, and the
stream itself is the most reliable source for it. Ordinary arrivals extend a
run and the estimate is that run's average; a late arrival is measured against
it, pads `round(delta / interval) - 1` slots, and never pollutes the estimate.
Use `round`, not `int`: an exact 4 s gap at 20 Hz evaluates to 79.999….

Verified end to end: a 4 s analyzer dropout produces 80 `nan` slots and renders
as a 6-column hole, against 0 blank columns for uninterrupted data.

**The estimate is bounded from below as well**, by the same `gap_factor`, and
this is not symmetry for its own sake. Arrival times describe the stream only
while this program keeps up with it. A frame that outlasts one sampling
interval blocks the event loop, and the records queued behind it are then
delivered back to back — deltas near zero from an instrument whose rate never
changed. Letting those into the average was a one-way ratchet: each burst
pulled the estimate down, which made the next ordinary arrival look like an
outage, which padded slots instead of feeding the estimate back up. It ran away
within seconds. On the logging host a minute of analyzer data became a
two-second window that was 99% padding, and it looked exactly like a failing
analyzer. `TestGapDetection` covers both directions.

**The estimate has to be steady, not merely unbiased**, and that is why it is
a run average rather than a moving average over every delta. `window_values`
turns it into a slot count and the renderer spreads that many slots across the
full width, so any change in the estimate moves every sample sideways.
Scheduling jitter is the same few milliseconds at any rate, which makes it a
large share of 50 ms and a negligible share of 1 s: with a per-delta EMA the
analyzer panel jumped up to 5.8% of its width between consecutive frames while
sonicshow sat perfectly still — reported from the logging host as the lower
plot not looking smooth. A run of consecutive in-band arrivals telescopes to
`(last - first) / (n - 1)`, so it carries the jitter of two arrivals spread
over n of them: worst frame-to-frame step 0.25%, a 23x improvement, with the
1 Hz panel unchanged at zero. A burst or a gap ends the run rather than
entering it, and the published estimate stands until a fresh run reaches
`MIN_RUN`; under delivery too broken to measure, the last trustworthy answer
beats a fresh untrustworthy one. `TestWindowValues` asserts the frame-to-frame
step, not the total spread — a slow drift of a few slots is invisible, a jump
is what the eye catches.

Warm-up is a duration (2 s), not a count of arrivals, and during it the
estimate is the overall rate rather than the last delta. Under bursty delivery
no single delta is the cadence — each is either far too short (inside a burst)
or far too long (across the stall that caused it) — while the count over enough
wall time is neither. A fixed count would only cover a stall cycle at one
particular stream rate; sonicshow at 1 Hz and an analyzer at 20 Hz need the
same guarantee.

**Both panels show one window, measured in seconds, and the window is what the
keys move.** Before that, history was a count of samples per buffer, so 240
slots of a 1 Hz sonic was four minutes while 1200 slots of a 20 Hz analyzer was
one, and the two plots could not be read against each other at all — which is
the only reason to stack them, since the question an operator asks is which
gust carried which peak. `SeriesBuffer.window_values` converts the requested
seconds into slots with the measured cadence, takes the tail, and pads with
`nan` at whichever end is short. The padding is not cosmetic: the renderer
indexes x by sample and stretches whatever list it is given across the full
width, so two panels line up only if each list covers the window exactly. A
young stream drawn without the pad would be smeared across a span it never
observed, and would appear to disagree with the other panel about when things
happened.

Four things about it are easy to undo and each one silently breaks the
alignment it exists to provide:

- **What is drawn is `visible_seconds`, not `window_seconds`.** The window
  opens as the data arrives and stops at the selected range, so a fresh start
  draws the seconds it has across the whole plot rather than a sliver pinned to
  the right edge of a mostly empty minute — which on a logging host reads as a
  stream that is not arriving. Both panels take the same figure, computed once
  from the shared clock; sizing each to its own stream would set the two plots
  to different scales exactly when they differ most. The floor
  (`MIN_WINDOW_SECONDS`) exists because two or three samples make a plot whose
  y axis rescales wildly on every frame.

- **The window ends at `now`, not at the stream's own last sample.** Slots are
  appended only when something arrives, so a stream that stops would otherwise
  sit frozen against the right edge — drawing a full, healthy trace with not
  one `nan` in it, a whole window out of phase with its neighbour, under a
  header claiming both show the same seconds. `_refresh` reads
  `LiveState.elapsed` once and hands it to both panels.
- **The whole second is in each panel's redraw token**, for the same reason: a
  silent stream delivers no messages, and the gate keys on message count, so
  without it the dead panel would never redraw and could not scroll out even in
  principle. It costs nothing — the wind panel already redraws once a second
  and the gas panel far more often.
- **Buffers are sized past `MAX_WINDOW_SECONDS`, never to it**
  (`WINDOW_HEADROOM`). The slot count comes from the *measured* cadence, so an
  estimate a few percent below nominal asks for more slots than an exact buffer
  holds, and the shortfall pads as `nan`: a gap the stream never had, drifting
  frame to frame as the estimate wanders, on the one display whose purpose is
  showing the real ones. The same headroom covers a site whose analyzer runs
  faster than the rate the buffer was provisioned for. It costs memory only —
  what reaches the renderer is the window, not the buffer.

The window's cost is the reason the ladder stops at 240 s rather than doubling
on. Measured at 90 columns, the gas panel alone costs 1.9 ms/frame at 60 s
(1200 points) and 4.4 ms at 240 s (4800), so at the 8 Hz refresh the longest
window spends ~35 ms/s against ~16 ms/s for the default. That is affordable
because it is opt-in and bounded; another doubling would not be.

Headless tests drive the real app via `App.run_test`; see `tests/test_app.py`.
Avoid `print()` inside a `run_test` block: Textual routes it through a cp1252
stream on Windows and non-ASCII output raises. For the same reason, user-facing
unit strings stay ASCII (`m s-1`, `umol mol-1`), rECorD's own notation.

## Reference sources

Everything below comes from reading the source of rECorD and its two in-house
dependencies:

| Package | Version | What it does |
|---|---|---|
| `record` | 0.4.16 | The acquisition program itself |
| `pygl` | 0.9.5 | `Datafile` (TOA5/ICOS writing), logging helpers |
| `udpmulticast` | 0.1.26 | UDP multicast socket helpers |

All three are poetry projects published to an institution-internal package
index, **not to PyPI**. This project therefore cannot import `record` and must
reimplement the small amount of client logic it needs (multicast subscribe +
parse).

Local read-only snapshots of all three are kept outside this repo, under a
`references/` directory in the project's data folder; ask the maintainer for the
location. Line references below (e.g. `record/utils.py:826`) point into those
snapshots.

## How rECorD works

`record` is a single asyncio process, started as
`record <SonicType> <global_config.toml>`. Its main loop (`BaseReader.start`,
`record/utils.py:826`) is driven by the **sonic**, which acts as the clock:

1. Block on the first byte from the sonic serial port. Its arrival is the
   record timestamp.
2. While the rest of the sonic line trickles into the UART buffer, do async work
   concurrently: read gas-analyzer (GA) UDP sockets, and write the *previous*
   record to the data file.
3. Read + parse the rest of the sonic line, push it into a record buffer
   (deque, default 200 records).
4. Once per second, broadcast a summary on the *sonicshow* multicast socket.

Key structural points:

- **Sonic**: serial, `record/sonics.py`. `GillHS50` and `GillR3_50` are
  implemented (`GillR3_50` only differs in `recnum_max`). Both ASCII and binary
  Gill formats are parsed; the output format is auto-detected in `Sonic.find()`.
  Sampling frequency is hard-coded to 20 Hz (`Sonic.__init__` default
  `sampling_freq=20`) and never read from the TOML.
- **Gas analyzers**: never talk to rECorD directly over serial/TCP. A separate
  process (subclass of `BaseAnalyzer`, `record/ga_utils.py:15`) owns the
  instrument and republishes each record as **one JSON object per line** on a
  UDP multicast group. rECorD subscribes to that group. This is the
  inter-process boundary and the reason UDP multicast is a hard dependency.
- **Record alignment**: `GasAnalyzer` (`record/utils.py:85`) keeps a deque the
  same length as the sonic buffer and sorts async GA records into slots aligned
  to sonic records; it copes with jitter, with bursts after network glitches,
  and with GA frequencies above/below the sonic's. Every written GA record
  carries a status bitfield (see below).
- **Output**: TOA5 (or ICOS) CSV written by `pygl.Datafile`, flushed every 100
  records, rolled over per `option` (`"daily"` or `"ec.N"` = N half hours), and
  gzipped in a subprocess on rollover. Line 4 of the TOA5 header is misused to
  tag each column with its source device, e.g. `[GillHS50]`, `[LI7500RS]`
  (`record/record.py:97`). See "Data files" below for the details.

## Transport: UDP multicast

All of rECorD's live streams go through `udpmulticast`. Two facts shape the
design of this project:

- **The streams do not leave the host.** `get_multicast_server_socket`
  (`udpmulticast/server.py:10`) defaults to `ttl=0` ("does not leave the local
  host") with `IP_MULTICAST_LOOP=1`, and binds to `127.0.0.1` everywhere
  rECorD uses it. So **the visualizer must run on the same machine as rECorD**,
  unless the site reconfigures. There is a convention for that, visible in
  `udpsend.py`: one well-known group means localhost and binds to `127.0.0.1`,
  another means LAN and binds to a real NIC address. `BaseAnalyzer` takes
  `multicast_bind_ip` and `ttl` as parameters, so an analyzer *can* be published
  on the LAN; `BaseReader`'s sonicshow socket hardcodes `127.0.0.1` and the
  default TTL.
- **The client socket recipe is Linux-only.** `get_multicast_client_socket`
  (`udpmulticast/client.py:11`) sets `SO_REUSEPORT` and binds to the *multicast
  group address*. `SO_REUSEPORT` does not exist in Python on Windows, and
  Windows requires binding to `INADDR_ANY` rather than the group. Our client
  must use `SO_REUSEADDR` + bind `('', port)` on Windows, then join the group
  via `IP_ADD_MEMBERSHIP` with `struct.pack("4sl", inet_aton(group),
  INADDR_ANY)`. Do not copy the upstream function verbatim.

On Linux the loopback interface also needs a multicast route
(`224.0.0.0/4 dev lo`, plus `ip link set multicast on lo`); see the
`udpmulticast` README. If nothing arrives on a machine that is definitely
running rECorD, check this first.

**Do not write concrete multicast groups or ports into this repo.** They are
omitted on purpose. The defaults live in rECorD's source (`sonicshow_ip` /
`sonicshow_port`, `analyzershow_ip` / `analyzershow_port`) and the site's real
values live in its `record.toml`. Code should read them from config with the
upstream defaults as fallback, not hardcode them; if a default is needed at
runtime, source it from the site config rather than restating it in
documentation.

Framing is newline (`b'\n'`) delimited, and messages can exceed one datagram, so
a reader must accumulate until it sees a separator rather than treating each
datagram as a record (`MulticastProtocol.datagram_received`,
`udpmulticast/common.py:26`).

## Data sources available to this visualizer

Ordered by usefulness. Sources 1 and 2 are the ones a TUI would normally use.

### 1. `sonicshow` — 1 Hz sonic + system summary

- Multicast group and port come from the `sonicshow_ip` / `sonicshow_port`
  defaults in `BaseReader.__init__` (`record/utils.py:653`); the `sonicshow` CLI
  repeats them as its `-g` / `-p` defaults. One message per `sonicshow_interval`
  (1 s), newline-terminated.
- **The payload is a Python dict `repr()`, not JSON**: it is built as
  `f"{sonicshow_dict}\n".encode()` (`record/utils.py:933`), so it uses single
  quotes. Parse with `ast.literal_eval`, never `json.loads`.
- Reference consumer: the `sonicshow` CLI → `DeviceShow` (`record/utils.py:987`),
  which just prints each datagram.
- Keys, from `GillHS50.compose_sonicshow_info` (`record/sonics.py:500`),
  aggregated over the records of the last interval:

  | key | meaning | type |
  |---|---|---|
  | `Wc1`, `Wc2`, `Wc3` | wind components u, v, w | `"mean(stdev)"` string, 2 decimals |
  | `SOS` | speed of sound / sonic temperature (K or °C per `SOSREP`) | same |
  | `PRT` | absolute temperature, only if `ABSTEMP` is on | same |
  | `Error` | sonic error code — `StaD` of a record where `StaA == 0` | int |
  | `IncX`, `IncY` | inclinometer, degrees (raw × 0.01) | float |
  | `Gain` | `StaD` of a record where `StaA == 5` | int |

  Plus, added by `BaseReader.start` (`record/utils.py:927`):

  | key | meaning |
  |---|---|
  | `sonic_buffer` | `"used/max"` string, sonic record buffer fill |
  | `<ga>_freq` | estimated GA sampling frequency in Hz, 1 decimal |
  | `<ga>_buffer` | `"used/max"` string, that GA's record buffer fill |

  `<ga>` is the analyzer's config key, e.g. `li7500rs_freq`.

  Note the mean/stdev strings are pre-formatted text, so the visualizer has to
  re-parse them if it wants numbers for plotting.

### 2. `analyzershow` — ~1 Hz gas analyzer summary

- Group and port from the `analyzershow_ip` / `analyzershow_port` defaults in
  `BaseAnalyzer.__init__` (`record/ga_utils.py:19`): same group as sonicshow,
  the next port up.
- Also a Python dict `repr()`, same parsing caveat.
- Contents are per-analyzer and configured via `analyzershow_variables`, a
  `{variable: aggregation}` mapping, where aggregation is `avg` (rendered
  `"mean(stdev)"` in `.2e` notation), `smp` (last value), `max`, or `min`
  (`BaseAnalyzer.aggregate_list`, `record/ga_utils.py:113`).
- Produced by the *analyzer* process, not by rECorD. It only exists if the site
  runs a `BaseAnalyzer` subclass.

### 3. Raw GA stream — full rate, real JSON

- The GA's own multicast group/port, taken from the `ip` and `port` keys of the
  site's `[gasanalyzers.<name>]` section. Not a code default; it is per site.
- One `json.dumps` object per line at the analyzer's rate (~20 Hz). This is
  genuine JSON (`record/ga_utils.py:268` and `:296`).
- Structure is nested and analyzer-specific; the config's `var_map` describes
  the path, e.g. `var_map.Data.CO2D = "CO2_CONC"` → `{"Data": {"CO2D": ...}}`.
  Buffered records get an extra `{"Auxiliary": {"BufferSize": n}}`.
- **This is the only high-rate stream on the network.** rECorD exports no
  high-rate sonic stream: wind data is only available at 1 Hz via sonicshow,
  or at full rate by tailing the data file.

### 4. Data files

For full-rate sonic data, the fallback is to tail the file rECorD is currently
writing. Details, all from `pygl/pygl.py`:

- **Location is flat.** `Datafile._compose_filepath` (`pygl/pygl.py:159`) only
  applies date directories and `subdir` when `archive_dirs` is true, and
  `record.py` never passes `archive_dirs`, so it stays `False`. The `date_dirs=True`
  and `subdir=ec_setup_dir` that `record.py` does pass are therefore **ignored**,
  and files land directly in `workingdir` = `[datafile].root_dir`, defaulting to
  `/home/data/<hostname>`.
- **Filename**: `<SITE>_<type>_<timestamp><ending>`, e.g. `ECDA_ec_20260726-1430.dat`.
  `<SITE>` comes from `get_site()` (`pygl/pygl.py:469`): the hostname truncated
  at `-idaq`, uppercased. The timestamp is `YYYYMMDD` for `option="daily"` and
  `YYYYMMDD-HHMM` for `option="ec.N"`.
- **There is no TIMESTAMP column.** `BaseReader.write_to_file` calls
  `_prepare_data_string(None, ...)` (`record/utils.py:786`), passing `None` as
  the time, and the site's `variables` list contains no `TIMESTAMP`. Record
  timing must be reconstructed from the filename plus the fixed 20 Hz rate.
  Anything derived this way drifts; do not present it as an exact timestamp.
- **Format**: comma-separated, `\r\n` line endings. Missing values are the
  literal `"NAN"` *including the quotes* for TOA5 (`"NaN"` for ICOS). Non-numeric
  values are double-quoted, numbers are not.
- **TOA5 header**, 4 lines, all fields double-quoted (`pygl/pygl.py:349`):
  1. `"TOA5",<hostname>,<platform.machine()>,<empty serial>,<platform.platform()>,<program path>,<rECorD version>,<table name>`
  2. variable names
  3. units
  4. device tags: `[GillHS50]`, `[LI7500RS]`, … (this is the "aggregations"
     line, repurposed)

  ICOS has a single header line of quoted variable names and no units.
- Rollover: at midnight (`daily`) or the next N×30-minute boundary (`ec.N`), the
  old file is gzipped in a separate process and the original deleted. A file
  that vanishes and reappears as `.gz` is normal rollover, not an error.

## Status and diagnostic codes

**GA status bitfield** — `<GA>_STATUS` column in the data file, constants in
`GasAnalyzer` (`record/utils.py:89`):

| bit | name | meaning |
|---|---|---|
| `0x80` | `NO_RECENT_DATA` | no record from the analyzer for this sonic record |
| `0x20` | `DATA_REPEATED` | last valid record copied forward (up to `max_rep`, then NaN) |
| `0x10` | `NO_GA_RESPONSE` | analyzer not responding |
| `0x08` | `DATA_DISCARDED` | at least one record was dropped to stay aligned |
| `0x04` | `DATA_BUFFERED` | record was time-sorted into the buffer, not taken live |
| `0x01` | `JSON_ERROR` | JSON parse failure |

These are *not* in sonicshow, only in the data file.

**Sonic `StaA` / `StaD`** (Gill): `StaA` doubles as the record counter, cycling
`1..recnum_max` (10 for HS-50, 6 for R3-50), and as an address selecting what
`StaD` means. `StaA == 0` → instrument error, `StaD` is the error code.
`StaA == 5` → gain. `StaA == 7..10` → inclinometer X/Y high/low bytes. A break
in the `StaA` sequence means a lost record and triggers a full restart of the
reader (`RuntimeWarning` → `try_restart`, `record/utils.py:740`).

## Configuration files (TOML)

Two files, both needed to interpret a live stream:

- **Global** (`data/record.toml`): `[datafile]` (`variables`, `units`, `format`,
  `option`, `type`, `ending`, optional `multiplier`/`offset` per variable),
  `[sonic]` (`device`, `baud`, `line_ending`, `var_map`, `recnum_var`,
  `full_config`), and `[gasanalyzers.<name>]` (`ip`, `port`, `var_map`,
  `status_var`, `max_rep`, `max_jitter_buffer`, optional `timestamp.*`).
- **Sonic** (`data/gillHS50.toml`): flat key/value pairs pushed verbatim into
  the instrument (Gill command names, uppercased).

`var_map` maps *raw instrument variable → data-file variable*, and may be
nested to mirror a nested JSON stream. `VariableMapping` (`record/utils.py:29`)
flattens it. To label GA values meaningfully, the visualizer needs the same
config.

## Known issues in the reference source

Relevant because they affect what we can rely on:

- `record.py` offers `Metek_uSonic3` as a CLI choice, but no such class exists
  in `record/sonics.py`, so selecting it raises `AttributeError`. Only the two
  Gill sonics actually work, despite `data/metek.toml` existing.
- The example `data/record.toml` writes flat `use_timestamp` / `timestamp_var`
  keys, but `record.py:176` reads a nested `[gasanalyzers.<name>.timestamp]`
  table with `use` / `var` / `format` / `factor`. The example is stale; the
  README's nested form is authoritative.
- Timestamp-based buffering logs "provisional and not tested in this version".
- `fileformat = "ICOS"` cannot work from rECorD: `Datafile` builds ICOS
  filenames from `kwargs['logger_id']` and `kwargs['datafile_id']`
  (`pygl/pygl.py:98`), and `record.py` passes neither → `KeyError`. Only TOA5 is
  usable in practice.
- `Datafile._compose_filename` and `_compose_filepath` use
  `current_time=datetime.now()` as a *default argument*, evaluated once at
  import. The initial filename is therefore stamped at import time; rECorD
  works around this by calling `new_file(..., force=True)` at startup.
- `get_site()` does `hostname[:hostname.find('-idaq')]`. On a host whose name
  does not contain `-idaq`, `find` returns `-1` and the last character of the
  hostname is silently chopped off.
- `_prepare_data_string` catches `KeyError` around building the line but then
  falls through to `outstr += "\r\n"`, which would raise `UnboundLocalError`.
  Unreachable in practice, since `_parse_variable` handles missing keys itself.

## Implications for this project

- Implement our own multicast subscriber; do not depend on `record`, `pygl`, or
  `udpmulticast`. Write the socket setup portably: the upstream client recipe
  does not run on Windows (see "Transport" above).
- **Deployment is constrained**: with rECorD's defaults (TTL 0, bound to
  loopback) the live streams are reachable only from the logging host itself.
  Either the TUI runs there, or it reads data files from a share, or rECorD is
  reconfigured onto the LAN-scoped multicast group with a non-zero TTL. This is
  the first design decision to settle.
- Support two parsers: `ast.literal_eval` for `sonicshow`/`analyzershow`,
  `json.loads` for raw GA streams. Never assume JSON for the former.
  Accumulate to a `\n` before parsing.
- Treat every stream as lossy: UDP, no retransmit, and the sender formats
  numbers as text. Missing datagrams are normal; show staleness rather than
  freezing on the last value (`DeviceShow` uses a 1.2 s timeout).
- Reading the site's `record.toml` is the most reliable way to find out which
  GAs exist, their multicast addresses, and the variable names to display.
- If tailing data files: no timestamp column exists, files are flat in
  `root_dir`, and the current file disappears on rollover (gzipped). Detect the
  new file by name rather than holding a file handle.

## Conventions in this repo

Mirrors the sibling project `diive`: hatchling, GPL-3.0, ruff with
`line-length = 110` and `select = ["E4", "E7", "E9", "F", "B"]`, dependencies
pinned with lower bounds, `uv.lock` committed.

```bash
uv sync
```

```bash
uv run pytest -q && uv run ruff check .
```
