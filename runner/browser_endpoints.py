"""Generate the browser's TypeScript URL helpers from Flask's registered routes."""

import argparse
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

from jinja2 import Environment, StrictUndefined, TemplateError
from werkzeug.routing import BuildError, Map


TEMPLATE = Path("build/browser-endpoints.ts.jinja")
OUTPUT = Path("src/script/generated/endpoints.ts")


def render_endpoints(routes: Map, template: str) -> str:
    """Render client bindings using the same URL builder as Flask's url_for."""
    adapter = routes.bind("localhost")

    def path(endpoint: str, *aliases: str, **parameters: str) -> str:
        # Werkzeug quotes URL values. Substitute TypeScript arguments only after
        # building so existing callers retain their runtime interpolation semantics.
        markers = {
            name: f"__browser_arg_{index}__" for index, name in enumerate(parameters)
        }
        paths: set[str] = set()
        for name in (endpoint, *aliases):
            try:
                rules = list(routes.iter_rules(name))
            except KeyError as error:
                raise ValueError(f"No registered Flask endpoint {name!r}.") from error
            matching = {
                rule.rule for rule in rules
                if not rule.build_only and rule.arguments == parameters.keys()
            }
            if len(matching) != 1:
                raise ValueError(
                    f"{name}: expected one route with parameters {sorted(parameters)}, "
                    f"found {sorted(matching)}."
                )
            paths.add(adapter.build(name, markers))
        if len(paths) != 1:
            raise ValueError(f"{(endpoint, *aliases)} no longer share a URL: {sorted(paths)}")
        value = paths.pop()
        if not value.startswith("/") or value.startswith("//"):
            raise ValueError(f"{endpoint}: browser helpers require a same-origin path.")
        value = value.replace("\\", "\\\\").replace("`", "\\`").replace("${", "\\${")
        for name, variable in parameters.items():
            marker = markers[name]
            if value.count(marker) != 1:
                raise ValueError(f"{endpoint}: cannot interpolate {name!r} as a string.")
            value = value.replace(marker, "${" + variable + "}")
        return value

    env = Environment(undefined=StrictUndefined, keep_trailing_newline=True)
    return env.from_string(template).render(path=path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check", action="store_true", help="Report stale output without writing."
    )
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    # The route map must be reproducible in CI and independent of the installation.
    os.environ.update(
        FLASK_ENV="testing",
        LAGNIAPPE_OFFLINE_WEB_TEST="1",
        LAGNIAPPE_CONFIG_ROOT=str(root / "testing/fixtures/offline-runtime"),
    )
    from lagniappe.web import app

    output = root / OUTPUT
    try:
        generated = render_endpoints(
            app.url_map, (root / TEMPLATE).read_text(encoding="utf-8")
        )
        if output.is_file() and output.read_text(encoding="utf-8") == generated:
            return 0
        if args.check:
            print(
                f"{OUTPUT} is stale or missing. Regenerate with "
                "venv/bin/python -m runner.browser_endpoints.",
                file=sys.stderr,
            )
            return 1
        output.parent.mkdir(parents=True, exist_ok=True)
        with TemporaryDirectory(dir=output.parent) as directory:
            candidate = Path(directory) / output.name
            candidate.write_text(generated, encoding="utf-8", newline="\n")
            candidate.replace(output)
    except (OSError, ValueError, BuildError, TemplateError) as error:
        print(f"Browser endpoint generation failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
