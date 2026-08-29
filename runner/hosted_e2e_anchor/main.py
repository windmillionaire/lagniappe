"""Inert traffic-owning version for the App Engine E2E service."""


# @testable true
# @tests tests_tooling/test_009_hosted_e2e.py::test_hosted_anchor_marks_every_rejection
# @matrix hosted-e2e : anchor deletion-safety soft-routing
def app(environ, start_response):
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
