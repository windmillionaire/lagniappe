from flask import Blueprint


messages = Blueprint("messages", __name__)
message_internal = Blueprint("message_internal", __name__)

from . import main

__all__ = ["messages", "message_internal"]
