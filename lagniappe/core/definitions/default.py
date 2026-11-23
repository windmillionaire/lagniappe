from enum import Enum, EnumMeta


# @testable infrastructure
def _get_default_member[Member: Enum](self: type[Member], name: str) -> Member:
    try:
        return EnumMeta.__getitem__(self, name)
    except KeyError:
        return EnumMeta.__getitem__(self, "DEFAULT")


class DefaultEnum(EnumMeta):
    """
    Enum metaclass that returns a DEFAULT value instead of raising KeyError.

    Used by enums like IngressStage and Action where a safe default is needed.
    """

    __getitem__ = _get_default_member
