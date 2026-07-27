from enum import EnumMeta


# @testable infrastructure
class DefaultEnum(EnumMeta):
    """
    Enum metaclass that returns a DEFAULT value instead of raising KeyError.

    Used by enums like IngressStage and Action where a safe default is needed.
    """

    def __getitem__(cls, name):
        try:
            return super().__getitem__(name)
        except KeyError:
            return cls.DEFAULT
