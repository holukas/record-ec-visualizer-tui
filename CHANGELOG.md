# Changelog

Notable changes to this project, newest first. Version numbers follow
[semantic versioning](https://semver.org/spec/v2.0.0.html).

## v0.4.0 | 28 Aug 2026

### Added

- The Eddy Derby, a game played through the analyzer's own inlet, on `g`.
  Breathe at the inlet and the CO2 reading jumps from a few hundred
  umol mol-1 to thousands, which is the shortest route there is from "this box
  measures air" to "I can move that with my lungs". For open days, on the
  instrument that is already running.
- Each player takes a turn and an ASCII animal runs along their lane while they
  blow. The turn passes once the air is clear of the breath. On the derby
  screen, `r` restarts, `a` and `x` add and drop a lane, `n` passes a turn, and
  `escape` goes back to the plots.
- A breath scores the area under its peak, in ppm s, above 1000 umol mol-1. The
  peak value would not do: an open-path head measures to about 3000 and breath
  is more than ten times that, so anyone who leans close pins it and the peaks
  all tie.
- The finish line is 20,000 ppm s, four or five hard breaths, the same every
  session. Lanes that cross on the same numbered breath are placed by total
  score. `--derby-goal`, `--derby-players` and `--breath-threshold` set the
  line, the lanes and the level that counts.
- `b` breathes for you under `--demo`. The simulator puts it on the wire as
  bytes and clips it at the analyzer's 3000 umol mol-1 range, so it reaches the
  game through the same decoder a real one would.

### Changed

- The plots are not redrawn while the derby is up, so the game costs nothing on
  top of the display it replaces. The streams keep arriving, and the plots pick
  up where they are when it is closed.

## v0.3.1 | 20 Aug 2026

### Changed

- Frames are 27-34% cheaper to draw. Most of the saving is not in the drawing:
  Textual converts every colour span with `Style.from_rich_style` on each
  update, once per span and uncached, which was 48% of a redraw. A trace
  weaving across a row leaves single coloured cells between blanks, and ending
  the run at each blank turned one row into dozens of spans. A blank cell shows
  nothing, so the run crosses it now, and 756 spans a frame became 336.
- The rest is four narrower changes in the renderer. The per-column envelope is
  collected in locals rather than filed into a dict, a row of cells is a
  `bytearray` that one `translate` turns into glyphs, and both sample-to-dot
  mappings are written at the call site. The output is unchanged, checked cell
  by cell over 192 renders.
- At the logging host's 230x30 geometry a redraw of both panels costs about
  3.8 ms at a 15 s window, 7.1 ms at 60 s and 11.3 ms at 240 s. The earlier
  figures covered the renderer alone; these cover a whole `_refresh` in a
  running app, which is where the span conversion showed up.

## v0.3.0 | 19 Aug 2026

### Added

- One time range for both plots, moved with `-` and `+` through 15, 30, 60, 120
  and 240 seconds, default 60. History was a count of samples before, so one
  buffer held four minutes of a 1 Hz sonic and one minute of a 20 Hz analyzer,
  and the plots could not be read against each other. Both windows end at the
  same moment, so a stream that stops scrolls out instead of holding its last
  trace against the edge.
- `c` cycles four colour sets. `classic` is the default and the only one built
  from the 16 ANSI colours; on a terminal limited to those the others are
  approximated to the nearest of eight, which merges hues picked to be
  distinct. `okabe` is Okabe-Ito, readable with the common forms of colour
  blindness. `aurora` and `dusk` are quieter and louder.
- The header shows the version, so a screenshot says which build drew it.
- `--glyphs blocks` draws the plots with half blocks, for terminals whose font
  has no braille. The Linux console prompted it: its font holds at most 512
  glyphs and no braille, and the braille blank is U+2800 rather than a space,
  so every empty cell becomes a replacement box. It halves the resolution both
  ways, so it is never selected automatically.

### Changed

- Both plots step at the same moment. Each panel used to redraw when its own
  stream delivered, so the analyzer's 20 Hz records moved the lower plot every
  frame while the wind plot sat still between its once-a-second messages. They
  share one redraw decision now, taken when the window has scrolled by a whole
  dot column. At 240 s the pair costs less to draw than the lower plot alone
  used to.
- Frames are 10-20% cheaper to draw. The renderer assembles a frame as one
  string plus a list of spans instead of appending per run of same-styled
  cells, and one walk of a series yields its finite samples, its per-column
  envelope and its axis bounds. Unchanged output over 66 renders.
- The README's advice for plots that come out as boxes covered only the locale.
  A UTF-8 locale is necessary but not sufficient: on the console the font is
  the cause. Both fixes are there now, a braille console font through
  `console-braille` and `setfont`, or `--glyphs blocks`, which needs no font
  work. The first was verified on Ubuntu 24.04 with `Lat15-Fixed16.psf.gz` and
  `brl-16x8.psf`.
- The setup guide gained a step for finding the site's `record.toml`, which
  every step after it needs, and it names Ubuntu 24.04 alongside Debian 12 for
  the Python check. Ubuntu's system Python is externally managed, so pipx is
  the only route there.

### Fixed

- A mistyped `--gas-var` looked like a dead analyzer: records kept arriving,
  the status bar kept calling the stream live, and the plot stayed empty. The
  empty panel says so now and lists the names the site's `var_map` produces,
  which appear nowhere else on screen.
- The gas panel labelled every variable `umol mol-1`. That is right for a CO2
  mixing ratio and wrong for the cell temperature, pressure, flow rate and
  diagnostic codes the same analyzer carries. The unit comes from the parallel
  `variables` and `units` lists in `[datafile]` now, and the header prints none
  when the config cannot answer.
- The analyzer plot slid sideways from frame to frame while the wind plot grew
  smoothly. The cadence estimate was a moving average over arrival deltas, and
  the window turns that estimate into a slot count spread across the full
  width, so every wobble moved every sample. Jitter is the same few
  milliseconds at any rate, a large share of 50 ms and a negligible share of
  1 s, which is why only the lower plot showed it: up to 5.8% of the width
  between consecutive frames. The estimate is the average of a run of
  consecutive ordinary arrivals now, worst step 0.25%.
- The analyzer plot degenerated into holes on a host that could not render as
  fast as the stream arrives, and the header shrank to "last 2 s" instead of
  60. A slow frame blocks the event loop and the queued records then arrive
  back to back; those near-zero deltas dragged the cadence estimate down,
  ordinary arrivals afterwards looked like outages, and the `nan` slots they
  padded never fed the estimate back up. It is bounded below by the same
  `gap_factor` that bounds it above now, and warm-up measures the rate over two
  seconds rather than one delta.

## v0.2.1 | 18 Aug 2026

Documentation and packaging. Nothing in the program changed.

### Changed

- README and CLAUDE.md rewritten in plainer language. The commands, numbers and
  content are the same.
- CLAUDE.md is no longer in the source distribution. It documents rECorD's
  internals and is only useful when working on this repository.
- `record.toml` and `references/` are in `.gitignore`. A site's real
  `record.toml` holds its multicast groups and ports, and `references/` holds
  copies of the in-house `record`, `pygl` and `udpmulticast` sources. Neither
  was ever committed, and now neither can be by accident.

## v0.2.0 | 18 Aug 2026

### Added

- A logo: three wavy lines for the wind, amber dots for the gas, and the short
  name **ecvis**. SVG and PNG in `images/`; the README opens with it.

### Changed

- `--dump` also prints each analyzer record with the site's `var_map` names
  applied. Those are the names `--gas-var` accepts, and they never appear in
  the raw record.

### Fixed

- Offline install: the wheel alone was not enough, pip would still download
  textual and rich. The guide installs everything from a local folder now.
- The guide wrongly said sharing rECorD's ports needs the same account. Both
  programs set `SO_REUSEADDR`, so it works from any account.

## v0.1.0 | 17 Aug 2026

First release.

### Added

- Live display of the three wind components from `sonicshow` and one gas
  analyzer variable, as braille plots in the terminal.
- One header line per stream, with the current values and each component named
  in its plot colour. In a narrow window it drops the units first and the
  status text second rather than wrapping.
- `sw` and `TKE` in the wind header. rECorD sends every wind component as
  `mean(stdev)`, so both come for free. They cover one second each and come out
  too low, so they show how well the air is mixing but are not measurements.
- A status line with the time since each stream was last heard from, plus the
  buffer fill and sampling rate rECorD reports for each analyzer.
- Gaps in the plot when a stream falls silent. The x axis counts samples, so a
  silent stream keeps its place and the line does not close over the outage.
  The time between samples is learned from the stream rather than configured.
- Readers for both formats rECorD sends: the printed Python dictionary used by
  `sonicshow` and `analyzershow`, and the JSON used by the analyzer streams.
  Messages split across several datagrams are reassembled first.
- A multicast client that runs on Linux and on Windows. The one in
  `udpmulticast` is Linux only, so the socket setup is written from scratch
  here and tested over a real loopback connection.
- `--record-config`, which takes the analyzer addresses and the variable names
  out of the site's `record.toml`, so the display uses the site's own names.
- `--gas-var` to choose the variable to plot, `--analyzer` to pick one analyzer
  at a site with several, and `--interface` to name the interface to listen on.
- `--dump`, which prints the decoded records and starts no display. It shows
  whether the streams arrive, and what the analyzer calls its variables.
- `--demo`, which runs the display against a built-in simulator. The simulator
  sends real rECorD bytes, so demo data is read by the same code that reads a
  real site. `--seed`, `--speedup` and `--no-dropouts` adjust it.
- Keys: `q` quits, `space` pauses, `r` clears the plots.
- [CLAUDE.md](CLAUDE.md), which describes how rECorD works: the acquisition
  loop, the multicast transport, record alignment, the status bit fields, the
  layout of the TOA5 files, and the configuration format.

### Known limitations

- Not yet run against a real rECorD site. Testing so far covers the simulator
  and loopback multicast.
- The visualizer has to run on the logging host. rECorD sends with TTL 0 bound
  to loopback, so the streams never leave that machine.
- Wind data comes at 1 Hz only. rECorD sends no faster sonic stream, and
  reading the 20 Hz data files is not implemented.
- The `analyzershow` stream is ignored. Gas values come from the raw analyzer
  stream instead.
- One gas variable is plotted at a time.
