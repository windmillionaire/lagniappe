from pathlib import Path

__test__ = False


def _find_testing_dir():
    current = Path.cwd()
    for directory in [current, *current.parents]:
        if (directory / "testing" / "pytest.ini").exists():
            return directory / "testing" / "files"
    raise FileNotFoundError("Could not find testing directory")


TEST_FILE_DIR = _find_testing_dir()

MIME_TYPES = {
    "csv": "text/csv",
    "txt": "text/plain",
    "json": "application/json",
    "pdf": "application/pdf",
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "gif": "image/gif",
    "webp": "image/webp",
}


class TestFile:
    def __init__(self, name):
        self.name = name

    @property
    def mime_type(self) -> str:
        """Get MIME type from filename extension."""
        ext = self.name.lower().split(".")[-1]

        return MIME_TYPES.get(ext, "application/octet-stream")

    @property
    def path(self) -> Path:
        """Get absolute path to the test file."""
        return TEST_FILE_DIR / self.name

    @property
    def content(self):
        """Get the content of the test file."""
        with open(self.path, "rb") as f:
            return f.read()

    def paste(self, page):
        page.evaluate(
            """async (data) => {
                    const blob = new Blob([new Uint8Array(data.content)], { type: data.type });
                    await navigator.clipboard.write([
                        new ClipboardItem({ [data.type]: blob })
                    ]);
                }""",
            {
                "content": list(self.content),
                "type": self.mime_type,
            },
        )

    def drop(self, target):
        target.evaluate(
            """(element, fileData) => {
                    const file = new File([new Uint8Array(fileData.content)], fileData.name, {
                        type: fileData.type
                    });
                    const dataTransfer = new DataTransfer();
                    dataTransfer.items.add(file);
                    
                    const dropEvent = new DragEvent('drop', {
                        bubbles: true,
                        cancelable: true,
                        dataTransfer: dataTransfer
                    });
                    element.dispatchEvent(dropEvent);
                }""",
            {
                "content": list(self.content),
                "name": self.name,
                "type": self.mime_type,
            },
        )

    def input(self, target):
        target.set_input_files(self.path)
