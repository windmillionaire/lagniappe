from flask import Blueprint

users = Blueprint("users", __name__)

from . import (
    main,
    login,
    groups,
)

__all__ = ["users"]
