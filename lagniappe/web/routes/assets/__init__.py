from flask import Blueprint


assets = Blueprint("assets", __name__)


from . import (
    editor,
    page,
    main,
)

__all__ = ["assets"]
