"""Browser review capture and HTML report helpers.

This utility supports manual/agent UI review against the managed test server.
It captures browser evidence into a per-review folder and renders curated HTML
reports from a small JSON spec.
"""

from __future__ import annotations

import argparse
from datetime import datetime
import html
import json
import os
from pathlib import Path
import shutil
from typing import Any

from config import SETTINGS

from .artifacts import BROWSER_REVIEWS_DIR, slugify

VIEWPORT_PRESETS = {
    "desktop": {"width": 1280, "height": 720},
    "mobile": {"width": 390, "height": 844},
    "tablet": {"width": 820, "height": 1180},
}

SEVERITIES = {"high", "medium", "low", "good", "note"}


def create_review_dir(
    name: str,
    *,
    timestamp: str | None = None,
    root: Path = BROWSER_REVIEWS_DIR,
) -> Path:
    """Create a timestamped report folder under reports/browser_reviews."""
    stamp = timestamp or datetime.now().strftime("%Y%m%d_%H%M%S")
    review_dir = root / f"{slugify(name, 'browser-review')}_{stamp}"
    (review_dir / "screenshots").mkdir(parents=True, exist_ok=True)
    return review_dir


def parse_viewport(value: str) -> tuple[str, dict[str, int]]:
    """Parse viewport presets or NAME=WIDTHxHEIGHT entries."""
    if "=" not in value:
        if value not in VIEWPORT_PRESETS:
            choices = ", ".join(sorted(VIEWPORT_PRESETS))
            raise ValueError(f"Unknown viewport '{value}'. Use one of: {choices}.")
        return value, VIEWPORT_PRESETS[value]

    name, size = value.split("=", 1)
    width, height = size.lower().split("x", 1)
    return slugify(name, "viewport"), {"width": int(width), "height": int(height)}


def _resolve_target_url(path_or_url: str) -> str:
    if path_or_url.startswith(("http://", "https://")):
        return path_or_url

    suffix = path_or_url if path_or_url.startswith("/") else f"/{path_or_url}"
    return f"{SETTINGS.test_config['BASE_URL']}{suffix}"


def _admin_login_url() -> str:
    email = SETTINGS.test_config["ADMIN_EMAIL"]
    return f"{SETTINGS.test_config['BASE_URL']}/users/login?test_user={email}"


def capture_review(args: argparse.Namespace) -> int:
    """Capture screenshots and browser diagnostics into a review folder."""
    os.environ["FLASK_ENV"] = "testing"
    default_browsers = Path.home() / ".cache/ms-playwright"
    if default_browsers.is_dir():
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(default_browsers)

    from playwright.sync_api import sync_playwright

    review_dir = create_review_dir(args.name)
    screenshots_dir = review_dir / "screenshots"
    target_url = _resolve_target_url(args.path)
    viewports = [parse_viewport(value) for value in args.viewport]
    capture_data: dict[str, Any] = {
        "name": args.name,
        "path": args.path,
        "target_url": target_url,
        "login_url": _admin_login_url() if args.login_admin else None,
        "captures": [],
    }

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage"],
            )
            context = browser.new_context()

            for label, viewport in viewports:
                page = context.new_page()
                console_messages: list[str] = []
                page_errors: list[str] = []
                failed_requests: list[str] = []
                http_errors: list[dict[str, Any]] = []
                page.on(
                    "console",
                    lambda msg: console_messages.append(f"{msg.type}: {msg.text}"),
                )
                page.on("pageerror", lambda exc: page_errors.append(str(exc)))
                page.on(
                    "requestfailed",
                    lambda request: failed_requests.append(
                        f"{request.method} {request.url}: {request.failure}"
                    ),
                )
                page.on(
                    "response",
                    lambda response: (
                        http_errors.append(
                            {"status": response.status, "url": response.url}
                        )
                        if response.status >= 400
                        else None
                    ),
                )

                page.set_viewport_size(viewport)
                if args.login_admin:
                    page.goto(
                        _admin_login_url(),
                        wait_until="load",
                        timeout=args.timeout,
                    )
                response = page.goto(
                    target_url, wait_until="load", timeout=args.timeout
                )
                if args.wait_for:
                    page.wait_for_selector(args.wait_for, timeout=args.timeout)
                if args.settle_ms:
                    page.wait_for_timeout(args.settle_ms)

                screenshot = (
                    screenshots_dir / f"{slugify(args.name, 'capture')}_{label}.png"
                )
                page.screenshot(path=str(screenshot), full_page=True)
                capture_data["captures"].append(
                    {
                        "viewport": label,
                        "size": viewport,
                        "response_status": response.status if response else None,
                        "final_url": page.url,
                        "title": page.title(),
                        "screenshot": str(screenshot.relative_to(review_dir)),
                        "console_messages": console_messages,
                        "page_errors": page_errors,
                        "failed_requests": failed_requests,
                        "http_errors": http_errors,
                    }
                )
                page.close()

            context.close()
            browser.close()

        (review_dir / "capture.json").write_text(
            json.dumps(capture_data, indent=2),
            encoding="utf-8",
        )
        starter = {
            "title": args.title or f"Browser Review: {args.name}",
            "subtitle": args.focus or "",
            "summary": "",
            "findings": [],
            "diagnostics": [],
        }
        (review_dir / "review.json").write_text(
            json.dumps(starter, indent=2) + "\n",
            encoding="utf-8",
        )
    except Exception:
        if not args.keep_failed:
            shutil.rmtree(review_dir, ignore_errors=True)
        raise

    print(review_dir)
    return 0


def _relative_asset(report_dir: Path, path_value: str) -> str:
    path = Path(path_value)
    if path.is_absolute():
        try:
            return path.relative_to(report_dir).as_posix()
        except ValueError:
            return path.as_posix()
    return path.as_posix()


def _finding_screenshots(report_dir: Path, finding: dict[str, Any]) -> str:
    screenshots = finding.get("screenshots", [])
    if not screenshots:
        return ""

    figures = []
    for item in screenshots:
        if isinstance(item, str):
            path_value = item
            caption = ""
        else:
            path_value = item.get("path", "")
            caption = item.get("caption", "")

        if not path_value:
            continue

        image_src = html.escape(_relative_asset(report_dir, path_value))
        caption_html = (
            f"<figcaption>{html.escape(caption)}</figcaption>" if caption else ""
        )
        figures.append(
            f"""
            <figure>
              <img src="{image_src}" alt="{html.escape(caption or "Finding screenshot")}">
              {caption_html}
            </figure>
            """
        )

    if not figures:
        return ""

    return f'<div class="screenshots">{"".join(figures)}</div>'


def _finding_html(report_dir: Path, finding: dict[str, Any]) -> str:
    severity = str(finding.get("severity", "note")).lower()
    if severity not in SEVERITIES:
        severity = "note"

    suggestions = finding.get("suggestions", [])
    suggestions_html = ""
    if suggestions:
        suggestions_html = (
            "<ul>"
            + "".join(f"<li>{html.escape(str(item))}</li>" for item in suggestions)
            + "</ul>"
        )

    body = finding.get("body", "")
    return f"""
      <article class="finding {severity}">
        <h3><span>{html.escape(severity.title())}</span>{html.escape(finding.get("title", "Untitled finding"))}</h3>
        <p>{html.escape(str(body))}</p>
        {suggestions_html}
        {_finding_screenshots(report_dir, finding)}
      </article>
    """


def _diagnostics_html(spec: dict[str, Any]) -> str:
    diagnostics = spec.get("diagnostics", [])
    if not diagnostics:
        return ""

    items = []
    for diagnostic in diagnostics:
        title = diagnostic.get("title", "Diagnostic")
        content = diagnostic.get("content", "")
        items.append(
            f"""
            <details class="diagnostic">
              <summary>{html.escape(str(title))}</summary>
              <pre>{html.escape(str(content))}</pre>
            </details>
            """
        )

    return f"<h2>Diagnostics</h2>{''.join(items)}"


def render_report(spec: dict[str, Any], report_dir: Path) -> str:
    findings = spec.get("findings", [])
    if findings:
        findings_html = "".join(
            _finding_html(report_dir, finding) for finding in findings
        )
    else:
        findings_html = '<p class="empty">No findings recorded.</p>'

    summary = spec.get("summary", "")
    summary_html = (
        f'<p class="summary">{html.escape(str(summary))}</p>' if summary else ""
    )

    generated = spec.get("generated_at") or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(spec.get("title", "Browser Review"))}</title>
  <style>
    :root {{
      --ink: #152033;
      --muted: #667085;
      --line: #d9dee7;
      --panel: #f7f9fc;
      --high: #b42318;
      --medium: #9a5b00;
      --low: #175cd3;
      --good: #087443;
      --note: #475467;
      --brand: #0b6091;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      color: var(--ink);
      background: #fff;
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      line-height: 1.55;
    }}
    header {{
      padding: 32px 40px 24px;
      color: #fff;
      background: var(--brand);
    }}
    header p {{ max-width: 860px; margin: 8px 0 0; color: #dff1ff; }}
    main {{ max-width: 1080px; margin: 0 auto; padding: 28px 28px 48px; }}
    h1, h2, h3 {{ margin: 0; line-height: 1.2; }}
    h2 {{ margin-top: 32px; padding-bottom: 8px; border-bottom: 1px solid var(--line); }}
    .summary, .empty {{
      margin-top: 14px;
      padding: 14px 16px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--panel);
    }}
    .finding {{
      margin-top: 16px;
      padding: 16px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #fff;
    }}
    .finding h3 {{ display: flex; gap: 10px; align-items: center; }}
    .finding h3 span {{
      flex: 0 0 auto;
      min-width: 58px;
      border-radius: 999px;
      padding: 2px 8px;
      color: #fff;
      text-align: center;
      font-size: 12px;
      font-weight: 700;
    }}
    .high h3 span {{ background: var(--high); }}
    .medium h3 span {{ background: var(--medium); }}
    .low h3 span {{ background: var(--low); }}
    .good h3 span {{ background: var(--good); }}
    .note h3 span {{ background: var(--note); }}
    ul {{ margin: 8px 0 0 22px; padding: 0; }}
    .screenshots {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
      gap: 14px;
      margin-top: 14px;
    }}
    figure {{
      margin: 0;
      overflow: hidden;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #fff;
    }}
    img {{ display: block; width: 100%; height: auto; }}
    figcaption {{
      padding: 9px 11px;
      color: var(--muted);
      border-top: 1px solid var(--line);
      font-size: 13px;
    }}
    .diagnostic {{ margin-top: 12px; }}
    pre {{
      overflow: auto;
      white-space: pre-wrap;
      padding: 12px;
      border-radius: 8px;
      color: #e2e8f0;
      background: #0f172a;
      font-size: 12px;
    }}
    footer {{ margin-top: 36px; color: var(--muted); font-size: 13px; }}
  </style>
</head>
<body>
  <header>
    <h1>{html.escape(spec.get("title", "Browser Review"))}</h1>
    <p>{html.escape(spec.get("subtitle", ""))}</p>
  </header>
  <main>
    {summary_html}
    <h2>Findings</h2>
    {findings_html}
    {_diagnostics_html(spec)}
    <footer>Generated {html.escape(generated)}</footer>
  </main>
</body>
</html>
"""


def render_command(args: argparse.Namespace) -> int:
    spec_path = Path(args.spec)
    report_dir = spec_path.parent
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    spec.setdefault("generated_at", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    if args.output:
        output_path = Path(args.output)
    else:
        output_path = report_dir / "index.html"

    output_path.write_text(
        render_report(spec, report_dir),
        encoding="utf-8",
    )
    spec_path.write_text(
        json.dumps(spec, indent=2) + "\n",
        encoding="utf-8",
    )
    print(output_path)
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    capture = subparsers.add_parser("capture", help="Capture browser evidence.")
    capture.add_argument("--name", required=True, help="Review slug/name.")
    capture.add_argument("--title", help="Starter report title.")
    capture.add_argument("--focus", help="Starter report subtitle/focus.")
    capture.add_argument("--path", default="/", help="Target path or URL.")
    capture.add_argument(
        "--login-admin",
        action="store_true",
        help="Log in through /users/login?test_user=<ADMIN_EMAIL> before capture.",
    )
    capture.add_argument(
        "--viewport",
        action="append",
        default=None,
        help="Viewport preset or NAME=WIDTHxHEIGHT. Defaults to desktop and mobile.",
    )
    capture.add_argument(
        "--wait-for",
        default="[lp-view]",
        help="Selector to wait for before screenshot capture.",
    )
    capture.add_argument(
        "--settle-ms",
        type=int,
        default=1200,
        help="Extra milliseconds to wait after load/selector.",
    )
    capture.add_argument(
        "--timeout",
        type=int,
        default=30000,
        help="Navigation and selector timeout in milliseconds.",
    )
    capture.add_argument(
        "--keep-failed",
        action="store_true",
        help="Keep the generated review folder if capture fails.",
    )

    render = subparsers.add_parser("render", help="Render review.json to HTML.")
    render.add_argument("spec", help="Path to review.json.")
    render.add_argument("--output", help="Optional output HTML path.")

    args = parser.parse_args(argv)
    if args.command == "capture" and args.viewport is None:
        args.viewport = ["desktop", "mobile"]
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.command == "capture":
        return capture_review(args)
    if args.command == "render":
        return render_command(args)
    raise ValueError(f"Unknown command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
