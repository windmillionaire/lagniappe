"""Narrow external webhook routes."""

from flask import Blueprint


webhooks = Blueprint("webhooks", __name__)

from . import main  # noqa: E402,F401


__all__ = ["webhooks"]
