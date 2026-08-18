from flask import Blueprint

testing = Blueprint("testing", __name__)

from . import main  # noqa: E402, F401

__all__ = ["testing"]
