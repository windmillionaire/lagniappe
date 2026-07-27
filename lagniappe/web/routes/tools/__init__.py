from flask import Blueprint

tools = Blueprint("tools", __name__)

from . import main

__all__ = ["tools"]
