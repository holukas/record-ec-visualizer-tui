"""Entry point: ``record-ec-visualizer-tui`` / ``python -m record_ec_visualizer_tui``.

Two sources, one application:

live multicast (the default)
    Subscribes to real rECorD multicast streams. Addresses are required
    arguments — there are deliberately no defaults in this package. rECorD's
    own defaults live in its source (``sonicshow_ip`` / ``sonicshow_port``) and
    the analyzer addresses live in the site's ``record.toml``, which
    ``--record-config`` will read for you.

``--demo``
    Generates rECorD-shaped stream lines locally. Nothing else is needed, and
    the data travels the same decode path as a live site. It has to be asked
    for: on the logging host the bare command should mean "show me the site",
    not "show me invented numbers that look just like it".

Remember that rECorD publishes these streams with TTL 0 bound to loopback, so
unless the site has been reconfigured this has to run on the logging host.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
import tomllib
from collections.abc import AsyncIterator
from pathlib import Path

from record_ec_visualizer_tui import __version__
from record_ec_visualizer_tui.codec import DecodeError, VariableMap, parse_ga_message, parse_show_message
from record_ec_visualizer_tui.model import LiveState
from record_ec_visualizer_tui.simulator import SONICSHOW_STREAM, RecordSimulator, SimulationConfig
from record_ec_visualizer_tui.sources import (
    MulticastEndpoint,
    endpoints_from_record_config,
    multicast_lines,
    simulated_lines,
)
from record_ec_visualizer_tui.tui.app import VisualizerApp
from record_ec_visualizer_tui.tui.plot import GLYPH_SETS


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="record-ec-visualizer-tui",
        description="Real-time terminal visualizer for rECorD eddy covariance data.",
    )
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument(
        "--demo",
        action="store_true",
        help="feed the display from the built-in simulator instead of a live site",
    )
    parser.add_argument(
        "--dump",
        action="store_true",
        help="print decoded records instead of starting the TUI (for checking a live connection)",
    )
    parser.add_argument(
        "--gas-var",
        default="CO2",
        help="site variable to plot from the analyzer stream (default: CO2, a mixing ratio)",
    )
    parser.add_argument(
        "--glyphs",
        choices=sorted(GLYPH_SETS),
        default="braille",
        help=(
            "characters the plots are drawn from (default: braille). Use 'blocks' "
            "on a terminal whose font has no braille, such as the Linux virtual "
            "console, where braille plots come out as rows of boxes; it costs half "
            "the resolution, so it is never selected automatically"
        ),
    )

    simulated = parser.add_argument_group("demo source (--demo)")
    simulated.add_argument("--seed", type=int, default=0, help="RNG seed (default: 0)")
    simulated.add_argument(
        "--speedup",
        type=float,
        default=1.0,
        help=(
            "run the simulation faster than real time (default: 1.0). Note that "
            "staleness is measured against the wall clock, so simulated dropouts "
            "stop registering as stale above roughly 5x"
        ),
    )
    simulated.add_argument(
        "--no-dropouts",
        action="store_true",
        help="do not simulate periodic analyzer dropouts",
    )

    live = parser.add_argument_group("live multicast source (the default)")
    live.add_argument("--sonicshow-group", help="multicast group of rECorD's sonicshow stream")
    live.add_argument("--sonicshow-port", type=int, help="UDP port of rECorD's sonicshow stream")
    live.add_argument(
        "--record-config",
        type=Path,
        help="path to the site's rECorD record.toml, read for analyzer addresses and var_map",
    )
    live.add_argument(
        "--analyzer",
        action="append",
        dest="analyzers",
        help="limit to this analyzer from record.toml (repeatable; default: all)",
    )
    live.add_argument("--interface", default="0.0.0.0", help="local interface to join on")
    return parser


def _units_for(config: dict, variable: str) -> str:
    """The site's own unit for a data-file variable, or nothing.

    ``[datafile]`` carries ``variables`` and ``units`` as parallel lists, which
    is the only place a stream says what its numbers mean: an analyzer record
    is bare JSON and the ``var_map`` renames without describing. Returning ""
    when the config cannot answer is the point — the header then prints no
    unit at all, which is honest, where a default would have been a confident
    label on a variable that may well be a temperature or a pressure.
    """
    datafile = config.get("datafile") or {}
    names = datafile.get("variables")
    units = datafile.get("units")
    if not isinstance(names, list) or not isinstance(units, list):
        return ""
    try:
        unit = units[names.index(variable)]
    except (ValueError, IndexError):
        return ""
    return unit if isinstance(unit, str) else ""


def _load_record_config(path: Path) -> dict:
    with path.open("rb") as handle:
        return tomllib.load(handle)


def _build_simulated(args: argparse.Namespace) -> tuple[AsyncIterator[tuple[str, bytes]], LiveState, str]:
    config = SimulationConfig(seed=args.seed)
    if args.no_dropouts:
        config.dropout_every_s = 0.0
    simulator = RecordSimulator(config)
    state = LiveState(
        gas_var=args.gas_var,
        gas_units=config.units.get(args.gas_var, ""),
        sonic_map=VariableMap(config.sonic_var_map),
        gas_map=VariableMap(config.var_map),
    )
    subtitle = f"simulated · {config.ga_name}"
    if args.speedup != 1.0:
        subtitle += f" · {args.speedup:g}x"
    return simulated_lines(simulator, speedup=args.speedup), state, subtitle


def _build_multicast(
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
) -> tuple[AsyncIterator[tuple[str, bytes]], LiveState, str]:
    endpoints: list[MulticastEndpoint] = []
    sonic_map = VariableMap()
    gas_map = VariableMap()
    config: dict = {}

    if bool(args.sonicshow_group) != bool(args.sonicshow_port):
        parser.error("--sonicshow-group and --sonicshow-port must be given together")
    if args.sonicshow_group:
        endpoints.append(
            MulticastEndpoint(
                name=SONICSHOW_STREAM,
                group=args.sonicshow_group,
                port=args.sonicshow_port,
                interface=args.interface,
            )
        )

    if args.record_config:
        config = _load_record_config(args.record_config)
        endpoints.extend(endpoints_from_record_config(config, args.analyzers, args.interface))
        sonic_section = config.get("sonic") or {}
        if isinstance(sonic_section.get("var_map"), dict):
            sonic_map = VariableMap(sonic_section["var_map"])
        for name, section in (config.get("gasanalyzers") or {}).items():
            if args.analyzers and name not in args.analyzers:
                continue
            if isinstance(section, dict) and isinstance(section.get("var_map"), dict):
                gas_map = VariableMap(section["var_map"])
                break

    if not endpoints:
        parser.error(
            "no streams to subscribe to: pass --sonicshow-group/--sonicshow-port "
            "and/or --record-config, or --demo to run against the simulator"
        )

    state = LiveState(
        gas_var=args.gas_var,
        gas_units=_units_for(config, args.gas_var),
        sonic_map=sonic_map,
        gas_map=gas_map,
    )
    subtitle = "live · " + ", ".join(endpoint.name for endpoint in endpoints)
    return multicast_lines(endpoints), state, subtitle


async def _dump(lines: AsyncIterator[tuple[str, bytes]], state: LiveState) -> None:
    """Print decoded records, the quickest way to confirm a live connection.

    Analyzer records are printed twice: as decoded from the wire, and after the
    site's ``var_map``. ``--gas-var`` has to match a name from the second form —
    the raw record never contains it — which is what earns the mapped line its
    place here.
    """
    async for name, payload in lines:
        try:
            record = parse_show_message(payload) if name == SONICSHOW_STREAM else parse_ga_message(payload)
        except DecodeError as exc:
            print(f"[{name}] decode error: {exc}", file=sys.stderr)
            continue
        print(f"[{name}] {record}")
        if name != SONICSHOW_STREAM:
            mapped = state.gas_map.apply(record)
            if mapped:
                print(f"[{name}] after var_map: {mapped}")


def _reject_crossed_options(args: argparse.Namespace, parser: argparse.ArgumentParser) -> None:
    """Refuse options belonging to the source that was not selected.

    Silently ignoring them would be the worse failure: an operator who asked for
    a live site and mistyped an address deserves to hear about it rather than
    watch a plausible-looking simulation.
    """
    demo_only = ["--seed", "--speedup", "--no-dropouts"]
    live_only = ["--sonicshow-group", "--sonicshow-port", "--record-config", "--analyzer", "--interface"]
    owner, options = ("the live multicast source", live_only) if args.demo else ("--demo", demo_only)

    given = {
        "--seed": args.seed != 0,
        "--speedup": args.speedup != 1.0,
        "--no-dropouts": args.no_dropouts,
        "--sonicshow-group": args.sonicshow_group is not None,
        "--sonicshow-port": args.sonicshow_port is not None,
        "--record-config": args.record_config is not None,
        "--analyzer": bool(args.analyzers),
        "--interface": args.interface != "0.0.0.0",
    }
    offenders = [option for option in options if given[option]]
    if offenders:
        parser.error(f"{', '.join(offenders)} only applies to {owner}")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    _reject_crossed_options(args, parser)

    if args.demo:
        lines, state, subtitle = _build_simulated(args)
    else:
        lines, state, subtitle = _build_multicast(args, parser)

    if args.dump:
        try:
            asyncio.run(_dump(lines, state))
        except KeyboardInterrupt:
            pass
        return 0

    VisualizerApp(lines, state, subtitle=subtitle, glyphs=GLYPH_SETS[args.glyphs]).run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
