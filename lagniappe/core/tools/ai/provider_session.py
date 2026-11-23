"""Generation-owned asynchronous requests behind the synchronous planner."""

import asyncio
from contextvars import ContextVar
from typing import TYPE_CHECKING, TypedDict, Unpack

if TYPE_CHECKING:
    from lagniappe.core.tools.deferred_jobs.control import DeferredExecutionControl

from google import genai
from google.genai import types

from lagniappe import CONFIG

from .provider_policy import is_provider_transient_error, retry_http_options


class ContentRequest(TypedDict):
    """Exactly the request fields shared by sync and cancellable generation."""

    model: str
    contents: types.ContentListUnionDict
    config: types.GenerateContentConfig


current_session: ContextVar[ProviderSession | None] = ContextVar("ai_provider_session", default=None)
MIN_PROVIDER_RETRY_SECONDS = 30


# @testable true
# @tests tests_unit/test_015c_provider_session.py::test_blocked_request_is_cancelled_and_closed
# @tests tests_unit/test_015c_provider_session.py::test_transient_retry_preserves_request_and_uses_one_budget
# @tests tests_unit/test_015c_provider_session.py::test_transient_error_does_not_retry_with_too_little_time
# @matrix ai : cancellation deadline retry-ownership service-tier
class ProviderSession:
    """Own the client and loop; never leave a blocked request in a worker thread."""

    def __init__(self, control: DeferredExecutionControl) -> None:
        self.control = control
        self.runner = asyncio.Runner()
        self.client: genai.Client | None = None

    def request(self, **kwargs: Unpack[ContentRequest]) -> types.GenerateContentResponse:
        return self.runner.run(self._request(kwargs))

    async def _request(self, kwargs: ContentRequest) -> types.GenerateContentResponse:
        self.control.ensure_active()
        if self.client is None:
            self.client = genai.Client(
                project=CONFIG.GOOGLE_CLOUD_PROJECT,
                location=CONFIG.AI_LOCATION,
                vertexai=True,
                credentials=CONFIG.google_credentials,
                http_options=types.HttpOptions(
                    api_version="v1",
                    retry_options=types.HttpRetryOptions(attempts=1),
                ),
            )
        while True:
            config = kwargs["config"].model_copy(deep=True)
            headers = getattr(getattr(config, "http_options", None), "headers", None)
            config.http_options = retry_http_options(attempts=1, headers=headers)
            config.http_options.timeout = max(1, int(self.control.remaining_seconds * 1000))
            task = asyncio.create_task(self.client.aio.models.generate_content(
                model=kwargs["model"], contents=kwargs["contents"], config=config,
            ))
            try:
                while not task.done():
                    await asyncio.wait({task}, timeout=min(1, self.control.remaining_seconds))
                    self.control.ensure_active()
                return task.result()
            except Exception as error:
                self.control.ensure_active()
                if (
                    not is_provider_transient_error(error)
                    or self.control.remaining_seconds < MIN_PROVIDER_RETRY_SECONDS
                    or not self.control.claim_provider_retry()
                ):
                    raise
            finally:
                if not task.done():
                    task.cancel()
                await asyncio.gather(task, return_exceptions=True)

    def close(self):
        try:
            if self.client is not None:
                try:
                    self.runner.run(self._close_client())
                finally:
                    self.client.close()
        finally:
            self.runner.close()

    async def _close_client(self) -> None:
        if self.client is not None:
            await asyncio.wait_for(self.client.aio.aclose(), timeout=2)
