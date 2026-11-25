"""Shared setup presentation; importing this module never installs packages."""

from __future__ import annotations

import builtins
import os
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from types import TracebackType
from typing import TYPE_CHECKING, Literal, Self, TextIO, TypedDict, Unpack

from runner.console import (
    ProgressLabel,
    format_value,
    terminal_width,
    wrap_text,
)
from runner.terminal import _console, styled, unstyle

if TYPE_CHECKING:
    from rich.console import Console


class ValueLayout(TypedDict, total=False):
    width: int | None
    column: int | None
    verbatim: bool
    standalone: bool


ACTIVE_PROGRESS = []
_PAUSE_DEPTH = 0


def supports_unicode(stream: TextIO | None, text: str) -> bool:
    try:
        text.encode(getattr(stream, "encoding", None) or "ascii")
    except (LookupError, UnicodeEncodeError):
        return False
    return True


def heading(message: object) -> str:
    return styled(str(message).rstrip().rstrip(":.!"), "bold")


def emphasis(message: object, *, stream: TextIO | None = None) -> str:
    return styled(message, "bold", stream=stream)


def literal(message: object, *, stream: TextIO | None = None) -> str:
    return styled(message, "cyan", stream=stream)


def value(
    label: object,
    content: object,
    *,
    action: bool = False,
    stream: TextIO | None = None,
    **layout: Unpack[ValueLayout],
) -> str:
    """Render a bold label and an optional cyan copy/type/open target."""
    label = str(label).rstrip(":")
    content = literal(content, stream=stream) if action else str(content)
    if unstyle(label) == label:
        text = label.lstrip()
        label = label[: len(label) - len(text)] + emphasis(text, stream=stream)
    return format_value(label, content, **layout)


def secondary(message: object) -> str:
    return styled(message, "bright_black")


def choice(key: object, label: object, detail: object = None) -> str:
    result = f"  {styled(str(key) + '.', 'cyan')} {label}"
    return wrap_text(result + (f" {secondary('(' + str(detail) + ')')}" if detail else ""))


def status(
    message: object, kind: str = "neutral", *, stream: TextIO | None = None
) -> str:
    """Style only the status marker, leaving explanatory prose neutral."""
    stream = sys.stdout if stream is None else stream
    glyph, style = {
        "success": ("✓" if supports_unicode(stream, "✓") else "[OK]", "green"),
        "warning": ("!", "yellow"),
        "error": ("✗" if supports_unicode(stream, "✗") else "[X]", "red"),
        "pending": ("-", "yellow"),
        "neutral": ("-", "default"),
    }[kind]
    text = unstyle(message).strip()
    first, separator, rest = text.partition("\n")
    # Only short status labels lose their final punctuation. Multi-sentence
    # explanations and provider detail remain intact.
    first = first.rstrip(".!:") if ". " not in first else first
    rendered = wrap_text(f"{glyph} {first}" + separator + rest)
    return styled(glyph, style, stream=stream) + rendered[len(glyph):]


def success(message: object, *, stream: TextIO | None = None) -> str:
    return status(message, "success", stream=stream)


def warning(
    message: object, diagnostic: object = None, *, stream: TextIO | None = None
) -> str:
    result = status(message, "warning", stream=stream)
    return result + "\n" + str(diagnostic) if diagnostic else result


def error(
    message: object, diagnostic: object = None, *, stream: TextIO | None = None
) -> str:
    result = status(message, "error", stream=stream)
    return result + "\n" + str(diagnostic) if diagnostic else result


def info(message: object) -> str:
    return wrap_text(message)


def activity(message: object) -> str:
    return secondary(wrap_text(str(message).rstrip().rstrip(".") + "..."))


def plain_progress(console: Console | None, stream: TextIO | None = None) -> bool:
    stream = sys.stdout if stream is None else stream
    return (
        console is None
        or not console.is_terminal
        or console.legacy_windows
        or os.environ.get("TERM", "").lower() in {"dumb", "unknown"}
        or not supports_unicode(stream, "⠋✓✗")
        or terminal_width() < 20
    )


@contextmanager
def pause_progress() -> Iterator[None]:
    global _PAUSE_DEPTH
    if _PAUSE_DEPTH == 0:
        for progress in reversed(ACTIVE_PROGRESS):
            progress.stop()
    _PAUSE_DEPTH += 1
    try:
        yield
    finally:
        _PAUSE_DEPTH -= 1
        if _PAUSE_DEPTH == 0 and ACTIVE_PROGRESS:
            ACTIVE_PROGRESS[-1].start()


def read_input(prompt: str = "") -> str:
    """Preserve builtin input semantics while keeping the prompt stationary."""
    with pause_progress():
        return builtins.input(prompt) if prompt else builtins.input()


def output(
    *messages: object,
    sep: str = " ",
    end: str = "\n",
    file: TextIO | None = None,
    flush: bool = False,
    raw: bool = False,
) -> None:
    """Print already-laid-out text literally, coordinating with active progress."""
    stream = sys.stdout if file is None else file
    active = next(
        (p for p in reversed(ACTIVE_PROGRESS) if getattr(p, "running", False)),
        None,
    )
    if raw or (active is not None and active.stream is not stream):
        with pause_progress():
            builtins.print(*messages, sep=sep, end=end, file=stream, flush=flush)
        return
    console = active.console if active is not None else _console(stream)
    text = sep.join(str(message) for message in messages)
    if console is None:
        builtins.print(unstyle(text), end=end, file=stream, flush=flush)
        return
    from rich.text import Text

    console.print(Text.from_ansi(text), end=end, soft_wrap=True)
    if flush:
        stream.flush()


class Progress:
    """One transient Rich indicator, with a static transcript fallback."""

    def __init__(self, text: str = "", *, success_text: str | None = None) -> None:
        self.text = unstyle(text).strip().rstrip(".")
        self.success_text = success_text
        self.stream = sys.stdout
        self.console = _console(self.stream)
        self.running = False
        self.finished = False
        self.announced = False
        self.live = None

    def __enter__(self) -> Self:
        for progress in reversed(ACTIVE_PROGRESS):
            progress.stop()
        ACTIVE_PROGRESS.append(self)
        try:
            self.start()
        except BaseException:
            self.__exit__(*sys.exc_info())
            raise
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> Literal[False]:
        try:
            self.stop()
        finally:
            self.finished = True
            ACTIVE_PROGRESS.remove(self)
            if ACTIVE_PROGRESS:
                ACTIVE_PROGRESS[-1].start()
        return False

    def _render(self):
        from rich.spinner import Spinner
        from rich.text import Text

        if not hasattr(self, "spinner"):
            self.spinner = Spinner("dots", style="bright_black")
        self.label = ProgressLabel(self.text + "...")
        self.spinner.update(text=Text(str(self.label), style="bright_black"))
        return self.spinner

    def start(self) -> Self:
        if self.finished or self.running or _PAUSE_DEPTH:
            return self
        if plain_progress(self.console, self.stream):
            if not self.announced:
                output(activity(self.text), file=self.stream)
                self.announced = True
            return self
        from rich.live import Live

        if self.live is None:
            self.live = Live(
                console=self.console, get_renderable=self._render,
                transient=True, refresh_per_second=8,
                redirect_stdout=False, redirect_stderr=False,
            )
        self.live.start(refresh=True)
        self.running = True
        return self

    def stop(self) -> Self:
        if self.live is not None and self.running:
            self.live.stop()
        self.running = False
        return self

    def write(self, message: object, *, raw: bool = False) -> None:
        output(message, file=self.stream, raw=raw)

    def _finish(self, kind, message):
        if self.finished:
            return
        self.stop()
        self.finished = True
        output(status(message, kind, stream=self.stream), file=self.stream)

    def ok(self, message: object = None) -> None:
        self._finish("success", message or self.success_text or f"Completed: {self.text}")

    def fail(self, message: object = None) -> None:
        self._finish("error", message or f"Failed: {self.text}")

    def skip(self, message: object) -> None:
        self._finish("neutral", message)
