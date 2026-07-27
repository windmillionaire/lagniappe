from flask import Blueprint

filters = Blueprint("filters", __name__)

from . import (
    main,
)

__all__ = ["filters"]
