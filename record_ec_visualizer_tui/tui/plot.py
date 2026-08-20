"""Sub-cell line plots rendered into a ``rich.text.Text``.

Same approach and public shape as bico's ``bico/tui/plot.py``: a plain function
that turns a list of series into styled text, with no widget or library beyond
rich. Each terminal cell carries 2x4 braille dots, so a plot is four times
taller and twice wider in resolution than its character grid.

Braille dot-to-bit layout inside one cell::

    (0,0) (1,0)      bit 0   bit 3
    (0,1) (1,1)      bit 1   bit 4
    (0,2) (1,2)      bit 2   bit 5
    (0,3) (1,3)      bit 6   bit 7

Which glyphs a cell is drawn from is a :class:`GlyphSet`, because braille is not
available everywhere. The Linux virtual console — the monitor attached to the
logging host — renders with a console-setup font holding 256 or 512 glyphs and
no braille block at all, so every cell of a braille plot, including the blank
ones, comes out as a replacement box. :data:`BLOCKS` draws the same plot from
half blocks instead, which those fonts do carry, at half the vertical and half
the horizontal resolution. It is never selected automatically: a terminal that
cannot draw braille is indistinguishable at this level from one that can, and
guessing wrong would silently halve the resolution of a display that was fine.
"""
from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from rich.text import Span, Text

BRAILLE_BASE = 0x2800
_DOT_BITS = ((0, 1, 2, 6), (3, 4, 5, 7))

#: Bit masks flattened to ``(dot_x & 1) * 4 + (dot_y & 3)``. Setting a dot is
#: the innermost operation in the renderer — several thousand times per frame —
#: so it indexes this table instead of calling a helper and shifting.
_DOT_MASKS = tuple(1 << _DOT_BITS[x][y] for x in (0, 1) for y in (0, 1, 2, 3))

#: Every braille cell, precomputed. Cheaper than chr() per cell per frame.
_BRAILLE_CELLS = tuple(chr(BRAILLE_BASE + value) for value in range(256))

#: Upper half block, lower half block, full block. Written as escapes for the
#: same reason the rest of this package sticks to ASCII source: these are the
#: characters most likely to be mangled by a terminal or editor that is not
#: sure what encoding it is looking at.
BLOCK_UPPER, BLOCK_LOWER, BLOCK_FULL = "\u2580", "\u2584", "\u2588"

#: Half-block cells, indexed the same way: bit 0 is the top half, bit 1 the
#: bottom. A blank cell is a plain space, not a blank glyph as in braille.
_BLOCK_CELLS = (" ", BLOCK_UPPER, BLOCK_LOWER, BLOCK_FULL)


@dataclass(frozen=True)
class GlyphSet:
    """How many dots fit in a terminal cell, and what to draw them with.

    ``masks`` is indexed ``(dot_x & (dots_x - 1)) * dots_y + (dot_y & (dots_y - 1))``
    and ``cells`` by the resulting bit pattern, which is the same flattened
    lookup the braille renderer always used. ``shift_x``/``shift_y`` turn a dot
    coordinate into a cell coordinate.
    """

    name: str
    dots_x: int
    dots_y: int
    shift_x: int
    shift_y: int
    masks: tuple[int, ...]
    cells: tuple[str, ...]
    #: ``cells`` as a table for :meth:`str.translate`, so a row of bit
    #: patterns becomes a row of glyphs in one C-level call instead of a
    #: Python lookup per cell.
    table: dict[int, str]


#: 2x4 dots per cell. The default, and the reason the plots look like plots.
BRAILLE = GlyphSet("braille", 2, 4, 1, 2, _DOT_MASKS, _BRAILLE_CELLS, dict(enumerate(_BRAILLE_CELLS)))

#: 1x2 dots per cell, for terminals whose font has no braille.
BLOCKS = GlyphSet("blocks", 1, 2, 0, 1, (1, 2), _BLOCK_CELLS, dict(enumerate(_BLOCK_CELLS)))

#: Selectable by name from the command line.
GLYPH_SETS = {glyphs.name: glyphs for glyphs in (BRAILLE, BLOCKS)}


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


def _sample_points(
    ys: Sequence[Any],
    dot_cols: int,
) -> tuple[list[tuple[int, float]], int, float, float]:
    """Finite samples, already reduced to what the dot grid can show.

    Returns the points in index order, the sample stride they now stand for,
    and the lowest and highest values seen. The bounds come back from the same
    pass because the axis needs them and a separate pass to collect them would
    be a second walk over the whole window.

    A 20 Hz stream easily carries several samples per dot column, and drawing
    every one of them is wasted work: the column can only show the range they
    span. Keeping the minimum and maximum per column draws the identical
    picture — the vertical smear of a dense trace *is* its min/max envelope —
    for a fraction of the segments. The stride comes back with them so gap
    detection can be scaled to match.

    The dense path walks the samples a column at a time, keeping the running
    extremes in locals, rather than tagging every sample with its column and
    filing it. Both forms visit each sample once, but the filing form paid a
    tuple for every sample and a dict lookup and store for every column, and
    at four thousand samples a frame that allocation is most of the cost.

    The two loops are deliberately not one. Folding them together would mean
    either a branch per sample or a full list of points built before the dense
    path throws most of it away, and at four thousand samples a frame this is
    the walk that has to stay tight. Series from
    :class:`~record_ec_visualizer_tui.model.SeriesBuffer` are always floats, so
    that case gets an exact-type fast path; anything else still goes through
    the general checks.
    """
    count = len(ys)
    stride = max(1, -(-count // dot_cols)) if count > dot_cols else 1  # ceil
    isfinite = math.isfinite
    lowest = math.inf
    highest = -math.inf

    if stride == 1:
        points: list[tuple[int, float]] = []
        append = points.append
        for index, value in enumerate(ys):
            if type(value) is float:
                if not isfinite(value):
                    continue
            else:
                value = _as_float(value)
                if value is None:
                    continue
            append((index, value))
            if value < lowest:
                lowest = value
            if value > highest:
                highest = value
        return points, 1, lowest, highest

    reduced: list[tuple[int, float]] = []
    append = reduced.append
    for start in range(0, count, stride):
        stop = min(start + stride, count)
        low_index = high_index = -1
        low_value = math.inf
        high_value = -math.inf
        for index in range(start, stop):
            value = ys[index]
            if type(value) is float:
                if not isfinite(value):
                    continue
            else:
                value = _as_float(value)
                if value is None:
                    continue
            if value < low_value:
                low_value = value
                low_index = index
            if value > high_value:
                high_value = value
                high_index = index
        if low_index < 0:
            continue
        if low_index < high_index:
            append((low_index, low_value))
            append((high_index, high_value))
        elif high_index < low_index:
            append((high_index, high_value))
            append((low_index, low_value))
        else:
            append((low_index, low_value))
        if low_value < lowest:
            lowest = low_value
        if high_value > highest:
            highest = high_value
    return reduced, stride, lowest, highest


def _as_float(value: Any) -> float | None:
    """Coerce anything that is not already a float, or reject it.

    Off the hot path by construction: the fast path in
    :func:`_sample_points` never calls this for the floats a
    :class:`~record_ec_visualizer_tui.model.SeriesBuffer` produces.
    """
    if value is None or isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    as_float = float(value)
    return as_float if math.isfinite(as_float) else None


def _draw_segment(
    x0: int,
    y0: int,
    x1: int,
    y1: int,
    bits: list[bytearray],
    colors: list[list[str | None]],
    color: str | None,
    shift_x: int,
    shift_y: int,
    mask_x: int,
    mask_y: int,
    dots_y: int,
    masks: tuple[int, ...],
) -> None:
    """Bresenham line between two dots, writing them as it goes.

    The dot write is spelled out here rather than delegated to ``set_dot``
    because this loop runs a few thousand times a frame and the call was
    costing more than the work inside it. The geometry arrives as plain
    arguments for the same reason the closure bound it as defaults: an
    attribute lookup on the glyph set at this depth is not free. Both
    endpoints come from the axis mappings, which clamp into the grid, so no
    bounds check is needed on the dots between them.
    """
    dx = abs(x1 - x0)
    dy = -abs(y1 - y0)
    step_x = 1 if x0 < x1 else -1
    step_y = 1 if y0 < y1 else -1
    error = dx + dy
    x, y = x0, y0
    while True:
        cell_x = x >> shift_x
        cell_y = y >> shift_y
        bits[cell_y][cell_x] |= masks[(x & mask_x) * dots_y + (y & mask_y)]
        if color is not None:
            colors[cell_y][cell_x] = color
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
    glyphs: GlyphSet = BRAILLE,
) -> Text:
    """Render ``series`` as a line plot.

    :param series: one dict per line, with ``y`` (a sequence of values, where
        ``None``/``nan`` means "no sample") and optional ``color``.
    :param connect: join consecutive samples into a line rather than plotting
        bare dots.
    :param max_gap: how many missing samples a connecting line may bridge.
        Keeping this at 1 means dropouts show as gaps instead of being drawn
        across, which matters when the gap *is* the thing worth seeing.
    :param y_min: fix the lower bound of the axis instead of deriving it.
    :param y_max: fix the upper bound of the axis instead of deriving it.
    :param glyphs: what to draw the cells from. :data:`BRAILLE` unless the
        terminal's font cannot show it, in which case :data:`BLOCKS`.
    """
    width = max(8, int(width))
    height = max(1, int(height))
    dot_cols = width * glyphs.dots_x
    dot_rows = height * glyphs.dots_y

    # One walk per series: the samples worth drawing and the bounds of the axis
    # come out of the same pass, and a dense series never materialises the
    # points the dot grid could not have shown anyway.
    scanned: list[tuple[dict[str, Any], list[tuple[int, float]], int, int]] = []
    lowest = math.inf
    highest = -math.inf
    for spec in series:
        ys = spec.get("y") or ()
        points, stride, series_low, series_high = _sample_points(ys, dot_cols)
        if not points:
            continue
        scanned.append((spec, points, stride, len(ys)))
        if series_low < lowest:
            lowest = series_low
        if series_high > highest:
            highest = series_high

    if not scanned:
        return Text(empty_message, style=axis_style)

    low = lowest if y_min is None else float(y_min)
    high = highest if y_max is None else float(y_max)
    if not math.isfinite(low) or not math.isfinite(high):  # pragma: no cover - defensive
        return Text(empty_message, style=axis_style)
    if high - low < 1e-12:
        # A flat series still deserves a sensible axis rather than a divide by zero.
        pad = max(abs(high) * 0.01, 0.5)
        low, high = low - pad, high + pad

    # bytearray rows, so a finished row decodes and translates into glyphs
    # without a Python loop over its cells.
    bits = [bytearray(width) for _ in range(height)]
    colors: list[list[str | None]] = [[None] * width for _ in range(height)]

    # Read off the glyph set once for the whole frame: these are handed to
    # the segment loop a few hundred times a panel.
    shift_x, shift_y = glyphs.shift_x, glyphs.shift_y
    mask_x, mask_y = glyphs.dots_x - 1, glyphs.dots_y - 1
    dots_y, masks = glyphs.dots_y, glyphs.masks

    for spec, points, stride, count in scanned:
        color = spec.get("color")
        # gap_limit rises with the stride so a dropout still reads as a gap
        # once a dense series has been collapsed to its per-column envelope.
        gap_limit = max_gap * stride

        # The two axis mappings are written out where they are used rather
        # than called: they run once per point, several thousand times a
        # frame, and the arithmetic is two operations either side of a call.
        # The expressions are kept in the original order so the rounding lands
        # on the same dot it always did.
        x_span = dot_cols - 1
        x_count = count - 1
        y_span = dot_rows - 1
        value_span = high - low

        # What draws a lone dot: a series drawn unconnected, or the far side
        # of a gap too wide to bridge. The dots along a segment are written by
        # :func:`_draw_segment` itself, which is where the volume is. The
        # geometry is still bound as default arguments rather than read off
        # the dataclass, for the same reason it is passed to the segment
        # loop by value: an attribute lookup at this depth is not free.
        def set_dot(
            dot_x: int,
            dot_y: int,
            color: str | None = color,
            shift_x: int = shift_x,
            shift_y: int = shift_y,
            mask_x: int = mask_x,
            mask_y: int = mask_y,
            dots_y: int = dots_y,
            masks: tuple[int, ...] = masks,
        ) -> None:
            if not (0 <= dot_x < dot_cols and 0 <= dot_y < dot_rows):
                return
            cell_x, cell_y = dot_x >> shift_x, dot_y >> shift_y
            bits[cell_y][cell_x] |= masks[(dot_x & mask_x) * dots_y + (dot_y & mask_y)]
            if color is not None:
                colors[cell_y][cell_x] = color

        previous: tuple[int, int, int] | None = None
        for index, value in points:
            dot_x = x_span if x_count <= 0 else int(round(index * x_span / x_count))
            dot_y = int(round((high - value) / value_span * y_span))
            if dot_y < 0:
                dot_y = 0
            elif dot_y > y_span:
                dot_y = y_span
            if connect and previous is not None:
                prev_index, prev_x, prev_y = previous
                if index - prev_index <= gap_limit:
                    _draw_segment(
                        prev_x, prev_y, dot_x, dot_y,
                        bits, colors, color,
                        shift_x, shift_y, mask_x, mask_y, dots_y, masks,
                    )
                else:
                    set_dot(dot_x, dot_y)
            else:
                set_dot(dot_x, dot_y)
            previous = (index, dot_x, dot_y)

    # The whole frame is assembled as one string plus a list of spans, and
    # handed to ``Text`` once. Appending to a ``Text`` was 29% of a frame:
    # every call strips control codes and extends the span list, and a plot of
    # a wiggly trace breaks into hundreds of short same-styled runs per frame.
    # A row of cells is a row of bit patterns, so it is held as a bytearray
    # and turned into glyphs by one ``translate`` rather than a lookup per
    # cell, and the coloured runs become slices of it.
    parts: list[str] = []
    spans: list[Span] = []
    offset = 0
    table = glyphs.table
    for row in range(height):
        if row == 0:
            label = _fmt(high)
        elif row == height - 1:
            label = _fmt(low)
        else:
            label = ""
        axis = f"{label:>{label_width}} │"
        parts.append(axis)
        spans.append(Span(offset, offset + len(axis), axis_style))
        offset += len(axis)

        row_bits = bits[row]
        row_colors = colors[row]
        parts.append(row_bits.decode("latin-1").translate(table))
        # A cell with no dots in it shows nothing, so it takes whatever colour
        # the run it sits in already has rather than ending that run. This is
        # not cosmetic: every span costs Textual one uncached rich-to-Textual
        # style conversion when the panel is updated, and a trace that weaves
        # across a row leaves single coloured cells between blanks. Carrying
        # the run over the blanks turns those back into a handful of spans.
        start = 0
        run_style = row_colors[0]
        for column in range(1, width):
            if not row_bits[column]:
                continue
            style = row_colors[column]
            if style != run_style:
                if run_style is not None:
                    spans.append(Span(offset + start, offset + column, run_style))
                start = column
                run_style = style
        if run_style is not None:
            spans.append(Span(offset + start, offset + width, run_style))
        offset += width

        if row < height - 1:
            parts.append("\n")
            offset += 1
    return Text("".join(parts), spans=spans)
