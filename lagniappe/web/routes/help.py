"""Signed-in, source-backed application reference pages."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from flask.typing import ResponseReturnValue

from flask import Blueprint, abort, render_template

from lagniappe.reference import get_topic, grouped_topics
from lagniappe.web.auth import logged_in

help_pages = Blueprint("help", __name__)


@help_pages.route("/")
@logged_in
def index() -> ResponseReturnValue:
    return render_template("help/index.html", groups=grouped_topics())


@help_pages.route("/<topic_id>")
@logged_in
def article(topic_id: str) -> ResponseReturnValue:
    try:
        topic = get_topic(topic_id)
    except KeyError:
        abort(404)
    return render_template("help/page.html", topic=topic)
