# Changelog

Notable changes to this project, newest first. Version numbers follow
[semantic versioning](https://semver.org/spec/v2.0.0.html).

## Unreleased

### Added

- `--glyphs blocks` draws the plots with half blocks instead of braille, for
  terminals whose font has no braille block. The case that prompted it is the
  Linux virtual console on the logging host: its default console font holds at
  most 512 glyphs and no braille at all, so a braille plot fills the screen with
  replacement boxes — including every blank cell, since the blank is U+2800
  rather than a space. Half blocks cost half the vertical and half the
  horizontal resolution, so the mode is never selected automatically; a
  terminal that cannot draw braille looks the same from here as one that can,
  and guessing wrong would quietly halve a display that was fine.

### Fixed

- The analyzer plot degenerated into mostly holes on a host that could not
  render as fast as the stream arrives, and the header shrank to "last 2 s"
  when it should have said 60. `SeriesBuffer` learned its cadence from arrival
  times, which describe the stream only while the consumer keeps up: a frame
  that outlasts one sampling interval blocks the event loop and the queued
  records then arrive back to back. Those near-zero deltas dragged the estimate
  down, which made every ordinary arrival afterwards look like an outage, which
  padded hundreds of `nan` slots and never fed the estimate back up. A one-way
  ratchet, and indistinguishable on screen from a failing analyzer. The
  estimate is now bounded from below by the same `gap_factor` that bounds it
  from above, and warm-up measures the overall rate over two seconds rather
  than trusting a single delta.

### Changed

- The README's advice for plots that come out as boxes covered only the locale.
  A UTF-8 locale is necessary but not sufficient: on the console the font is
  the cause, and no locale setting fixes it. It now covers both fixes: giving
  the console a braille font with `console-braille` and `setfont`, which keeps
  the full resolution, and `--glyphs blocks`, which needs no font work. The
  first was verified on Ubuntu 24.04 with `Lat15-Fixed16.psf.gz` and
  `brl-16x8.psf` on an 8x16 console.
- The setup guide gained a step for finding the site's `record.toml`. Every
  step after it needs that path, and the guide had assumed the reader knew it.
  rECorD takes it as its second argument, so the running process is the
  authoritative answer, ahead of both systemd and a filesystem search.
- The guide names Ubuntu 24.04 alongside Debian 12 for the Python version
  check, and notes that its system Python is externally managed, which makes
  pipx the only route rather than the tidy one.

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
