from flask import Blueprint

pages = Blueprint("pages", __name__)

from . import (
    main,
    notes,
)

__all__ = ["pages"]
