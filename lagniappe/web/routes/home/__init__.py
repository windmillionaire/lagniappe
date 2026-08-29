from flask import Blueprint

home = Blueprint("home", __name__)
internal = Blueprint("internal", __name__)


from . import (
    admin,
    preview,
    search,
    site,
    main,
    poll,
    public,
    refresh,
    sync,
)

__all__ = ["home", "internal"]
