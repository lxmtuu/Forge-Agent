"""Forge Agent — a self-hosted coding agent engine (Claude Code / Codex style)."""

import sys

__version__ = "0.38.0"


def _make_output_safe() -> None:
    """Make writing to stdout/stderr unable to raise UnicodeEncodeError.

    Many handlers report an error with ``print`` and then carry on. When the output encoding
    cannot represent a character (the messages are Vietnamese), ``print`` raised inside the
    handler and ended the operation that was meant to continue. Only the error handler changes:
    the encoding that the environment asked for stays, and an unencodable character is written
    as an escape.

    Two handlers raise for such a character: ``strict`` (``PYTHONIOENCODING=cp1252``) and
    ``surrogateescape``, which is the default of Python on Windows and only takes care of lone
    surrogates.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            reconfigure = getattr(stream, "reconfigure", None)
            if reconfigure is not None and stream.errors in ("strict", "surrogateescape"):
                reconfigure(errors="backslashreplace")
        except Exception:  # noqa: BLE001 — a stream that cannot be reconfigured is left as it is
            pass


_make_output_safe()
