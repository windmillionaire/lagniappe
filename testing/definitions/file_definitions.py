from dataclasses import dataclass


@dataclass
class FileDefinition:
    name: str
    description: str = ""
    form: bool = False
    origin: str = "page"  # page, home


create_file = FileDefinition(
    name="Test File",
    description="A test file.",
    origin="page",
)
