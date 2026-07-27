from flask import Blueprint

reference = Blueprint("reference", __name__)

from . import main