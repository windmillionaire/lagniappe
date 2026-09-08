"""Dependency-free text layout for repository and installer output."""

import re
import shutil
import unicodedata


_SGR = re.compile(r"\x1b\[[0-9;]*m")
_MARKER = re.compile(r"(?:[•*?✔✗!-]|\d+[.)]|\[(?:OK|X|!)\])\s+")
_PROMPT_HINT = re.compile(
    r"\s+((?:\[[^\]\n]+\]|\([YyNn]/[YyNn]\))"
    r"(?:\s+\([^()\n]+\))?|\(x to (?:exit|cancel)\))\s*:?$"
)


# @testable false
# @covered-by runner/console.py::wrap_text
# @reason shared width policy exercised by text and prompt layout
def terminal_width(width=None):
    """Leave the last terminal column free; explicit widths are exact budgets."""
    if width is None:
        width = min(100, shutil.get_terminal_size(fallback=(80, 24)).columns - 1)
    return max(1, int(width))


# @testable false
# @covered-by runner/console.py::wrap_text
# @reason ANSI styling has no display width
def unstyle(message):
    return _SGR.sub("", str(message))


# @testable false
# @covered-by runner/console.py::wrap_text
# @reason cell counting is shared by prose, prompts, rows, and progress labels
def cell_width(message):
    """Count ordinary terminal cells, including combining accents and CJK text."""
    return sum(
        0
        if unicodedata.combining(char) or unicodedata.category(char) == "Cf"
        else 2
        if unicodedata.east_asian_width(char) in {"W", "F"}
        else 1
        for char in unstyle(message)
    )


# @testable true
# @tests tests_tooling/test_001k_setup_console.py::test_prose_layout
# @tests tests_tooling/test_001c_setup_runtime_resources.py::test_setup_formatter_tracks_active_spinners
# @matrix setup : portability terminal-wrapping
def wrap_text(message, width=None):
    """Wrap at words, preserving paragraphs, list indentation, and long tokens."""
    width = terminal_width(width)
    result = []
    for line in str(message).split("\n"):
        if not line.strip():
            result.append("")
            continue
        content = line.lstrip()
        # At very small widths, give words priority over decorative indentation.
        indent = line[: len(line) - len(content)].expandtabs(4)
        indent = indent[: max(0, width - 4)]
        marker = _MARKER.match(content)
        prefix = marker.group() if marker else ""
        if marker:
            content = content[marker.end() :]
        words = content.split()
        word_room = max(0, width - max((cell_width(word) for word in words), default=0))
        indent = indent[:word_room]
        continuation = " " * min(cell_width(indent + prefix), word_room)
        current = indent + prefix
        has_word = False
        for word in words:
            candidate = current + (" " if has_word else "") + word
            if (has_word or current.strip()) and cell_width(candidate) > width:
                result.append(current)
                current = continuation + word
            else:
                current = candidate
            has_word = True
        result.append(current.rstrip())
    return "\n".join(result)


# @testable true
# @tests tests_tooling/test_001k_setup_console.py::test_prompt_layout
# @matrix setup : interactive-input terminal-wrapping
def format_prompt(message, width=None):
    """Use one leading question marker while preserving answer/default hints."""
    width = terminal_width(width)
    original = str(message)
    text = unstyle(original).rstrip()
    leading = "\n" * (len(text) - len(text.lstrip("\n")))
    text = text.lstrip("\n")
    if text.startswith("? "):
        text = text[2:]
    hint_match = _PROMPT_HINT.search(text)
    hint = hint_match.group(1) if hint_match else ""
    body = text[: hint_match.start()] if hint_match else text
    body = body.rstrip().rstrip("?:").rstrip()
    rendered = wrap_text("? " + body, width=max(1, width - 1))
    if hint:
        separator = (
            " "
            if cell_width(rendered.split("\n")[-1] + " " + hint + " ") <= width
            else "\n  "
        )
        rendered += separator + hint
    # Preserve the caller's color policy, applying its emphasis only to the marker.
    color = _SGR.search(original)
    if color:
        rendered = color.group() + "?" + "\x1b[0m" + rendered[1:]
    return leading + rendered + " "


# @testable true
# @tests tests_tooling/test_001k_setup_console.py::test_value_layout_preserves_copyable_values
# @matrix setup : operator-summary terminal-wrapping
def format_value(
    label, value, *, width=None, column=None, verbatim=False, standalone=False
):
    """Align a short row or put its complete value beneath a wrapped label."""
    width = terminal_width(width)
    label = str(label).rstrip(":") + ":"
    value = str(value)
    column = max(cell_width(label) + 2, column or 0)
    if not standalone and "\n" not in value and column + cell_width(value) <= width:
        return label + " " * (column - cell_width(label)) + value
    heading = wrap_text(label, width)
    if verbatim:
        return heading + "\n" + "\n".join("  " + line for line in value.split("\n"))
    return (
        heading
        + "\n"
        + wrap_text("\n".join("  " + line for line in value.split("\n")), width)
    )


# @testable true
# @tests tests_tooling/test_001k_setup_console.py::test_progress_label_tracks_terminal_width
# @matrix setup : spinner terminal-wrapping
class ProgressLabel:
    """Yaspin string adapter; fit a neutral label on each animation frame."""

    def __init__(self, message):
        self.message = " ".join(unstyle(message).split())
        self.initial_width = terminal_width()

    def __str__(self):
        # Reserve space for the widest completion glyph ([OK]), separator,
        # and Yaspin's own ellipsis budget. Do not depend on its cached width.
        width = max(1, min(self.initial_width, terminal_width()) - 8)
        if cell_width(self.message) <= width:
            return self.message
        ellipsis = "..." if width >= 4 else "."
        result = ""
        for char in self.message:
            if cell_width(result + char) > width - len(ellipsis):
                break
            result += char
        return result.rstrip() + ellipsis
