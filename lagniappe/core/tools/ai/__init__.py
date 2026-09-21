"""Explicit startup entry point for AI services.

Import feature operations from their owning modules. Keeping this package free
of eager workflow imports lets shared policy and contracts load independently.
"""


# @testable false
# @covered-by lagniappe/core/tools/ai/core.py::GenAI.initialize
# @reason package-level convenience wrapper around provider client initialization
def initialize():
    from .core import ai_model

    ai_model.initialize()


__all__ = ["initialize"]
