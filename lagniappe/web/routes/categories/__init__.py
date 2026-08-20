from flask import Blueprint


categories = Blueprint("categories", __name__)


from . import (
    main,
)

__all__ = ["categories"]
