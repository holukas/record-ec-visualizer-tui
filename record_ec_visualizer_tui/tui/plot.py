"""Braille-cell line plots rendered into a ``rich.text.Text``.

Same approach and public shape as bico's ``bico/tui/plot.py``: a plain function
that turns a list of series into styled text, with no widget or library beyond
rich. Each terminal cell carries 2x4 braille dots, so a plot is four times
taller and twice wider in resolution than its character grid.

Braille dot-to-bit layout inside one cell::

    (0,0) (1,0)      bit 0   bit 3
    (0,1) (1,1)      bit 1   bit 4
    (0,2) (1,2)      bit 2   bit 5
    (0,3) (1,3)      bit 6   bit 7
"""
from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any, Callable

from rich.text import Text

BRAILLE_BASE = 0x2800
_DOT_BITS = ((0, 1, 2, 6), (3, 4, 5, 7))

#: Bit masks flattened to ``(dot_x & 1) * 4 + (dot_y & 3)``. Setting a dot is
#: the innermost operation in the renderer — several thousand times per frame —
#: so it indexes this table instead of calling a helper and shifting.
_DOT_MASKS = tuple(1 << _DOT_BITS[x][y] for x in (0, 1) for y in (0, 1, 2, 3))

#: Every braille cell, precomputed. Cheaper than chr() per cell per frame.
_BRAILLE_CELLS = tuple(chr(BRAILLE_BASE + value) for value in range(256))


def _fmt(value: float) -> str:
    """Compact axis label."""
    if math.isnan(value):
        return "nan"
    magnitude = abs(value)
    if magnitude != 0 and (magnitude < 0.01 or magnitude >= 100_000):
        return f"{value:.1e}"
    if magnitude >= 1000:
        return f"{value:,.0f}"
    if magnitude >= 100:
        return f"{value:.1f}"
    return f"{value:.2f}"


def _finite_points(ys: Sequence[Any]) -> list[tuple[int, float]]:
    """Index/value pairs for the entries that are real numbers.

    Series coming from :class:`~record_ec_visualizer_tui.model.SeriesBuffer` are
    always floats, so that case gets an exact-type fast path; anything else
    still goes through the general checks.
    """
    points: list[tuple[int, float]] = []
    append = points.append
    isfinite = math.isfinite
    for index, value in enumerate(ys):
        if type(value) is float:
            if isfinite(value):
                append((index, value))
            continue
        if value is None or isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        as_float = float(value)
        if isfinite(as_float):
            append((index, as_float))
    return points


def _decimate(
    points: list[tuple[int, float]],
    count: int,
    dot_cols: int,
) -> tuple[list[tuple[int, float]], int]:
    """Reduce dense data to the extremes visible in each dot column.

    A 20 Hz stream easily carries several samples per dot column, and drawing
    every one of them is wasted work: the column can only show the range they
    span. Keeping the minimum and maximum per column draws the identical
    picture — the vertical smear of a dense trace *is* its min/max envelope —
    for a fraction of the segments. This matters because the visualizer is
    expected to run on the logging host, where rECorD's own 20 Hz loop is the
    thing that must not be starved of CPU.

    Returns the reduced points (still in index order) and the sample stride
    they now represent, so gap detection can be scaled accordingly.
    """
    stride = max(1, -(-count // dot_cols))  # ceil
    extremes: dict[int, tuple[tuple[int, float], tuple[int, float]]] = {}
    for point in points:
        column = point[0] // stride
        current = extremes.get(column)
        if current is None:
            extremes[column] = (point, point)
        else:
            low, high = current
            extremes[column] = (
                point if point[1] < low[1] else low,
                point if point[1] > high[1] else high,
            )

    reduced: list[tuple[int, float]] = []
    for column in sorted(extremes):
        low, high = extremes[column]
        reduced.extend((low, high) if low[0] <= high[0] else (high, low))
        if low is high:
            reduced.pop()
    return reduced, stride


def _draw_segment(
    x0: int,
    y0: int,
    x1: int,
    y1: int,
    set_dot: Callable[[int, int], None],
) -> None:
    """Bresenham line between two dots."""
    dx = abs(x1 - x0)
    dy = -abs(y1 - y0)
    step_x = 1 if x0 < x1 else -1
    step_y = 1 if y0 < y1 else -1
    error = dx + dy
    x, y = x0, y0
    while True:
        set_dot(x, y)
        if x == x1 and y == y1:
            return
        doubled = 2 * error
        if doubled >= dy:
            error += dy
            x += step_x
        if doubled <= dx:
            error += dx
            y += step_y


def render_braille_plot(
    series: Sequence[dict[str, Any]],
    *,
    width: int = 60,
    height: int = 8,
    axis_style: str = "grey50",
    connect: bool = True,
    max_gap: int = 1,
    y_min: float | None = None,
    y_max: float | None = None,
    label_width: int = 9,
    empty_message: str = "waiting for data",
) -> Text:
    """Render ``series`` as a braille line plot.

    :param series: one dict per line, with ``y`` (a sequence of values, where
        ``None``/``nan`` means "no sample") and optional ``color``.
    :param connect: join consecutive samples into a line rather than plotting
        bare dots.
    :param max_gap: how many missing samples a connecting line may bridge.
        Keeping this at 1 means dropouts show as gaps instead of being drawn
        across, which matters when the gap *is* the thing worth seeing.
    :param y_min: fix the lower bound of the axis instead of deriving it.
    :param y_max: fix the upper bound of the axis instead of deriving it.
    """
    width = max(8, int(width))
    height = max(1, int(height))
    dot_cols = width * 2
    dot_rows = height * 4

    all_points = [(spec, _finite_points(spec.get("y") or ())) for spec in series]
    values = [value for _, points in all_points for _, value in points]
    if not values:
        return Text(empty_message, style=axis_style)

    low = min(values) if y_min is None else float(y_min)
    high = max(values) if y_max is None else float(y_max)
    if not math.isfinite(low) or not math.isfinite(high):  # pragma: no cover - defensive
        return Text(empty_message, style=axis_style)
    if high - low < 1e-12:
        # A flat series still deserves a sensible axis rather than a divide by zero.
        pad = max(abs(high) * 0.01, 0.5)
        low, high = low - pad, high + pad

    bits = [[0] * width for _ in range(height)]
    colors: list[list[str | None]] = [[None] * width for _ in range(height)]

    for spec, points in all_points:
        if not points:
            continue
        color = spec.get("color")
        ys = spec.get("y") or ()
        count = len(ys)

        # Denser than the grid can show: collapse to the per-column envelope.
        # gap_limit rises with the stride so a dropout still reads as a gap.
        stride = 1
        if count > dot_cols:
            points, stride = _decimate(points, count, dot_cols)
        gap_limit = max_gap * stride

        def to_dot_x(index: int, count: int = count) -> int:
            if count <= 1:
                return dot_cols - 1
            return int(round(index * (dot_cols - 1) / (count - 1)))

        def to_dot_y(value: float) -> int:
            scaled = (high - value) / (high - low)
            return min(dot_rows - 1, max(0, int(round(scaled * (dot_rows - 1)))))

        def set_dot(dot_x: int, dot_y: int, color: str | None = color) -> None:
            if not (0 <= dot_x < dot_cols and 0 <= dot_y < dot_rows):
                return
            cell_x, cell_y = dot_x >> 1, dot_y >> 2
            bits[cell_y][cell_x] |= _DOT_MASKS[(dot_x & 1) * 4 + (dot_y & 3)]
            if color is not None:
                colors[cell_y][cell_x] = color

        previous: tuple[int, int, int] | None = None
        for index, value in points:
            dot_x, dot_y = to_dot_x(index), to_dot_y(value)
            if connect and previous is not None:
                prev_index, prev_x, prev_y = previous
                if index - prev_index <= gap_limit:
                    _draw_segment(prev_x, prev_y, dot_x, dot_y, set_dot)
                else:
                    set_dot(dot_x, dot_y)
            else:
                set_dot(dot_x, dot_y)
            previous = (index, dot_x, dot_y)

    out = Text()
    for row in range(height):
        if row == 0:
            label = _fmt(high)
        elif row == height - 1:
            label = _fmt(low)
        else:
            label = ""
        out.append(f"{label:>{label_width}} │", style=axis_style)

        # Append runs of same-styled cells rather than one call per cell: a
        # frame is well over a thousand cells, and most of them are blank and
        # share a style, so this is where the render time actually goes.
        row_bits = bits[row]
        row_colors = colors[row]
        run_style = row_colors[0]
        run: list[str] = []
        for column in range(width):
            style = row_colors[column]
            if style != run_style:
                out.append("".join(run), style=run_style or None)
                run = []
                run_style = style
            run.append(_BRAILLE_CELLS[row_bits[column]])
        out.append("".join(run), style=run_style or None)
        if row < height - 1:
            out.append("\n")
    return out


