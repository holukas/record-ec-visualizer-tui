# Changelog

Notable changes to this project, newest first. Version numbers follow
[semantic versioning](https://semver.org/spec/v2.0.0.html).

## v0.2.0 | 18 Aug 2026

### Added

- A logo. The icon shows what the display shows: three wavy lines for the wind
  components, and a row of amber dots for the gas records underneath. Next to it
  the short name **ecvis**, with the dot of the `i` in amber. All files are in
  `images/`: SVG for light, dark and single-color use, plus PNG copies. The
  README now opens with it.

### Changed

- `--dump` prints each gas analyzer record twice: once as it arrives, and once
  with the site's `var_map` names applied. The name passed to `--gas-var` has to
  be one of the mapped names, and those never appear in the raw record. Before
  this change the dump could only show names that would not work.

### Fixed

- The install guide said that copying the wheel file was enough for a machine
  without internet. It was not: pip would still try to download textual and
  rich. The guide now downloads the dependencies too and installs everything
  from a local folder.
- The guide claimed the visualizer can share rECorD's ports only when both
  programs run under the same account. That was wrong. Both programs set the
  socket option that allows sharing (`SO_REUSEADDR`), and Linux does not care
  which user owns them. Running as the same user is still recommended, but the
  "address already in use" error the guide predicted does not happen.

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
