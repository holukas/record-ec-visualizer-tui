"""Print what rECorD's streams look like on the wire, and what they decode to.

No TUI — this is the one to run when you want to *see* the data rather than
watch it. It is also the thing to diff against a real installation: run

    record-ec-visualizer-tui --source multicast ... --dump

on the logging host and the decoded records should look like these.

Run it::

    python examples/demo_wire_format.py
"""
from __future__ import annotations

from record_ec_visualizer_tui.codec import (
    VariableMap,
    parse_ga_message,
    parse_show_message,
)
from record_ec_visualizer_tui.simulator import (
    SONICSHOW_STREAM,
    RecordSimulator,
    SimulationConfig,
)

#: 20 Hz, so this is 3 seconds of acquisition.
TICKS = 60


def main() -> None:
    config = SimulationConfig()
    simulator = RecordSimulator(config)
    gas_map = VariableMap(config.var_map)
    sonic_map = VariableMap(config.sonic_var_map)

    shown_gas = 0
    for stream, payload in simulator.iter_lines(TICKS):
        if stream == SONICSHOW_STREAM:
            print()
            print("=" * 78)
            print(f"stream: {stream}   (1 Hz)")
            print("-" * 78)
            print("raw bytes  :", payload)
            record = parse_show_message(payload)
            print("decoded    :", record)
            print()
            print("  Note the single quotes: this is a Python dict repr, so it is NOT")
            print("  valid JSON. It has to go through ast.literal_eval.")
            print("  Wind components arrive pre-formatted as 'mean(stdev)' text.")
            print("  Applying the sonic var_map renames the raw keys:")
            for raw_key in ("Wc1", "Wc2", "Wc3"):
                if raw_key in record:
                    print(f"    {raw_key} -> {sonic_map.file_var_for(raw_key)}  = {record[raw_key]}")
            print("=" * 78)
            continue

        if shown_gas >= 2:
            continue
        shown_gas += 1
        print()
        print("=" * 78)
        print(f"stream: {stream}   (~20 Hz)")
        print("-" * 78)
        print("raw bytes  :", payload)
        record = parse_ga_message(payload)
        print("decoded    :", record)
        print()
        print("  Double quotes: this one really is JSON.")
        print("  Nested, so the site's var_map resolves a path to a variable name:")
        for file_var, value in sorted(gas_map.apply(record).items()):
            print(f"    {file_var:<12} = {value}")
        print("=" * 78)


if __name__ == "__main__":
    main()
