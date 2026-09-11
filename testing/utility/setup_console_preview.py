"""Offline terminal specimen: python -m testing.utility.setup_console_preview."""

import time

from runner.console import format_prompt
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
    ui.output("\n" + ui.heading("Google Sign-In instructions"))
    ui.output(
        ui.info(
            ui.literal("1.")
            + " Choose "
            + ui.literal("Web application")
            + ", then enter these values."
        )
    )
    ui.output(ui.value("  Name", "Example workspace", action=True, verbatim=True))
    ui.output(
        ui.value(
            "  Authorized redirect URI",
            "https://workspace.example.test/users/google-signin",
            action=True,
            verbatim=True,
        )
    )
    ui.output(
        ui.info(
            ui.literal("2.")
            + " Click "
            + ui.literal("Create")
            + ", then "
            + ui.literal("Download JSON")
            + "."
        )
    )
    ui.output("\n" + ui.heading("Cloudflare and manual DNS"))
    ui.output(
        ui.info(
            "Keep "
            + ui.literal("Zone > DNS > Edit")
            + " and add "
            + ui.literal("Zone > Zone > Read")
            + "."
        )
    )
    for label, content in (
        ("Type", "TXT"),
        ("Name", "_dmarc.example.test"),
        ("Value", '"v=DMARC1;  p=none;"'),
    ):
        ui.output(ui.value("  " + label, content, action=True, verbatim=True))
    ui.output(
        ui.status("Managed TLS certificate pending; retrying in 30 seconds", "pending")
    )
    ui.output("\n" + ui.heading("Resend receiving"))
    ui.output(
        ui.info(
            "Create a receiving key with "
            + ui.literal("Full access")
            + ". Keep the "
            + ui.literal("Sending access")
            + " key separate."
        )
    )
    ui.output(ui.status("Optional DMARC setup skipped"))
    ui.output(
        ui.warning(
            "Settings saved locally; the webhook remains disabled until deployment"
        )
    )
    ui.output("\n" + ui.heading("Next steps"))
    ui.output(
        ui.value(
            "Retry AI email",
            setup_command("ai-email"),
            action=True,
            verbatim=True,
            standalone=True,
        )
    )
    from installer.summary import print_install_summary

    ui.output("\n" + ui.success("Setup complete"))
    print_install_summary(
        {
            "APP_NAME": "Example workspace",
            "APP_URL": "https://workspace.example.test",
            "INSTALLER_EMAIL": "installer@example.test",
            "DEPLOYER_EMAIL": "installer@example.test",
            "ADMIN_EMAIL": "owner@example.test",
            "BOOTSTRAP_ADMIN_EMAIL": "installer@example.test",
            "APP_ENGINE_LOCATION": "us-central",
            "RESOURCE_REGION": "us-central1",
            "OCR_LOCATION": "us",
            "REDIS_HOST": "redis.example.test",
            "REDIS_TLS": True,
            "CAPTURE_ERRORS": False,
            "AI_ENABLED": True,
            "EXTERNAL_AI_ENABLED": True,
            "AI_OBSERVABILITY": False,
            "MCP_RESOURCE": "https://agent.example.test/mcp",
            "MCP_VERSION": "diagnostic-only",
            "AI_MODEL": "example-primary",
            "AI_UTILITY_MODEL": "example-utility",
            "AI_IMAGE_MODEL": "example-images",
        },
        node={"version": "1.0.0"},
        gcloud_config={"PROJECT": "example-project", "NAME": "example-workspace"},
        deployed=True,
    )


if __name__ == "__main__":
    main()
