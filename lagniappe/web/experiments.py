"""Experiments-only request headers and structured measurements."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence
    from flask import Flask, Response
    from google.cloud.datastore import Key
    from lagniappe import Config

import os
import time

from flask import before_render_template, g, request, template_rendered

from lagniappe import CONFIG
from lagniappe.core.tools import measurements
from lagniappe.core.tools.polling import task_lists


def task_list_context_keys() -> Sequence[Key]:
    """Select equivalent read schedules for an opt-in, same-instance trial."""
    variant = request.headers.get("X-Lagniappe-Experiments-Task-List")
    if CONFIG.EXPERIMENTS_ENABLED and variant in ("batched", "unbatched"):
        g.experiments_variant = f"p5-01:{variant}"
        if variant == "unbatched":
            return ()
    return task_lists.snapshot_keys()


def initialize_measurements(app: Flask, config: Config) -> None:
    """Register first so the timing response hook runs after all other hooks."""
    if not config.EXPERIMENTS_ENABLED or config.EXPERIMENTS_DIAGNOSTICS == "off":
        return

    @app.before_request
    def begin() -> None:
        mode = config.EXPERIMENTS_DIAGNOSTICS
        if request.endpoint == "projects.status" and request.method == "GET":
            variant = request.headers.get("X-Lagniappe-Experiments-Project-Stage")
            if variant in ("reuse", "reload"):
                g.experiments_variant = f"project-stage:{variant}"
                mode = "trace"
        g.experiments_measurement = measurements.Measurement(mode)
        g.experiments_token = measurements.CURRENT.set(g.experiments_measurement)

    @app.after_request
    def finish(response: Response) -> Response:
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
        if variant := g.get("experiments_variant"):
            summary.update(experiment=variant, process=os.getpid())
            response.headers["X-Lagniappe-Experiment"] = variant
        response.headers["X-Lagniappe-Request-ID"] = measurement.request_id
        response.headers["Server-Timing"] = f"lagniappe;dur={summary['app_ms']}"
        if config.EXPERIMENTS_SOURCE_ID:
            response.headers["X-Lagniappe-Source-ID"] = config.EXPERIMENTS_SOURCE_ID
        measurements.emit(summary)
        g.experiments_logged = True
        return response

    @app.teardown_request
    def cleanup(error: BaseException | None) -> None:
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

    def template_start(sender: Flask, **kwargs: object) -> None:
        g.setdefault("experiments_template_stack", []).append(time.perf_counter())

    def template_end(sender: Flask, **kwargs: object) -> None:
        stack = g.get("experiments_template_stack", [])
        measurement = measurements.CURRENT.get()
        if stack and measurement:
            measurement.record("template", "render", stack.pop())

    before_render_template.connect(template_start, app, weak=False)
    template_rendered.connect(template_end, app, weak=False)
