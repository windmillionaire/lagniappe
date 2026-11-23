"""Inert traffic-owning version for the App Engine E2E service."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from _typeshed.wsgi import StartResponse


def app(environ: dict[str, object], start_response: StartResponse) -> list[bytes]:
    body = b"Not Found\n"
    start_response(
        "404 Not Found",
        [
            ("Content-Type", "text/plain; charset=utf-8"),
            ("Content-Length", str(len(body))),
            ("Cache-Control", "no-store"),
            ("X-Robots-Tag", "noindex, nofollow"),
            ("X-Lagniappe-Hosted-E2E-Guard", "active"),
            ("X-Lagniappe-Hosted-E2E-Anchor", "active"),
        ],
    )
    return [body]
