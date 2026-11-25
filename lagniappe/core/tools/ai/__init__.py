"""Explicit startup entry point for AI services.

Import feature operations from their owning modules. Keeping this package free
of eager workflow imports lets shared policy and contracts load independently.
"""


def initialize() -> None:
    from .core import ai_model

    ai_model.initialize()


__all__ = ["initialize"]
