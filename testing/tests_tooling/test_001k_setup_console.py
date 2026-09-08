"""Portable, offline contracts for installer text and progress output."""

import io
import sys
import types

import pytest

from runner.console import (
    ProgressLabel,
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
    assert "[My workspace] " in format_prompt(
        "Installation name [My workspace]: ", width
    )
    assert format_prompt("Continue? [Y/n]: ", width).endswith("[Y/n] ")
    assert format_prompt("Value (x to exit): ", width).endswith("(x to exit) ")
    assert format_prompt("Press Enter to continue: ", width).endswith("continue ")
    assert (
        " ".join(format_prompt("Continue? [Y/n] (x to exit): ", width).split())
        == "? Continue [Y/n] (x to exit)"
    )
    assert (
        " ".join(
            format_prompt("Continue? [Y/n] (s to skip; x to exit): ", width).split()
        )
        == "? Continue [Y/n] (s to skip; x to exit)"
    )
    assert "[Why?]" in format_prompt("Label [Why?]: ", width)
    assert "https://example.test/?q=value" in format_prompt(
        "URL [https://example.test/?q=value]: ", width
    )
    colored = format_prompt("\n\x1b[36m" + message + "\x1b[0m", width)
    assert unstyle(colored) == "\n" + result
    assert "\x1b[36m?\x1b[0m" in colored
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
    if width == 40:
        assert "Application:\n  Example workspace" in text
    if width == 100:
        rows = text.splitlines()
        application = next(line for line in rows if line.startswith("Application:"))
        feature = next(line for line in rows if line.startswith("AI features:"))
        assert application.index("Example workspace") == feature.index("enabled")


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
    "platform,tty,encoding,term,columns,plain",
    [
        ("posix", True, "utf-8", "xterm", 80, False),
        ("nt", True, "utf-8", "xterm", 80, True),
        ("posix", False, "utf-8", "xterm", 80, True),
        ("posix", True, "ascii", "xterm", 80, True),
        ("posix", True, "utf-8", "dumb", 80, True),
        ("posix", True, "utf-8", "xterm", 12, True),
    ],
)
def test_progress_modes(monkeypatch, platform, tty, encoding, term, columns, plain):
    import installer

    stream = types.SimpleNamespace(isatty=lambda: tty, encoding=encoding)
    with monkeypatch.context() as scoped:
        scoped.setattr(installer.os, "name", platform)
        scoped.setenv("TERM", term)
        scoped.setenv("COLUMNS", str(columns))
        assert installer._use_plain_progress(stream) is plain


# @matrix setup : package-install spinner
@pytest.mark.parametrize("tty,no_color", [(True, False), (True, True), (False, False)])
def test_formatter_preserves_plain_and_colored_output(monkeypatch, tty, no_color):
    import installer
    from installer import package_install

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
    assert ("\x1b" in formatter.info("Heading")) is (tty and not no_color)
    assert unstyle(formatter.error("Failed.")) == "Failed."
    diagnostic = "provider output:\n  command with    preserved spacing\nsecond line"
    assert unstyle(formatter.error("Failed.", diagnostic)) == "Failed.\n" + diagnostic
    # Static output retains the operation name beside the result.
    monkeypatch.setattr(installer, "_use_plain_progress", lambda stream=None: True)
    with formatter.yaspin(text=formatter.success("Deploying application")) as spinner:
        assert package_install._ACTIVE_SPINNERS[-1] is spinner
        spinner.write(wrap_text("A short progress detail."))
        spinner.ok(formatter.ok_glyph)
    assert package_install._ACTIVE_SPINNERS == []
    assert "Deploying application" in output.getvalue()
    assert f"{formatter.ok_glyph} Deploying application" in output.getvalue()
    assert "\x1b" not in output.getvalue()
