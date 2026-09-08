"""Portable, offline contracts for installer text and progress output."""

import builtins
import io
import sys
import types

import pytest

from runner.console import (
    ProgressLabel,
    cell_width,
    format_prompt,
    format_value,
    unstyle,
    wrap_text,
)
from runner.context import format_command

pytestmark = pytest.mark.tooling


# @matrix setup : portability terminal-wrapping
@pytest.mark.parametrize("width", [12, 40, 60, 80, 100])
def test_prose_layout(width, monkeypatch):
    text = "First paragraph.\n\n  1. Review the saved settings before deployment.\n  - Keep all words."
    result = wrap_text(text, width)
    assert all(len(line) <= width for line in result.splitlines())
    assert result.split() == text.split()
    assert "\n\n" in result
    assert "\n     " in wrap_text(
        "  1. Review the saved settings before deployment.", 24
    )
    assert wrap_text("漢字 漢字", 5) == "漢字\n漢字"
    assert wrap_text("cafe\u0301 cafe\u0301", 9) == "cafe\u0301 cafe\u0301"
    assert unstyle(
        wrap_text("\x1b[36mA short sentence with words.\x1b[0m", 12)
    ) == wrap_text("A short sentence with words.", 12)
    token = "https://workspace.example.test/a/very/long/path?value=unchanged"
    assert token in wrap_text("Open " + token, width)
    monkeypatch.setenv("COLUMNS", "13")
    assert (
        max(map(len, wrap_text("A short sentence with several words.").splitlines()))
        <= 12
    )
    monkeypatch.setenv("COLUMNS", "160")
    assert max(map(len, wrap_text("word " * 50).splitlines())) <= 100


# @matrix setup : interactive-input terminal-wrapping
@pytest.mark.parametrize("width", [12, 40, 60, 80, 100])
def test_prompt_layout(width):
    message = "Would you like to deploy the app now? [y/N]: "
    result = format_prompt(message, width)
    assert result.startswith("? ")
    assert result.endswith("[y/N] ")
    assert not result.endswith("  ")
    assert all(len(line) <= width for line in result.splitlines())
    assert " ".join(result.split()) == "? Would you like to deploy the app now [y/N]"
    assert "(My workspace) " in format_prompt(
        "Installation name [My workspace]: ", width
    )
    assert format_prompt("Continue? [Y/n]: ", width).endswith("[Y/n] ")
    assert format_prompt("Value (x to exit): ", width).endswith("[x to exit] ")
    assert format_prompt("Press Enter to continue: ", width).endswith("continue ")
    assert (
        " ".join(format_prompt("Continue? [Y/n] (x to exit): ", width).split())
        == "? Continue [Y/n] [x to exit]"
    )
    assert (
        " ".join(
            format_prompt("Continue? [Y/n] (s to skip; x to exit): ", width).split()
        )
        == "? Continue [Y/n] [s to skip; x to exit]"
    )
    assert "(Why?)" in format_prompt("Label [Why?]: ", width)
    assert "https://example.test/?q=value" in format_prompt(
        "URL [https://example.test/?q=value]: ", width
    )
    colored = format_prompt("\n\x1b[36m" + message + "\x1b[0m", width)
    assert unstyle(colored) == "\n" + result
    assert format_prompt(result, width) == result


# @matrix setup : operator-summary terminal-wrapping
@pytest.mark.parametrize("width", [12, 40, 60, 80, 100])
@pytest.mark.parametrize("windows", [False, True])
def test_value_layout_preserves_copyable_values(width, windows):
    command = format_command(
        [
            "/tools/Google Cloud/gcloud",
            "app",
            "deploy",
            "my app.yaml",
            "--project",
            "example-project",
        ],
        windows=windows,
    )
    rendered = format_value(
        "Deploy the application", command, width=width, verbatim=True, standalone=True
    )
    assert rendered.splitlines()[-1] == "  " + command
    url = "https://workspace.example.test/a/very/long/path?value=unchanged"
    rendered = format_value("Application URL", url, width=width, verbatim=True)
    assert url in rendered
    assert "\n  " + url in rendered or rendered.endswith("  " + url)
    assert format_value("Enabled", "yes", width=40) == "Enabled:  yes"
    assert format_value("漢字", "yes", width=40, column=10) == "漢字:     yes"
    prose = format_value(
        "Status", "Review the saved settings before continuing.", width=width
    )
    assert all(len(line) <= width for line in prose.splitlines())
    assert (
        prose.split() == "Status: Review the saved settings before continuing.".split()
    )


# @matrix setup : manual-dns provider-records terminal-wrapping
@pytest.mark.parametrize("width", [12, 40, 80])
def test_dns_values_remain_verbatim(width, monkeypatch, capsys):
    from installer import ai_email
    from installer.domain import manual

    monkeypatch.setenv("COLUMNS", str(width))
    monkeypatch.setattr(
        manual,
        "FORMATTER",
        types.SimpleNamespace(
            initialize=lambda: types.SimpleNamespace(info=str),
        ),
    )
    name = "_verification.very-long-subdomain.example.test"
    value = '"provider token with   intentional spaces"'
    manual.print_manual_dns_instructions(
        "example.test",
        [
            {"type": "TXT", "name": name, "rrdata": value},
        ],
    )
    ai_email._print_domain_records(
        {
            "records": [
                {"type": "TXT", "name": name, "value": value, "priority": 10},
            ]
        }
    )
    output = capsys.readouterr().out
    assert output.count(name) == 2
    assert output.count(value) == 2
    assert "Priority:" in output
    assert "10" in output


# @matrix setup : operator-summary secret-redaction
@pytest.mark.parametrize("width", [12, 40, 60, 80, 100])
def test_install_summary_is_responsive(width):
    from installer.summary import install_summary_lines

    url = "https://workspace.example.test/a/long/installation/url"
    text = "\n".join(
        install_summary_lines(
            {
                "APP_NAME": "Example workspace",
                "APP_URL": url,
                "AI_ENABLED": True,
                "EXTERNAL_AI_ENABLED": False,
                "ADMIN_EMAIL": "owner@example.test",
                "SECRET_KEY": "must-never-appear",
                "REDIS_PASSWORD": "also-never-appear",
            },
            width=width,
            deployed=True,
        )
    )
    assert "must-never-appear" not in text
    assert "also-never-appear" not in text
    assert " ".join(text.split()).count("External AI (MCP and API/skill):") == 1
    assert ":disabled" not in text
    assert "\n  ./setup.sh doctor\n" in text
    assert "\n  ./setup.sh repair\n" in text
    assert text.endswith("\n  " + url)
    assert text.count(url) == 1
    assert all(
        cell_width(line) <= width
        for line in text.partition("\n\n")[0].splitlines()
    )
    assert "\nAccess\n" in text
    assert "\nServices\n" in text
    assert "\nAI\n" in text
    assert "\nNext steps\n" in text
    if width == 40:
        assert "Application:\n  Example workspace" in text
    if width == 100:
        rows = text.splitlines()
        application = next(line for line in rows if line.startswith("Application:"))
        version = next(line for line in rows if line.startswith("Lagniappe version:"))
        assert application.index("Example workspace") == version.index(
            "(not configured)"
        )


# @matrix setup : operator-summary terminal-wrapping
@pytest.mark.parametrize("width", [12, 40, 80, 100])
def test_instruction_values_preserve_styles_and_copyable_content(width, monkeypatch):
    from rich.text import Text
    from runner import presentation as ui

    class Terminal(io.StringIO):
        def isatty(self):
            return True

    stream = Terminal()
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setenv("TERM", "xterm-256color")
    literal = '"v=DMARC1;  p=none;" [literal brackets]'
    colored = ui.value(
        "  Value", literal, action=True, stream=stream, width=width, verbatim=True
    )
    assert literal in unstyle(colored)
    parsed = Text.from_ansi(colored)
    assert any(span.style.bold for span in parsed.spans)
    assert any(
        span.style.color and span.style.color.number == 6 for span in parsed.spans
    )
    assert ui.emphasis("Required:", stream=stream).endswith("\x1b[0m")
    monkeypatch.setenv("NO_COLOR", "1")
    plain = ui.value(
        "  Value", literal, action=True, stream=stream, width=width, verbatim=True
    )
    assert plain == unstyle(colored)
    assert "\x1b" not in plain


# @matrix setup : spinner terminal-wrapping
def test_progress_label_tracks_terminal_width(monkeypatch):
    monkeypatch.setenv("COLUMNS", "80")
    label = ProgressLabel("\x1b[32mDeploying App Engine indexes and application\x1b[0m")
    assert str(label) == "Deploying App Engine indexes and application"
    for columns in (40, 12, 60, 100):
        monkeypatch.setenv("COLUMNS", str(columns))
        rendered = str(label)
        assert "\x1b" not in rendered
        assert "\n" not in rendered
        assert len("[OK] " + rendered) < columns
    assert label.message == "Deploying App Engine indexes and application"


# @matrix setup : portability spinner
@pytest.mark.parametrize(
    "tty,legacy,encoding,term,columns,plain",
    [
        (True, False, "utf-8", "xterm", 80, False),
        (True, False, "utf-8", "", 80, False),  # Windows Terminal may omit TERM
        (True, True, "utf-8", "", 80, True),  # older Windows console host
        (False, False, "utf-8", "xterm", 80, True),
        (True, False, "ascii", "xterm", 80, True),
        (True, False, "utf-8", "dumb", 80, True),
        (True, False, "utf-8", "xterm", 12, True),
    ],
)
def test_progress_modes(monkeypatch, tty, legacy, encoding, term, columns, plain):
    from runner.presentation import plain_progress

    stream = types.SimpleNamespace(isatty=lambda: tty, encoding=encoding)
    console = types.SimpleNamespace(is_terminal=tty, legacy_windows=legacy)
    monkeypatch.setenv("TERM", term)
    monkeypatch.setenv("COLUMNS", str(columns))
    assert plain_progress(console, stream) is plain
    assert plain_progress(None, stream) is True


# @matrix setup : package-install spinner
@pytest.mark.parametrize("tty,no_color", [(True, False), (True, True), (False, False)])
def test_formatter_preserves_plain_and_colored_output(monkeypatch, tty, no_color):
    import installer
    from installer import package_install
    from runner import presentation as ui

    output = io.StringIO()
    monkeypatch.setattr(output, "isatty", lambda: tty)
    monkeypatch.setattr(sys, "stdout", output)
    monkeypatch.setenv("TERM", "xterm")
    monkeypatch.setenv("COLUMNS", "80")
    monkeypatch.delenv("NO_COLOR", raising=False)
    if no_color:
        monkeypatch.setenv("NO_COLOR", "")
    monkeypatch.setattr(
        package_install, "install_if_missing", lambda *args, **kwargs: None
    )
    formatter = installer.Formatter().initialize()
    assert ("\x1b" in ui.heading("Settings")) is (tty and not no_color)
    assert formatter.info("An explanation.") == "An explanation."
    assert unstyle(formatter.error("Failed.")) == "[X] Failed"
    diagnostic = "provider output:\n  command with    preserved spacing\nsecond line"
    assert unstyle(formatter.error("Failed.", diagnostic)) == "[X] Failed\n" + diagnostic
    with formatter.progress(text="Deploying application", success_text="Application deployed") as progress:
        assert package_install._ACTIVE_SPINNERS[-1] is progress
        progress.write(wrap_text("A short progress detail."))
        progress.ok()
    assert package_install._ACTIVE_SPINNERS == []
    text = unstyle(output.getvalue())
    assert text == "Deploying application...\nA short progress detail.\n[OK] Application deployed\n"
    assert ("\x1b" in output.getvalue()) is (tty and not no_color)


# @matrix setup : encoding operator-summary portability terminal-wrapping
def test_semantic_output(monkeypatch):
    from rich.color import Color
    from rich.text import Text
    from runner import presentation as ui

    class Terminal(io.StringIO):
        encoding = "utf-8"

        def isatty(self):
            return True

    stream = Terminal()
    monkeypatch.setattr(sys, "stdout", stream)
    monkeypatch.setenv("TERM", "xterm")
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setenv("COLUMNS", "80")
    for kind, marker, color in [
        ("success", "✓", "green"), ("warning", "!", "yellow"),
        ("error", "✗", "red"), ("pending", "-", "yellow"),
    ]:
        text = Text.from_ansi(ui.status("Configuration [value] saved.", kind))
        assert text.plain == marker + " Configuration [value] saved"
        assert len(text.spans) == 1
        assert (text.spans[0].start, text.spans[0].end) == (0, len(marker))
        assert text.spans[0].style.color.number == Color.parse(color).number
    prompt = Text.from_ansi(format_prompt("Application name", default="[bold]", hint="x to exit"))
    assert prompt.plain == "? Application name ([bold]) [x to exit] "
    assert prompt.spans[0].style.color.number == 2
    assert prompt.spans[1].style.bold
    assert prompt.spans[-1].style.color.number == 6
    assert Text.from_ansi(ui.heading("Settings:")).plain == "Settings"
    choice = Text.from_ansi(ui.choice(1, "Existing project", "example-project"))
    assert choice.plain == "  1. Existing project (example-project)"
    assert choice.spans[0].style.color.number == 6
    assert choice.spans[-1].style.color.number == 8
    assert unstyle(ui.status("Deployment skipped.")) == "- Deployment skipped"
    assert unstyle(ui.activity("Checking settings")) == "Checking settings..."
    literal = '[red]literal[/red] :rocket: https://example.test/?a=[1]  two spaces'
    ui.output(literal)
    assert stream.getvalue() == literal + "\n"
    monkeypatch.setenv("NO_COLOR", "")
    ui.output(ui.heading("Settings"), ui.success("Saved"), format_prompt("Continue", hint="Y/n"))
    assert "\x1b" not in stream.getvalue()
    # Bootstrap still prints complete plain content before Rich is available.
    monkeypatch.setitem(sys.modules, "rich.console", None)
    assert ui.heading("Settings") == "Settings"
    ui.output(literal)
    assert stream.getvalue().endswith(literal + "\n")


# @matrix setup : package-install spinner
def test_progress_output_and_input(monkeypatch):
    from runner import presentation as ui

    class Terminal(io.StringIO):
        encoding = "utf-8"

        def isatty(self):
            return True

    stream = Terminal()
    monkeypatch.setattr(sys, "stdout", stream)
    monkeypatch.setenv("TERM", "xterm")
    monkeypatch.setenv("COLUMNS", "80")
    assert ui.ACTIVE_PROGRESS == []
    with ui.Progress("Checking configuration", success_text="Configuration verified") as progress:
        assert progress.running
        assert sys.stdout is stream  # Rich must not intercept subprocess output.
        ui.output("Normal [literal] detail.")
        monkeypatch.setenv("COLUMNS", "24")
        assert len(progress._render().text.plain) < 20

        def answer(prompt):
            assert not progress.running
            assert prompt == "? Continue [Y/n] "
            return "y"

        monkeypatch.setattr(builtins, "input", answer)
        with ui.pause_progress():
            assert ui.read_input("? Continue [Y/n] ") == "y"
            assert not progress.running  # nested pauses never resume early
        assert progress.running
        with ui.Progress("Nested check") as nested:
            assert nested.running and not progress.running
            with ui.pause_progress():
                assert not nested.running
            assert nested.running and not progress.running
        assert progress.running
        diagnostic = "provider\n  raw    spacing\n[red]literal"
        sink = io.StringIO()
        ui.output(diagnostic, file=sink, raw=True)
        assert sink.getvalue() == diagnostic + "\n"
        assert progress.running
        progress.ok()
        progress.ok()  # completion is emitted once
        assert not progress.running
    assert ui.ACTIVE_PROGRESS == []
    transcript = unstyle(stream.getvalue())
    assert " ".join(transcript.split()).count("Configuration verified") == 1
    assert "Normal [literal] detail." in transcript
    with pytest.raises(RuntimeError, match="provider failed"):
        with ui.Progress("Failing operation"):
            raise RuntimeError("provider failed")
    assert ui.ACTIVE_PROGRESS == []
    assert "✓ Failing operation" not in unstyle(stream.getvalue())
    monkeypatch.setenv("COLUMNS", "80")
    with ui.Progress("Restoring optional images") as progress:
        progress.skip("Images unchanged")
    assert "- Images unchanged" in unstyle(stream.getvalue())
    assert "✓ Images unchanged" not in unstyle(stream.getvalue())


# @matrix setup : spinner subprocess-output
def test_visible_subprocess_output_pauses_progress(monkeypatch):
    import subprocess
    from runner import presentation as ui, process

    events = []
    progress = types.SimpleNamespace(
        stop=lambda: events.append("paused"),
        start=lambda: events.append("resumed"),
    )
    command = ["provider", "argument with spaces"]

    def run(args, **kwargs):
        assert args == command
        assert kwargs["capture_output"] is False
        assert events[-1] == "paused"
        events.append("provider output")
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr(process.subprocess, "run", run)
    monkeypatch.setattr(ui, "ACTIVE_PROGRESS", [progress])
    assert process.run_command(command, capture_output=False).returncode == 0
    assert events == ["paused", "provider output", "resumed"]
