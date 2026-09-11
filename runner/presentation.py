"""Shared setup presentation; importing this module never installs packages."""

import builtins
from contextlib import contextmanager
import os
import sys

from runner.console import (
    ProgressLabel,
    format_value,
    terminal_width,
    unstyle,
    wrap_text,
)


ACTIVE_PROGRESS = []
_PAUSE_DEPTH = 0


# @testable false
# @covered-by runner/presentation.py::status
# @reason shared encoding policy exercised by status and progress contracts
def supports_unicode(stream, text):
    try:
        text.encode(getattr(stream, "encoding", None) or "ascii")
    except (LookupError, UnicodeEncodeError):
        return False
    return True


# @testable false
# @covered-by runner/presentation.py::styled
# @reason optional renderer keeps bootstrap and read-only commands dependency-free
def _console(stream=None):
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


# @testable true
# @tests tests_tooling/test_001k_setup_console.py::test_formatter_preserves_plain_and_colored_output
# @matrix setup : package-install spinner
def styled(message, style, *, stream=None):
    """Return a literal styled span without introducing wrapping or markup."""
    text = unstyle(message)
    console = _console(stream)
    if console is None or console.color_system is None:
        return text
    from rich.text import Text

    with console.capture() as capture:
        console.print(Text(text, style=style), end="", soft_wrap=True)
    return capture.get()


# @testable false
# @covered-by runner/presentation.py::status
# @reason format-only section heading follows the shared semantic style contract
def heading(message):
    return styled(str(message).rstrip().rstrip(":.!"), "bold")


# @testable false
# @covered-by runner/presentation.py::styled
# @reason literal inline emphasis shares the renderer's terminal and plain fallbacks
def emphasis(message, *, stream=None):
    return styled(message, "bold", stream=stream)


# @testable false
# @covered-by runner/presentation.py::styled
# @reason exact action targets share the renderer's literal span contract
def literal(message, *, stream=None):
    return styled(message, "cyan", stream=stream)


# @testable true
# @tests tests_tooling/test_001k_setup_console.py::test_instruction_values_preserve_styles_and_copyable_content
# @matrix setup : operator-summary terminal-wrapping
def value(label, content, *, action=False, stream=None, **layout):
    """Render a bold label and an optional cyan copy/type/open target."""
    label = str(label).rstrip(":")
    content = literal(content, stream=stream) if action else str(content)
    if unstyle(label) == label:
        text = label.lstrip()
        label = label[: len(label) - len(text)] + emphasis(text, stream=stream)
    return format_value(label, content, **layout)


# @testable false
# @covered-by runner/presentation.py::status
# @reason format-only annotation follows the shared semantic style contract
def secondary(message):
    return styled(message, "bright_black")


# @testable false
# @covered-by runner/presentation.py::status
# @reason menu choice styling uses the same literal span renderer
def choice(key, label, detail=None):
    result = f"  {styled(str(key) + '.', 'cyan')} {label}"
    return wrap_text(result + (f" {secondary('(' + str(detail) + ')')}" if detail else ""))


# @testable true
# @tests tests_tooling/test_001k_setup_console.py::test_semantic_output
# @matrix setup : encoding operator-summary portability terminal-wrapping
def status(message, kind="neutral", *, stream=None):
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


# @testable false
# @covered-by runner/presentation.py::status
# @reason semantic status shortcut
def success(message, *, stream=None):
    return status(message, "success", stream=stream)


# @testable false
# @covered-by runner/presentation.py::status
# @reason semantic status shortcut
def warning(message, diagnostic=None, *, stream=None):
    result = status(message, "warning", stream=stream)
    return result + "\n" + str(diagnostic) if diagnostic else result


# @testable false
# @covered-by runner/presentation.py::status
# @reason diagnostic payload is intentionally left verbatim
def error(message, diagnostic=None, *, stream=None):
    result = status(message, "error", stream=stream)
    return result + "\n" + str(diagnostic) if diagnostic else result


# @testable false
# @covered-by runner/presentation.py::status
# @reason informational prose has no status color
def info(message):
    return wrap_text(message)


# @testable false
# @covered-by runner/presentation.py::status
# @reason static activity labels share the semantic style contract
def activity(message):
    return secondary(wrap_text(str(message).rstrip().rstrip(".") + "..."))


# @testable true
# @tests tests_tooling/test_001k_setup_console.py::test_progress_modes
# @matrix setup : portability spinner
def plain_progress(console, stream=None):
    stream = sys.stdout if stream is None else stream
    return (
        console is None
        or not console.is_terminal
        or console.legacy_windows
        or os.environ.get("TERM", "").lower() in {"dumb", "unknown"}
        or not supports_unicode(stream, "⠋✓✗")
        or terminal_width() < 20
    )


# @testable true
# @tests tests_tooling/test_001c_setup_runtime_resources.py::test_install_if_missing_pauses_active_spinner_for_prompt
# @tests tests_tooling/test_001k_setup_console.py::test_progress_output_and_input
# @matrix setup : package-install spinner
@contextmanager
def pause_progress():
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


# @testable true
# @tests tests_tooling/test_001k_setup_console.py::test_progress_output_and_input
# @matrix setup : package-install spinner
def read_input(prompt=""):
    """Preserve builtin input semantics while keeping the prompt stationary."""
    with pause_progress():
        return builtins.input(prompt) if prompt else builtins.input()


# @testable true
# @tests tests_tooling/test_001k_setup_console.py::test_progress_output_and_input
# @tests tests_tooling/test_001k_setup_console.py::test_semantic_output
# @matrix setup : operator-summary terminal-wrapping package-install spinner
def output(*messages, sep=" ", end="\n", file=None, flush=False, raw=False):
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


# @testable true
# @tests tests_tooling/test_001c_setup_runtime_resources.py::test_setup_formatter_tracks_active_spinners
# @tests tests_tooling/test_001k_setup_console.py::test_progress_output_and_input
# @tests tests_tooling/test_001k_setup_console.py::test_formatter_preserves_plain_and_colored_output
# @matrix setup : package-install spinner
class Progress:
    """One transient Rich indicator, with a static transcript fallback."""

    def __init__(self, text="", *, success_text=None):
        self.text = unstyle(text).strip().rstrip(".")
        self.success_text = success_text
        self.stream = sys.stdout
        self.console = _console(self.stream)
        self.running = False
        self.finished = False
        self.announced = False
        self.live = None

    def __enter__(self):
        for progress in reversed(ACTIVE_PROGRESS):
            progress.stop()
        ACTIVE_PROGRESS.append(self)
        try:
            self.start()
        except BaseException:
            self.__exit__(*sys.exc_info())
            raise
        return self

    def __exit__(self, exc_type, exc, tb):
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

    def start(self):
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

    def stop(self):
        if self.live is not None and self.running:
            self.live.stop()
        self.running = False
        return self

    def write(self, message, *, raw=False):
        output(message, file=self.stream, raw=raw)

    def _finish(self, kind, message):
        if self.finished:
            return
        self.stop()
        self.finished = True
        output(status(message, kind, stream=self.stream), file=self.stream)

    def ok(self, message=None):
        self._finish("success", message or self.success_text or f"Completed: {self.text}")

    def fail(self, message=None):
        self._finish("error", message or f"Failed: {self.text}")

    def skip(self, message):
        self._finish("neutral", message)
