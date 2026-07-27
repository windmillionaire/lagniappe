from enum import Enum

from ..resources import File

from .base import ResourceEnumMixin
from .file_definitions import create_file


class Files(ResourceEnumMixin, Enum):
    test_create_file = File(definition=create_file)
