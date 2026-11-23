"""Literal terminal styling shared by layout and presentation, with lazy Rich imports."""

from __future__ import annotations

import os
import re
import sys
from typing import TYPE_CHECKING, TextIO

if TYPE_CHECKING:
    from rich.console import Console


_SGR = re.compile(r"\x1b\[[0-9;]*m")


def unstyle(message: object) -> str:
    return _SGR.sub("", str(message))


def _console(stream: TextIO | None = None) -> Console | None:
    stream = sys.stdout if stream is None else stream
    try:
        from rich.console import Console
    except ImportError:
        return None
    tty = bool(getattr(stream, "isatty", lambda: False)())
    styled_output = (
        tty
        and "NO_COLOR" not in os.environ
        and os.environ.get("TERM", "").lower() not in {"dumb", "unknown"}
    )
    console = Console(
        file=stream,
        force_terminal=tty,
        force_jupyter=False,
        color_system="auto" if styled_output else None,
        markup=False,
        highlight=False,
        emoji=False,
    )
    # Builtin input consumes prompt strings. Keep those strings portable in
    # PowerShell's older console host, which cannot reliably render ANSI.
    if console.legacy_windows:
        console = Console(
            file=stream, force_terminal=False, color_system=None,
            force_jupyter=False, markup=False, highlight=False, emoji=False,
            legacy_windows=True,
        )
    return console


def styled(message: object, style: str, *, stream: TextIO | None = None) -> str:
    """Return a literal styled span without introducing wrapping or markup."""
    text = unstyle(message)
    console = _console(stream)
    if console is None or console.color_system is None:
        return text
    from rich.text import Text

    with console.capture() as capture:
        console.print(Text(text, style=style), end="", soft_wrap=True)
    return capture.get()
