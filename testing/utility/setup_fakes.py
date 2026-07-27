"""Small fakes for setup unit tests."""

from dataclasses import dataclass, field
from subprocess import CompletedProcess


@dataclass
class FakeResponse:
    status_code: int = 200
    json_data: dict | list | None = None
    text: str | None = None

    def __post_init__(self):
        if self.text is None:
            self.text = "ok" if self.json_data is not None else ""

    def json(self):
        if self.json_data is None:
            return {}
        return self.json_data


@dataclass
class FakeSession:
    responses: list[FakeResponse] = field(default_factory=list)
    calls: list[dict] = field(default_factory=list)

    def _next_response(self):
        if self.responses:
            return self.responses.pop(0)
        return FakeResponse()

    def get(self, url, **kwargs):
        self.calls.append({"method": "GET", "url": url, **kwargs})
        return self._next_response()

    def post(self, url, **kwargs):
        self.calls.append({"method": "POST", "url": url, **kwargs})
        return self._next_response()

    def patch(self, url, **kwargs):
        self.calls.append({"method": "PATCH", "url": url, **kwargs})
        return self._next_response()


@dataclass
class SpinnerRecorder:
    messages: list[str] = field(default_factory=list)
    oks: list[str] = field(default_factory=list)
    fails: list[str] = field(default_factory=list)

    def write(self, message):
        self.messages.append(message)

    def ok(self, mark):
        self.oks.append(mark)

    def fail(self, mark):
        self.fails.append(mark)


def spinner_factory(spinner=None):
    spinner = spinner or SpinnerRecorder()

    class _SpinnerContext:
        def __enter__(self):
            return spinner

        def __exit__(self, exc_type, exc, tb):
            return False

    return lambda **kwargs: _SpinnerContext()


def completed_process(args=None, returncode=0, stdout="", stderr=""):
    return CompletedProcess(args or [], returncode, stdout=stdout, stderr=stderr)
