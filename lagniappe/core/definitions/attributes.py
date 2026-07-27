"""Toggleable entity features (tasks, document, photo, etc.)."""

from enum import Enum


# @testable infrastructure
# @covered-by lagniappe/core/properties/common_entity.py::Attributes.value
class Attribute:
    """A toggleable feature on an entity (e.g. tasks, document, photo).

    Active if ``names`` is None (inherits all from model) or if this
    attribute's ``name`` is in the provided names list. Subclasses set
    ``name``, ``icon``, ``kind``, and ``title`` as class attributes.
    """

    def __init__(self, entity, names):
        default_kind = (
            entity.entity_kind if entity.entity_kind != "category" else "page"
        )
        self.kind = getattr(self, "kind", default_kind)
        self.entity_kind = entity.entity_kind

        # active is True if names is None (not defined, inherits from model) OR if this attribute's name is in names
        self.active = True if names is None or self.name in names else False


class ModelTasks(Attribute):
    """Attribute for projects that have model tasks (workflow definitions)."""

    name = "tasks"
    icon = "task"
    kind = "task"
    title = "Model Tasks"


class Document(Attribute):
    """Attribute for entities that have an associated document/page content."""

    name = "document"
    icon = "document"
    title = "Document"


class Tasks(Attribute):
    """Attribute for entities that can have child tasks."""

    name = "tasks"
    icon = "task"
    kind = "task"
    title = "Tasks"


class Photo(Attribute):
    """Attribute for entities that can have a photo/image."""

    name = "photo"
    icon = "image"
    kind = "page"
    title = "Photo"


class Notes(Attribute):
    """Attribute for entities that can have attached notes."""

    name = "notes"
    icon = "notes"
    kind = "note"
    title = "Notes"


class Files(Attribute):
    """Attribute for entities that can have attached files."""

    name = "files"
    icon = "file"
    kind = "file"
    title = "Files"


class ProjectAttributes(Enum):
    """Available attributes for Project entities."""

    tasks = ModelTasks
    document = Document


class PageAttributes(Enum):
    """Available attributes for Page entities."""

    tasks = Tasks
    document = Document
    photo = Photo
    notes = Notes
    files = Files


class CategoryAttributes(Enum):
    """Available attributes for Category entities."""

    tasks = Tasks
    document = Document
    photo = Photo
    notes = Notes
    files = Files


# @testable infrastructure
# @covered-by lagniappe/core/properties/common_entity.py::Attributes.value
class EntityAttributes(Enum):
    """Maps entity kinds to their available attribute enums."""

    project = ProjectAttributes
    page = PageAttributes
    category = CategoryAttributes
    users = CategoryAttributes

    # @testable false
    # @covered-by lagniappe/core/properties/common_entity.py::Attributes.value
    # @reason entity attribute initialization is owned by the Attributes property
    def initialize(self, entity, attribute_names=None):
        """Create Attribute instances for an entity (None = activate all)."""
        return [attr_class.value(entity, attribute_names) for attr_class in self.value]
