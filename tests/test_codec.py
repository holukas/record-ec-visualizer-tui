import math

import pytest

from record_ec_visualizer_tui.codec import (
    DecodeError,
    LineAssembler,
    VariableMap,
    parse_buffer_fill,
    parse_ga_message,
    parse_mean_stdev,
    parse_show_message,
)


class TestLineAssembler:
    def test_splits_on_newline(self):
        assembler = LineAssembler()
        assert assembler.push(b"one\ntwo\n") == [b"one", b"two"]

    def test_holds_back_incomplete_line(self):
        assembler = LineAssembler()
        assert assembler.push(b"par") == []
        assert assembler.push(b"tial\n") == [b"partial"]

    def test_message_split_across_datagrams(self):
        # rECorD reads its own sockets in 1024 byte chunks for exactly this reason.
        assembler = LineAssembler()
        payload = b'{"Data": {"CO2": 421.0}}'
        assert assembler.push(payload[:10]) == []
        assert assembler.push(payload[10:] + b"\n") == [payload]

    def test_ignores_blank_lines(self):
        assert LineAssembler().push(b"\n\na\n") == [b"a"]


class TestShowMessages:
    def test_parses_python_dict_repr_not_json(self):
        # The payload uses single quotes: json.loads would reject it.
        payload = b"{'Wc1': '1.23(0.45)', 'li7500rs_freq': 19.9}"
        assert parse_show_message(payload) == {"Wc1": "1.23(0.45)", "li7500rs_freq": 19.9}

    def test_rejects_json_object_with_double_quotes_only_if_not_literal(self):
        # A double-quoted dict happens to be a valid Python literal too.
        assert parse_show_message(b'{"a": 1}') == {"a": 1}

    def test_rejects_non_dict(self):
        with pytest.raises(DecodeError):
            parse_show_message(b"[1, 2, 3]")

    def test_rejects_garbage(self):
        with pytest.raises(DecodeError):
            parse_show_message(b"not a literal at all {{{")


class TestGaMessages:
    def test_parses_nested_json(self):
        record = parse_ga_message(b'{"Data": {"CO2": 421.5}, "Auxiliary": {"BufferSize": 2}}')
        assert record["Data"]["CO2"] == 421.5

    def test_rejects_python_repr(self):
        with pytest.raises(DecodeError):
            parse_ga_message(b"{'Data': {'CO2': 421.5}}")


class TestMeanStdev:
    def test_parses_pair(self):
        assert parse_mean_stdev("1.23(0.45)") == (1.23, 0.45)

    def test_parses_negative_mean(self):
        assert parse_mean_stdev("-0.12(0.33)") == (-0.12, 0.33)

    def test_handles_nan_stdev(self):
        # A one-record interval raises StatisticsError upstream and formats as "nan".
        mean, stdev = parse_mean_stdev("1.00(nan)")
        assert mean == 1.0
        assert math.isnan(stdev)

    def test_bare_number_becomes_mean_with_nan_stdev(self):
        mean, stdev = parse_mean_stdev(19.9)
        assert mean == 19.9
        assert math.isnan(stdev)

    def test_rejects_buffer_string(self):
        with pytest.raises(DecodeError):
            parse_mean_stdev("198/200")


class TestBufferFill:
    def test_parses(self):
        assert parse_buffer_fill("198/200") == (198, 200)

    def test_rejects_mean_stdev(self):
        with pytest.raises(DecodeError):
            parse_buffer_fill("1.23(0.45)")


class TestVariableMap:
    def test_flat_map_like_the_sonic(self):
        var_map = VariableMap({"Wc1": "U", "Wc2": "V", "Wc3": "W"})
        assert var_map.apply({"Wc1": 1.0, "Wc2": 2.0, "Wc3": 3.0}) == {"U": 1.0, "V": 2.0, "W": 3.0}

    def test_nested_map_like_an_analyzer(self):
        # var_map.Data.CO2D = "CO2_CONC" means raw["Data"]["CO2D"] is CO2_CONC.
        var_map = VariableMap({"Data": {"CO2D": "CO2_CONC", "Temp": "T_CELL"}})
        raw = {"Data": {"CO2D": 17.2, "Temp": 24.5}, "Auxiliary": {"BufferSize": 0}}
        assert var_map.apply(raw) == {"CO2_CONC": 17.2, "T_CELL": 24.5}

    def test_missing_keys_are_skipped_not_fatal(self):
        var_map = VariableMap({"Data": {"CO2D": "CO2_CONC", "Absent": "NOPE"}})
        assert var_map.apply({"Data": {"CO2D": 1.0}}) == {"CO2_CONC": 1.0}

    def test_missing_path_is_skipped(self):
        var_map = VariableMap({"Data": {"CO2D": "CO2_CONC"}})
        assert var_map.apply({"Other": {}}) == {}

    def test_file_vars_collected(self):
        var_map = VariableMap({"Data": {"CO2D": "CO2_CONC"}, "StaA": "SA_DIAG_TYPE"})
        assert sorted(var_map.file_vars) == ["CO2_CONC", "SA_DIAG_TYPE"]

    def test_file_var_for_raw_key(self):
        assert VariableMap({"Wc1": "U"}).file_var_for("Wc1") == "U"
        assert VariableMap({"Wc1": "U"}).file_var_for("Wc9") is None

    def test_empty_map_is_harmless(self):
        assert VariableMap().apply({"anything": 1}) == {}
