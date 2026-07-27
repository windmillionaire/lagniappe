from flask import Blueprint

process = Blueprint("process", __name__)


from . import main

__all__ = ["process"]
