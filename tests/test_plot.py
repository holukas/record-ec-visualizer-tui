import math

from rich.text import Text

from record_ec_visualizer_tui.tui.plot import BRAILLE_BASE, render_braille_plot


def _braille_only(text: Text) -> str:
    return "".join(ch for ch in text.plain if ord(ch) >= BRAILLE_BASE)


class TestRenderBraillePlot:
    def test_returns_text(self):
        assert isinstance(render_braille_plot([{"y": [1, 2, 3]}]), Text)

    def test_empty_series_shows_message(self):
        plot = render_braille_plot([], empty_message="nothing yet")
        assert plot.plain == "nothing yet"

    def test_all_missing_values_shows_message(self):
        plot = render_braille_plot([{"y": [None, math.nan]}], empty_message="nothing yet")
        assert plot.plain == "nothing yet"

    def test_grid_has_requested_height(self):
        plot = render_braille_plot([{"y": list(range(20))}], width=20, height=5)
        # One line per character row, plus nothing else.
        assert len(plot.plain.split("\n")) == 5

    def test_draws_some_dots(self):
        plot = render_braille_plot([{"y": [0, 1, 0, 1]}], width=20, height=4)
        assert any(ord(ch) > BRAILLE_BASE for ch in _braille_only(plot))

    def test_flat_series_does_not_divide_by_zero(self):
        plot = render_braille_plot([{"y": [5.0] * 10}], width=20, height=4)
        assert any(ord(ch) > BRAILLE_BASE for ch in _braille_only(plot))

    def test_single_point(self):
        plot = render_braille_plot([{"y": [1.0]}], width=20, height=4)
        assert any(ord(ch) > BRAILLE_BASE for ch in _braille_only(plot))

    def test_axis_labels_show_range(self):
        plot = render_braille_plot([{"y": [0.0, 10.0]}], width=20, height=4)
        assert "10.00" in plot.plain
        assert "0.00" in plot.plain

    def test_explicit_bounds_are_respected(self):
        plot = render_braille_plot([{"y": [1.0, 2.0]}], y_min=-5, y_max=5, width=20, height=4)
        assert "5.00" in plot.plain
        assert "-5.00" in plot.plain

    def test_multiple_series_render_together(self):
        plot = render_braille_plot(
            [{"y": [0, 1, 2], "color": "red"}, {"y": [2, 1, 0], "color": "blue"}],
            width=20,
            height=4,
        )
        assert any(ord(ch) > BRAILLE_BASE for ch in _braille_only(plot))

    def test_gap_is_not_bridged(self):
        # A dropout must read as a gap, not as a line drawn straight across it.
        with_gap = render_braille_plot(
            [{"y": [0.0] + [None] * 20 + [1.0]}], width=30, height=4, max_gap=1
        )
        bridged = render_braille_plot(
            [{"y": [0.0] + [None] * 20 + [1.0]}], width=30, height=4, max_gap=100
        )
        dots_with_gap = sum(ord(ch) - BRAILLE_BASE != 0 for ch in _braille_only(with_gap))
        dots_bridged = sum(ord(ch) - BRAILLE_BASE != 0 for ch in _braille_only(bridged))
        assert dots_with_gap < dots_bridged

    def test_narrow_width_is_clamped_not_crashed(self):
        assert isinstance(render_braille_plot([{"y": [1, 2]}], width=1, height=1), Text)

    def test_non_numeric_values_are_ignored(self):
        plot = render_braille_plot([{"y": ["nope", None, 1.0, 2.0]}], width=20, height=4)
        assert isinstance(plot, Text)
