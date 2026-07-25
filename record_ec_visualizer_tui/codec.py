"""Decoding of the wire formats rECorD publishes.

rECorD uses two different encodings on its UDP multicast sockets, and mixing
them up is the easiest mistake to make here:

* ``sonicshow`` and ``analyzershow`` send a **Python dict repr** — the sender
  does ``f"{some_dict}\\n".encode()``, so the payload uses single quotes and is
  *not* valid JSON. It has to go through :func:`ast.literal_eval`.
* the raw gas analyzer stream sends **real JSON**, one object per line.

Both are newline-delimited, and a message may be split across datagrams, so
bytes are accumulated by :class:`LineAssembler` before being parsed.

Numbers in the show-messages are pre-formatted text: wind components arrive as
``"1.23(0.45)"`` (mean and standard deviation over the last interval) and buffer
fills as ``"198/200"``. Those are unpacked by :func:`parse_mean_stdev` and
:func:`parse_buffer_fill`.
"""
from __future__ import annotations

import ast
import json
import math
import re
from collections.abc import Mapping, Sequence
from typing import Any

LINE_SEPARATOR = b"\n"

# "1.23(0.45)", and "nan" for either part: rECorD formats the standard deviation
# of a single-record interval as float('NAN'), which renders as "nan".
_MEAN_STDEV_RE = re.compile(
    r"^\s*(?P<mean>nan|[-+]?[0-9]*\.?[0-9]+(?:[eE][-+]?[0-9]+)?)"
    r"\s*\(\s*(?P<stdev>nan|[-+]?[0-9]*\.?[0-9]+(?:[eE][-+]?[0-9]+)?)\s*\)\s*$",
    re.IGNORECASE,
)
_BUFFER_RE = re.compile(r"^\s*(?P<used>\d+)\s*/\s*(?P<size>\d+)\s*$")


class DecodeError(ValueError):
    """Raised when a payload cannot be decoded into a record dictionary."""


class LineAssembler:
    """Accumulate byte chunks and hand back complete separator-delimited lines.

    A datagram is not guaranteed to be a whole message: rECorD reads its own
    sockets in 1024 byte chunks and only parses once it has seen a newline, so
    a consumer has to do the same.
    """

    def __init__(self, separator: bytes = LINE_SEPARATOR, max_buffer: int = 1 << 20) -> None:
        self._separator = separator
        self._max_buffer = max_buffer
        self._buffer = bytearray()

    def push(self, chunk: bytes) -> list[bytes]:
        """Add received bytes, returning every complete line they completed."""
        self._buffer.extend(chunk)
        if self._separator not in self._buffer:
            # Guard against a peer that never sends a separator.
            if len(self._buffer) > self._max_buffer:
                del self._buffer[: -self._max_buffer]
            return []
        *complete, remainder = bytes(self._buffer).split(self._separator)
        self._buffer = bytearray(remainder)
        return [line for line in complete if line.strip()]

def parse_show_message(payload: bytes | str) -> dict[str, Any]:
    """Decode a ``sonicshow`` / ``analyzershow`` payload (a Python dict repr)."""
    text = payload.decode("utf-8", errors="replace") if isinstance(payload, bytes) else payload
    try:
        value = ast.literal_eval(text.strip())
    except (ValueError, SyntaxError, MemoryError, RecursionError) as exc:
        raise DecodeError(f"not a Python literal: {text[:200]!r}") from exc
    if not isinstance(value, dict):
        raise DecodeError(f"expected a dict, got {type(value).__name__}")
    return {str(key): val for key, val in value.items()}


def parse_ga_message(payload: bytes | str) -> dict[str, Any]:
    """Decode a raw gas analyzer payload (real JSON)."""
    try:
        value = json.loads(payload)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise DecodeError(f"not valid JSON: {payload[:200]!r}") from exc
    if not isinstance(value, dict):
        raise DecodeError(f"expected a JSON object, got {type(value).__name__}")
    return value


def parse_mean_stdev(value: Any) -> tuple[float, float]:
    """Unpack a ``"mean(stdev)"`` string into two floats.

    Either part may be ``nan``. A value that is already numeric is returned as
    the mean with a ``nan`` standard deviation, so callers do not have to care
    whether the sender aggregated or not.
    """
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value), math.nan
    if not isinstance(value, str):
        raise DecodeError(f"cannot read mean/stdev from {value!r}")
    match = _MEAN_STDEV_RE.match(value)
    if match is None:
        raise DecodeError(f"cannot read mean/stdev from {value!r}")
    return float(match["mean"]), float(match["stdev"])


def parse_buffer_fill(value: Any) -> tuple[int, int]:
    """Unpack a ``"used/size"`` buffer-fill string into two ints."""
    if not isinstance(value, str):
        raise DecodeError(f"cannot read buffer fill from {value!r}")
    match = _BUFFER_RE.match(value)
    if match is None:
        raise DecodeError(f"cannot read buffer fill from {value!r}")
    return int(match["used"]), int(match["size"])


class VariableMap:
    """rECorD's ``var_map`` translation, reimplemented.

    A ``var_map`` describes where a value sits in the raw record and what the
    site calls it. The nesting is the *raw* path and the leaf value is the
    *file* variable name, so::

        var_map.Data.CO2D = "CO2_CONC"

    means "``raw["Data"]["CO2D"]`` is the site's ``CO2_CONC``". A flat map such
    as the sonic's ``{"Wc1": "U"}`` is the same thing with an empty path.

    This mirrors ``record.utils.VariableMapping`` closely enough that the same
    TOML works for both, including its tolerance for keys that are missing from
    a given record.
    """

    def __init__(self, config: Mapping[str, Any] | None = None) -> None:
        self._by_path: dict[tuple[str, ...], dict[str, str]] = {}
        self.file_vars: list[str] = []
        if config:
            self._walk(tuple(), config)

    def _walk(self, path: tuple[str, ...], node: Mapping[str, Any]) -> None:
        for key, value in node.items():
            if isinstance(value, Mapping):
                self._walk(path + (str(key),), value)
            else:
                self._by_path.setdefault(path, {})[str(key)] = str(value)
                self.file_vars.append(str(value))

    def file_var_for(self, raw_key: str, path: Sequence[str] = ()) -> str | None:
        """Return the site variable name for a raw key, or ``None`` if unmapped."""
        return self._by_path.get(tuple(path), {}).get(raw_key)

    def apply(self, raw: Mapping[str, Any]) -> dict[str, Any]:
        """Translate a raw record into ``{file_variable: value}``.

        Keys that the record does not carry are skipped rather than raising —
        analyzers legitimately omit fields between modes.
        """
        result: dict[str, Any] = {}
        for path, mapping in self._by_path.items():
            node: Any = raw
            for key in path:
                if not isinstance(node, Mapping) or key not in node:
                    node = None
                    break
                node = node[key]
            if not isinstance(node, Mapping):
                continue
            for raw_key, file_var in mapping.items():
                if raw_key in node:
                    result[file_var] = node[raw_key]
        return result

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"VariableMap({self._by_path!r})"
