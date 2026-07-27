from flask import Blueprint

testing = Blueprint("testing", __name__)

from . import (
    main,
)

__all__ = ["testing"]
