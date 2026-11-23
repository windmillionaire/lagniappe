from collections.abc import Mapping
from typing import TYPE_CHECKING, cast

from ..exceptions import PropertyError

if TYPE_CHECKING:
    from ..entities.entity import Entity


class ProcessProperty[Owner: Entity = "Entity"]:
    """Property backed by a JSON process section in entity.db.

    Stores multi-step workflow state (ingress stages, file options, etc.).
    Subclasses must set ``process_id``, ``section_id``, and ``attributes``
    (a tuple of attribute names accessible via __getattr__/__setattr__).

    Get:
        section (dict): The raw dict for this section within the process.
        error (str | None): Error message if the process step failed.
        complete (bool): Whether this step has completed successfully.
    """

    attributes: tuple[str, ...] = ()

    def __init__(
        self, *args: object, entity: Owner | None = None, **kwargs: object
    ) -> None:
        process_id = getattr(type(self), "process_id", None)
        section_id = getattr(type(self), "section_id", None)
        attributes = getattr(type(self), "attributes", None)

        if not process_id:
            raise NotImplementedError(f"{type(self).__name__} requires process_id")
        if not section_id:
            raise NotImplementedError(f"{type(self).__name__} requires section_id")
        if not isinstance(attributes, tuple):
            raise TypeError("attributes must be a tuple")

        if entity is None:
            raise AttributeError("A process property requires an entity with get_process")
        self.entity = entity
        self.id = section_id
        self.root_process = self.entity.get_process(process_id)
        # The process stores each declared section as its own mutable mapping.
        self._value = cast("dict[str, object]", self.root_process.setdefault(section_id, {}))

    @property
    def section(self) -> dict[str, object]:
        return self._value

    @section.setter
    def section(self, value: dict[str, object] | None) -> None:
        self._value.clear()
        if isinstance(value, dict):
            self._value.update({k.replace("_", "-"): v for k, v in value.items()})

    def update(self, form_data: Mapping[str, object]) -> dict[str, object] | bool | None:
        """Apply stage inputs. Subclasses can report the saved section or a change flag."""
        self.section = {**form_data}

    def clear(self) -> None:
        self.section = None

    @property
    def error(self) -> object:
        return self.section.get("error")

    @error.setter
    def error(self, value: object) -> None:
        self.section["error"] = value
        self.section.pop("complete", None)

    @property
    def complete(self) -> object:
        return self.section.get("complete")

    @complete.setter
    def complete(self, value: object) -> None:
        self.section["complete"] = value
        self.section.pop("error", None)

    def __getattr__(self, attr: str) -> object:
        if attr.replace("-", "_") in self.attributes:
            return self._value.get(attr.replace("_", "-"))

        raise PropertyError(
            f"'{type(self).__name__}' has no attribute '{attr}'",
            entity=self.entity,
        )

    def __setattr__(self, attr: str, value: object) -> None:
        if attr not in self.attributes:
            super().__setattr__(attr, value)
        else:
            section_name = attr.replace("_", "-")
            if value is not None:
                self._value[section_name] = value
            elif section_name in self._value:
                self._value.pop(section_name)
