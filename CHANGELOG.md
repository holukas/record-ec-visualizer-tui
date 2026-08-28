# Changelog

Notable changes to this project, newest first. Version numbers follow
[semantic versioning](https://semver.org/spec/v2.0.0.html).

## v0.4.0 | 28 Aug 2026

### Added

- The Eddy Derby, a game played through the analyzer's own inlet, on `g`.
  Breathe at the inlet and the CO2 reading jumps from a few hundred
  umol mol-1 to thousands in a fraction of a second, which is the shortest
  route there is from "this box measures air" to "I can move that with my
  lungs". It is for open days and visitors, on the instrument that is already
  running.
- Each player takes a turn at the inlet, and an ASCII animal runs along their
  lane while they blow. The turn passes to the next lane once the air is clear
  of the breath, and the meter says `clearing` while it waits, since the score
  and the animal both stand still for that second.
  On the derby screen, `r` starts a new derby, `a` and `x` add and drop a lane,
  `n` passes a turn for someone who has stepped away, and `escape` goes back to
  the plots.
- A breath scores the area under its peak, in ppm s, over the excess above
  1000 umol mol-1. The highest reading is the obvious score and it does not
  work: an open-path head measures to about 3000, breath is more than ten times
  that, and everyone who leans close pins the sensor. An area still ranks blows
  after the reading saturates, because what is left to vary is how long you
  hold it there. It is also what the flux processing does, over one breath
  instead of half an hour.
- The finish line is 20,000 ppm s, about four or five hard breaths. It is the
  same every session, so it can go on a sign next to the mast. A breath scores
  less where the mast holds the inlet out of reach, which makes a longer derby;
  `--derby-goal` moves the line. `--derby-players` and `--breath-threshold` set
  the lanes and the level that counts.
- Lanes that cross on the same numbered breath are placed by their total score.
  P1 opens every round, so ranking by the moment of crossing handed P1 any
  derby that finished level. Fewer breaths still wins outright, and a place can
  change until the last player of the round has been scored.
- `b` breathes for you under `--demo`, where there is no inlet to breathe into.
  The simulator puts the breath on the wire as bytes and clips it at the
  analyzer's 3000 umol mol-1 range, so it reaches the game through the same
  decoder a real one would, saturation included.

### Changed

- The plots are not redrawn while the derby is up, so the game costs nothing on
  top of the display it replaces. The streams keep arriving while it is open,
  and the plots pick up where they are when it is closed.

## v0.3.1 | 20 Aug 2026

### Changed

- Frames are 27-34% cheaper to draw. Most of the saving is not in the drawing:
  Textual converts every colour span of a panel with `Style.from_rich_style` on
  each update, once per span and without a cache, which was 48% of a redraw. A
  trace weaving across a row leaves single coloured cells between blanks, and
  ending the colour run at every blank turned one row into dozens of spans. A
  cell with no dots displays nothing, so the run crosses it now, and 756 spans
  a frame became 336.
- The rest comes from four narrower changes. The per-column envelope is
  collected a column at a time, holding the extremes in locals, instead of
  tagging every sample with its column and filing it into a dict. A row of
  cells is a `bytearray` that one `translate` turns into glyphs, instead of a
  lookup per cell. The two mappings from a sample to a dot are written at the
  call site, and `_draw_segment` writes its own dots instead of calling
  `set_dot`; both run tens of thousands of times a frame, where the call costs
  more than the arithmetic inside it. The output is unchanged, checked over 192
  renders compared cell by cell on the glyph and the colour visible there,
  across both glyph sets, four geometries, twelve series shapes, and connected
  and bare traces.
- At the logging host's 230x30 geometry a redraw of both panels now costs about
  3.8 ms at a 15 s window, 7.1 ms at 60 s and 11.3 ms at 240 s. The figures
  recorded before covered the renderer alone. These cover a whole `_refresh`
  through a running app, which is where the span conversion showed up.

## v0.3.0 | 19 Aug 2026

### Added

- One time range for both plots, moved with `-` and `+` through 15, 30, 60, 120
  and 240 seconds, default 60. History was a count of samples before, so the
  same buffer held four minutes of a 1 Hz sonic and one minute of a 20 Hz
  analyzer, and the two plots could not be read against each other. The range
  starts short and grows with the data, and widening it later uncovers older
  data rather than blank space. Both windows end at the same moment, so a
  stream that stops scrolls out instead of holding its last trace against the
  edge.
- `c` cycles four colour sets. `classic` is the default and the only one built
  from the 16 ANSI colours; on a terminal limited to those the others are
  approximated to the nearest of eight, which merges hues picked to be
  distinct. `okabe` is Okabe-Ito, readable with the common forms of colour
  blindness. `aurora` and `dusk` are quieter and louder.
- The header shows the version, so a screenshot says which build drew it.
- `--glyphs blocks` draws the plots with half blocks, for terminals whose font
  has no braille. The Linux console prompted it: its font holds at most 512
  glyphs and no braille, and the braille blank is U+2800 rather than a space,
  so every empty cell becomes a replacement box. Half blocks halve the
  resolution both ways, so the mode is never automatic; nothing here can tell a
  console that cannot draw braille from one that can.

### Changed

- Both plots step at the same moment. Each panel used to redraw when its own
  stream delivered, so the analyzer's 20 Hz records moved the lower plot on
  every frame while the wind plot above it sat still between its once-a-second
  messages. They now share one redraw decision, taken when the window has
  scrolled by a whole dot column, so the rate follows the range on screen
  rather than the stream. At 240 s the pair costs less to draw than the lower
  plot alone used to.
- Frames are 10-20% cheaper to draw. The renderer assembles a frame as one
  string plus a list of spans, instead of appending once per run of
  same-styled cells, which a wiggly trace breaks into hundreds of. Scanning a
  series for its finite samples, its per-column envelope and its axis bounds is
  one walk now instead of three, so a dense series never builds the points the
  dot grid could not have shown. The output is unchanged, checked over 66
  renders covering both glyph sets, three geometries and eleven series shapes.
- The README's advice for plots that come out as boxes covered only the locale.
  A UTF-8 locale is necessary but not sufficient: on the console the font is
  the cause. Both fixes are there now, a braille console font through
  `console-braille` and `setfont`, which keeps the full resolution, or
  `--glyphs blocks`, which needs no font work. The first was verified on
  Ubuntu 24.04 with `Lat15-Fixed16.psf.gz` and `brl-16x8.psf` on an 8x16
  console.
- The setup guide gained a step for finding the site's `record.toml`, which
  every step after it needs. rECorD takes it as its second argument, so the
  running process answers it ahead of systemd or a filesystem search.
- The guide names Ubuntu 24.04 alongside Debian 12 for the Python version
  check, and notes that its system Python is externally managed, so pipx is the
  only route.

### Fixed

- A mistyped `--gas-var` looked like a dead analyzer: records kept arriving,
  the status bar kept calling the stream live, and the plot stayed empty
  because the name never matched. The empty panel now says so and lists the
  names the site's `var_map` actually produces, trimmed to the width it has.
  They appear nowhere else on screen, since the raw record carries the
  instrument's own, so finding them meant going back to `--dump`.
- The gas panel labelled every variable `umol mol-1`. That is right for a CO2
  mixing ratio and wrong for the cell temperature, pressure, flow rate and
  diagnostic codes the same analyzer carries, all of which `--gas-var` will
  happily plot. The unit now comes from the parallel `variables` and `units`
  lists in `[datafile]` of the site's `record.toml`, and the header prints no
  unit at all when the config cannot answer.
- The analyzer plot slid sideways from frame to frame while the wind plot above
  it grew smoothly. The cadence estimate was a moving average over arrival
  deltas, and the window turns that estimate into a slot count which the
  renderer spreads across the full width, so every wobble in it moved every
  sample. Scheduling jitter is the same few milliseconds whatever the rate,
  which makes it a large share of 50 ms and a negligible share of 1 s, and that
  is why only the lower plot showed it. Measured on a 20 Hz stream with 3 ms of
  jitter, the trace jumped by up to 5.8% of the plot's width between
  consecutive frames. The estimate is now the average of a run of consecutive
  ordinary arrivals, which spreads the jitter of two arrivals over two hundred
  of them: worst step 0.25%, with the 1 Hz panel unchanged at zero.
- The analyzer plot degenerated into holes on a host that could not render as
  fast as the stream arrives, and the header shrank to "last 2 s" instead of
  60. `SeriesBuffer` learned its cadence from arrival times, which describe the
  stream only while the consumer keeps up: a slow frame blocks the event loop,
  and the queued records then arrive back to back. Those near-zero deltas
  dragged the estimate down, ordinary arrivals afterwards looked like outages,
  and the hundreds of `nan` slots they padded never fed the estimate back up. A
  one-way ratchet, indistinguishable on screen from a failing analyzer. The
  estimate is now bounded below by the same `gap_factor` that bounds it above,
  and warm-up measures the rate over two seconds rather than one delta.

## v0.2.1 | 18 Aug 2026

Documentation and packaging. Nothing in the program changed.

### Changed

- README and CLAUDE.md rewritten in plainer language. The commands, numbers and
  content are the same.
- CLAUDE.md is no longer included in the source distribution. It documents
  rECorD's internals and is only useful when working on this repository.
- `record.toml` and `references/` are now in `.gitignore`. A site's real
  `record.toml` holds its multicast groups and ports, and `references/` holds
  the copies of the in-house `record`, `pygl` and `udpmulticast` sources.
  Neither was ever committed, and now neither can be by accident.

## v0.2.0 | 18 Aug 2026

### Added

- A logo: three wavy lines for the wind, amber dots for the gas, and the short
  name **ecvis**. SVG and PNG files in `images/`; the README opens with it.

### Changed

- `--dump` also prints each analyzer record with the site's `var_map` names
  applied. Those are the names `--gas-var` accepts, and they never appear in
  the raw record.

### Fixed

- Offline install: the wheel alone was not enough, pip would still download
  textual and rich. The guide now installs everything from a local folder.
- The guide wrongly said sharing rECorD's ports needs the same account. Both
  programs set `SO_REUSEADDR`, so sharing works from any account.

## v0.1.0 | 17 Aug 2026

First release.

### Added

- Live display of the three wind components from `sonicshow` and one gas
  analyzer variable, drawn as braille plots in the terminal.
- One header line per stream. It shows the current values and names each
  component in its plot colour. In a narrow window it drops the units first and
  the status text second, rather than wrapping onto a second line.
- `sw` and `TKE` in the wind header. rECorD already sends every wind component
  as `mean(stdev)`, so both come for free. They cover one second each and come
  out too low, so they show how well the air is mixing but are not measurements.
- A status line with the time since each stream was last heard from, plus the
  buffer fill and sampling rate rECorD reports for each analyzer.
- Gaps in the plot when a stream falls silent. The x axis counts samples, so a
  silent stream keeps its place and the line does not close over the outage. The
  time between samples is learned from the stream instead of being configured.
- Readers for both formats rECorD sends: the printed Python dictionary used by
  `sonicshow` and `analyzershow`, and the JSON used by the analyzer streams.
  Messages split across several datagrams are put back together first.
- A multicast client that runs on Linux and on Windows. The one in
  `udpmulticast` is Linux only, so the socket setup is written from scratch here
  and tested over a real loopback connection.
- `--record-config`, which takes the analyzer addresses and the variable names
  out of the site's `record.toml`, so the display uses the site's own names.
- `--gas-var` to choose the variable to plot, `--analyzer` to pick one analyzer
  at a site that has several, and `--interface` to name the interface to listen
  on.
- `--dump`, which prints the decoded records and starts no display. It shows
  whether the streams arrive, and what the analyzer calls its variables.
- `--demo`, which runs the display against a built-in simulator. The simulator
  sends real rECorD bytes, so demo data is read by the same code that reads a
  real site. `--seed`, `--speedup` and `--no-dropouts` adjust it.
- Keys: `q` quits, `space` pauses, `r` clears the plots.
- [CLAUDE.md](CLAUDE.md), which describes how rECorD works: the acquisition
  loop, the multicast transport, how records are aligned, the status bit fields,
  the layout of the TOA5 files, and the configuration format.

### Known limitations

- Not yet run against a real rECorD site. Testing so far covers the simulator
  and loopback multicast.
- The visualizer has to run on the logging host. rECorD sends with TTL 0 bound
  to loopback, so the streams never leave that machine.
- Wind data comes at 1 Hz only. rECorD sends no faster sonic stream, and reading
  the 20 Hz data files is not implemented.
- The `analyzershow` stream is ignored. Gas values come from the raw analyzer
  stream instead.
- One gas variable is plotted at a time.
