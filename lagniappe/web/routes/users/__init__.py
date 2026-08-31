from flask import Blueprint

users = Blueprint("users", __name__)

from . import (
    main,
    login,
    groups,
    api_key,
)

__all__ = ["users"]
