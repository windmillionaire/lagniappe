"""Offline terminal specimen: python -m testing.utility.setup_console_preview."""

import time

from runner.console import format_prompt, format_value
from runner.context import setup_command
from runner import presentation as ui


def main():
    ui.output(ui.heading("Setup presentation preview"))
    ui.output(ui.secondary("Sample data; no setup changes are made."), end="\n\n")
    ui.output(ui.heading("Application settings"))
    ui.output(ui.info("Choose the name displayed in your installation."), end="\n\n")
    ui.output(format_prompt("Application name", default="My workspace", hint="x to exit"))
    ui.output(format_prompt("Enable AI features", hint="Y/n"), end="\n\n")
    ui.output(ui.choice(1, "Existing project", "example-project"))
    ui.output(ui.choice(2, "Create a project"), end="\n\n")
    with ui.Progress("Checking configuration", success_text="Configuration verified") as progress:
        time.sleep(1)
        progress.ok()
    ui.output(ui.status("Deployment skipped"))
    ui.output(ui.warning("Additional configuration required"))
    ui.output(ui.info("Add the DNS records, then rerun setup to verify them."))
    ui.output(ui.status("Managed certificate pending", "pending"))
    ui.output(ui.error("Example provider failure"))
    ui.output("  provider detail: [literal brackets] and    preserved spaces", raw=True)
    ui.output("\n" + ui.heading("Next steps"))
    ui.output(format_value("Check the installation", setup_command("doctor"), verbatim=True, standalone=True))


if __name__ == "__main__":
    main()
