from flask import Blueprint

forms = Blueprint("forms", __name__)

from . import (
    main,
)

__all__ = ["forms"]
