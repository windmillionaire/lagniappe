from flask import Blueprint


manual = Blueprint("manual", __name__)


from . import (
    main,
)

__all__ = ["manual"]
