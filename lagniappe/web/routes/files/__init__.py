from flask import Blueprint

files = Blueprint("files", __name__)


from . import ingress, main

__all__ = ["files"]
