"""The demo has to be asked for.

On the logging host the bare command means "show me the site". Anything that
would let it start the simulator unasked — or start a live session while
quietly ignoring a mistyped address — is a bug worth a test.
"""
import asyncio

import pytest

from record_ec_visualizer_tui.__main__ import main


def _exit_message(capsys) -> str:
    return capsys.readouterr().err


def test_bare_invocation_does_not_start_the_demo(capsys):
    with pytest.raises(SystemExit) as excinfo:
        main([])
    assert excinfo.value.code == 2
    assert "--demo" in _exit_message(capsys)


def test_demo_flag_selects_the_simulator():
    # --dump would run forever, so this only checks that argument handling gets
    # as far as building a source rather than erroring on missing addresses.
    from record_ec_visualizer_tui.__main__ import _build_simulated, build_parser

    args = build_parser().parse_args(["--demo"])
    lines, state, subtitle = _build_simulated(args)
    assert "simulated" in subtitle
    assert state.gas_var == "CO2"
    asyncio.run(lines.aclose())  # never started; close it rather than leave it to the GC


@pytest.mark.parametrize(
    "argv, expected",
    [
        (["--demo", "--sonicshow-group", "224.0.0.1", "--sonicshow-port", "5000"], "--sonicshow-group"),
        (["--demo", "--record-config", "record.toml"], "--record-config"),
        (["--speedup", "5", "--record-config", "record.toml"], "--speedup"),
        (["--no-dropouts", "--record-config", "record.toml"], "--no-dropouts"),
    ],
)
def test_options_of_the_unselected_source_are_rejected(argv, expected, capsys):
    with pytest.raises(SystemExit) as excinfo:
        main(argv)
    assert excinfo.value.code == 2
    assert expected in _exit_message(capsys)
