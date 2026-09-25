"""Experiments-only request headers and structured measurements."""

import os
import time

from flask import before_render_template, g, request, template_rendered

from lagniappe.core.tools import measurements


# @testable true
# @tests tests_e2e/013_agent_api/test_013g_experiments.py::test_experiments_request_headers_and_private_log_summary
# @matrix experiments : request-measurements
def initialize_measurements(app, config):
    """Register first so the timing response hook runs after all other hooks."""
    if not config.EXPERIMENTS_ENABLED or config.EXPERIMENTS_DIAGNOSTICS == "off":
        return

    # @testable false
    # @covered-by lagniappe/web/experiments.py::initialize_measurements
    # @reason begin request-local collection before authentication and CSRF checks
    @app.before_request
    def begin():
        g.experiments_measurement = measurements.Measurement(
            config.EXPERIMENTS_DIAGNOSTICS
        )
        g.experiments_token = measurements.CURRENT.set(g.experiments_measurement)

    # @testable false
    # @covered-by lagniappe/web/experiments.py::initialize_measurements
    # @reason response metadata deliberately excludes request paths and contents
    @app.after_request
    def finish(response):
        measurement = getattr(g, "experiments_measurement", None)
        if measurement is None:
            return response
        summary = measurement.summary()
        summary.update(
            method=request.method,
            route=request.url_rule.rule if request.url_rule else "unmatched",
            status=response.status_code,
            request_bytes=request.content_length,
            response_bytes=response.content_length,
            streamed=response.is_streamed,
            source_id=config.EXPERIMENTS_SOURCE_ID or None,
            version=os.environ.get("GAE_VERSION"),
            instance=os.environ.get("GAE_INSTANCE"),
        )
        response.headers["X-Lagniappe-Request-ID"] = measurement.request_id
        response.headers["Server-Timing"] = f"lagniappe;dur={summary['app_ms']}"
        if config.EXPERIMENTS_SOURCE_ID:
            response.headers["X-Lagniappe-Source-ID"] = config.EXPERIMENTS_SOURCE_ID
        measurements.emit(summary)
        g.experiments_logged = True
        return response

    # @testable false
    # @covered-by lagniappe/web/experiments.py::initialize_measurements
    # @reason restore the context even when Flask does not produce a response
    @app.teardown_request
    def cleanup(error):
        token = g.pop("experiments_token", None)
        if token is not None:
            if not g.pop("experiments_logged", False):
                summary = g.experiments_measurement.summary()
                summary.update(
                    status=500,
                    route=request.url_rule.rule if request.url_rule else "unmatched",
                    source_id=config.EXPERIMENTS_SOURCE_ID or None,
                )
                measurements.emit(summary)
            measurements.CURRENT.reset(token)

    # @testable false
    # @covered-by lagniappe/web/experiments.py::initialize_measurements
    # @reason pair Flask template signals without storing template context values
    def template_start(sender, **kwargs):
        g.setdefault("experiments_template_stack", []).append(time.perf_counter())

    # @testable false
    # @covered-by lagniappe/web/experiments.py::initialize_measurements
    # @reason template durations can overlap other measured provider operations
    def template_end(sender, **kwargs):
        stack = g.get("experiments_template_stack", [])
        measurement = measurements.CURRENT.get()
        if stack and measurement:
            measurement.record("template", "render", stack.pop())

    before_render_template.connect(template_start, app, weak=False)
    template_rendered.connect(template_end, app, weak=False)
