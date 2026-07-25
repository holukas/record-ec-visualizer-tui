"""
record-ec-visualizer-tui: real-time terminal visualizer for rECorD data
======================================================================

Reads incoming data from the rECorD logging script and renders it live in the
terminal.

The package is split so that simulated and live data travel the same path:

* :mod:`~record_ec_visualizer_tui.codec` decodes rECorD's two wire formats
* :mod:`~record_ec_visualizer_tui.sources` supplies stream lines, from a
  simulator or from real UDP multicast sockets
* :mod:`~record_ec_visualizer_tui.model` holds the rolling state
* :mod:`~record_ec_visualizer_tui.tui` draws it

https://github.com/holukas/record-ec-visualizer-tui
"""
from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("record-ec-visualizer-tui")
except PackageNotFoundError:  # not installed, e.g. running from a source checkout
    __version__ = "0.0.0.dev0"

__all__ = ["__version__"]
