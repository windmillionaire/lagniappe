from .field_host import FieldHost

class DetailsMixin(FieldHost):
    """Adds API detail output. Collected by Entity.details.

    Provides:
        details_value: Value for the details dict (default: self.value).
        details_key (str): Key in the details dict (default: self.id).
    """

    @property
    def details_value(self) -> object:
        return self.value

    @property
    def details_key(self) -> str:
        return self.id
