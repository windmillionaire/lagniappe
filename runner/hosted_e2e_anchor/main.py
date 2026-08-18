"""Inert traffic-owning version for the App Engine E2E service."""


def app(environ, start_response):
    body = b"Not Found\n"
    start_response(
        "404 Not Found",
        [
            ("Content-Type", "text/plain; charset=utf-8"),
            ("Content-Length", str(len(body))),
            ("Cache-Control", "no-store"),
            ("X-Robots-Tag", "noindex, nofollow"),
        ],
    )
    return [body]
