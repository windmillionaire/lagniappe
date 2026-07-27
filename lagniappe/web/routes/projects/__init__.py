from flask import Blueprint

projects = Blueprint("projects", __name__)

from . import (
    main,
    tasks,
)

__all__ = ["projects"]
