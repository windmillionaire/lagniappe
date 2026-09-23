"""Gemini AI client wrapper for content and image generation."""

from io import BytesIO
import json
import re

from google import genai
from google.genai import types

from lagniappe import CONFIG

from ... import exceptions
from .settings import runtime_ai_settings
from .provider_policy import (
    is_provider_quota_error as is_provider_quota_error,
    is_provider_transient_error as is_provider_transient_error,
    provider_error_details as provider_error_details,
    provider_error_message as provider_error_message,
    retry_http_options as retry_http_options,
)
from .provider_session import ProviderSession, current_session
from .functions import (
    FUNCTION_TOOL,
    MAX_TOOL_ITERATIONS,
    build_function_tool,
    execute_function_calls,
    summarize_function_calls,
)
from .debug import ai_debug, debug_log, enabled as debug_enabled
from .observability import (
    GenerationObserver,
    current_execution_control,
    current_observer,
    mark_outcome,
)

MINIMUM_SAFETY_SETTINGS = [
    types.SafetySetting(
        category=types.HarmCategory.HARM_CATEGORY_HATE_SPEECH,
        threshold=types.HarmBlockThreshold.BLOCK_ONLY_HIGH,
    ),
    types.SafetySetting(
        category=types.HarmCategory.HARM_CATEGORY_HARASSMENT,
        threshold=types.HarmBlockThreshold.BLOCK_ONLY_HIGH,
    ),
    types.SafetySetting(
        category=types.HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT,
        threshold=types.HarmBlockThreshold.BLOCK_ONLY_HIGH,
    ),
    types.SafetySetting(
        category=types.HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT,
        threshold=types.HarmBlockThreshold.BLOCK_ONLY_HIGH,
    ),
]

GOOGLE_SEARCH_TOOL = [types.Tool(google_search=types.GoogleSearch())]


TYPE_REGEX = re.compile(r"```(json|html|text)\s*([\s\S]*?)\s*```", re.MULTILINE)
REFERENCE_REGEX = re.compile(r"\[(?:\d+(?:\s*(?:,|-)\s*\d+)*)\]")

MODEL = CONFIG.AI_MODEL
UTILITY_MODEL = getattr(CONFIG, "AI_UTILITY_MODEL", MODEL)
IMAGE_MODEL = CONFIG.AI_IMAGE_MODEL
IMAGE_RESPONSE_MODALITIES = ["TEXT", "IMAGE"]
EMPTY_TEXT_RESPONSE_MESSAGE = "Model returned no text content."
BLOCKED_FINISH_REASONS = {
    "BLOCKED",
    "BLOCKLIST",
    "IMAGE_PROHIBITED_CONTENT",
    "IMAGE_SAFETY",
    "PROHIBITED_CONTENT",
    "SAFETY",
    "SPII",
}
EMPTY_FINISH_REASONS = {"FINISH_REASON_UNSPECIFIED", "STOP"}
EMPTY_TEXT_RETRY_ATTEMPTS = 2
DEFERRED_AI_RETRY_ATTEMPTS = 2


# @testable false
# @covered-by lagniappe/core/tools/ai/provider_policy.py::is_provider_quota_error
# @reason wrapper message is exercised through provider quota tests
def _raise_provider_error(error):
    if is_provider_quota_error(error):
        details = provider_error_details(error)
        context = {
            "ai_provider": {
                "quota_exhausted": True,
                "code": details.get("code"),
                "status": details.get("status"),
                "message": details.get("message"),
            }
        }
        raise exceptions.AIQuotaError(
            "AI quota is temporarily exhausted. The report can retry shortly.",
            context=context,
        ) from error
    raise error


# @testable false
# @covered-by lagniappe/core/tools/ai/core.py::GenAI.generate_image
# @reason private model-routing branch for image provider selection
def _is_imagen_model(model):
    return str(model or "").startswith("imagen-")


# @testable false
# @covered-by lagniappe/core/tools/ai/core.py::GenAI._generate_imagen_image
# @reason private prompt adapter for Imagen's text-only request shape
def _image_prompt_text(prompt):
    return "\n\n".join(part for part in (prompt.intro, prompt.build()) if part)


# @testable false
# @covered-by lagniappe/core/tools/ai/core.py::GenAI._extract_text
# @covered-by lagniappe/core/tools/ai/core.py::GenAI.generate_image
# @reason provider enum normalization is asserted through text and image extraction
def _finish_reason_name(reason):
    """Normalize SDK enum and string finish reasons to their provider value."""
    if reason is None:
        return None
    value = getattr(reason, "value", reason)
    return str(value).rsplit(".", 1)[-1].upper()


# @testable true
# @tests tests_unit/test_015_ai_tools.py::test_ai_model_cleanup_extracts_json_text_and_blocked_responses
# @matrix ai : citations cleanup
def clean_json_references(obj):
    """Recursively remove numeric reference citations from JSON strings."""
    if isinstance(obj, dict):
        return {k: clean_json_references(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [clean_json_references(item) for item in obj]
    elif isinstance(obj, str):
        return REFERENCE_REGEX.sub(r"", obj)
    return obj


# @testable true
# @tests tests_unit/test_015_ai_tools.py::test_ai_model_cleanup_extracts_json_text_and_blocked_responses
# @matrix ai : cleanup json-extraction
def extract_first_json_value(response_text):
    """Return the first balanced JSON object or array from model output."""
    start = next(
        (index for index, char in enumerate(response_text) if char in "{["),
        None,
    )
    if start is None:
        return None

    stack = []
    in_string = False
    escaped = False
    for index, char in enumerate(response_text[start:], start):
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue

        if char == '"':
            in_string = True
        elif char in "{[":
            stack.append("}" if char == "{" else "]")
        elif char in "}]":
            if not stack or stack[-1] != char:
                return None
            stack.pop()
            if not stack:
                return response_text[start : index + 1]

    return None


# @testable infrastructure
class GenAI:
    """Singleton wrapper around the Google GenAI client for Vertex AI."""

    _client = None

    @property
    def client(self):
        if not self._client:
            self.initialize()
        return self._client

    # @testable infrastructure
    @classmethod
    def initialize(cls):
        """Initialize the GenAI client if not already connected."""
        if cls._client:
            return

        client_kwargs = {
            "project": CONFIG.GOOGLE_CLOUD_PROJECT,
            "location": CONFIG.AI_LOCATION,
            "vertexai": True,
            "http_options": retry_http_options(api_version="v1"),
        }
        client_kwargs["credentials"] = CONFIG.google_credentials

        cls._client = genai.Client(**client_kwargs)

    # @testable true
    # @tests tests_unit/test_015_ai_tools.py::test_ai_model_cleanup_extracts_json_text_and_blocked_responses
    # @matrix ai : citations cleanup
    @staticmethod
    def cleanup(response_text, output_format):
        """Strip code fences and numeric reference citations from model output.

        Args:
            response_text: Raw text from the model response.
            output_format: Expected format ("JSON" or other) for parsing.

        Returns:
            Parsed JSON object or cleaned text string.
        """
        response_text = TYPE_REGEX.sub(r"\2", response_text).strip()
        if output_format == "JSON":
            try:
                result = json.loads(response_text)
            except json.JSONDecodeError as exc:
                extracted_json = extract_first_json_value(response_text)
                if extracted_json and extracted_json != response_text:
                    try:
                        result = json.loads(extracted_json)
                    except json.JSONDecodeError:
                        pass
                    else:
                        return clean_json_references(result)
                raise exceptions.AIException(
                    f"Invalid JSON response from model. AI response: {response_text}"
                ) from exc
            result = clean_json_references(result)
        else:
            result = REFERENCE_REGEX.sub(r"", response_text)
        return result

    # @testable true
    # @tests tests_unit/test_015_ai_tools.py::test_ai_config_combines_search_tools_json_and_thinking_settings
    # @tests tests_unit/test_015_ai_tools.py::test_deferred_ai_config_uses_short_sdk_retry_profile
    # @tests tests_unit/test_015_ai_tools.py::test_ai_model_tier_routes_generation_to_primary_or_utility_model
    # @matrix ai : config output-format retry-config retry-ownership search service-tier thinking tools
    @staticmethod
    def create_config(prompt, **overrides):
        """Build a GenerateContentConfig from a Prompt's settings."""
        execution_control = current_execution_control()
        service_tier_headers = (
            {
                "X-Vertex-AI-LLM-Request-Type": "shared",
                "X-Vertex-AI-LLM-Shared-Request-Type": prompt.service_tier,
            }
            if prompt.service_tier in {"priority", "flex"}
            else None
        )
        config = {
            "http_options": retry_http_options(
                attempts=(DEFERRED_AI_RETRY_ATTEMPTS if execution_control else None),
                headers=service_tier_headers,
            ),
            "safety_settings": MINIMUM_SAFETY_SETTINGS,
        }
        if prompt.intro:
            config["system_instruction"] = prompt.intro

        # Google Search and function declarations must live on one types.Tool; separate
        # Tool entries disable AFC and can yield UNEXPECTED_TOOL_CALL for google_search
        # on follow-up turns (see googleapis/python-genai#58).
        function_tool = None
        if prompt.tools:
            if isinstance(prompt.tools, list):
                function_tool = build_function_tool(*prompt.tools)
            else:
                function_tool = FUNCTION_TOOL

        if prompt.search and function_tool:
            config["tools"] = [
                types.Tool(
                    google_search=types.GoogleSearch(),
                    function_declarations=function_tool.function_declarations,
                )
            ]
        elif prompt.search:
            config["tools"] = list(GOOGLE_SEARCH_TOOL)
        elif function_tool:
            config["tools"] = [function_tool]

        if prompt.thinking_budget is not None:
            config["thinking_config"] = types.ThinkingConfig(
                thinking_budget=prompt.thinking_budget
            )

        output_type = prompt.output_format.get("type") if prompt.output_format else None
        if output_type == "JSON":
            config["response_mime_type"] = "application/json"
            if prompt.response_schema:
                config["response_schema"] = prompt.response_schema

        config.update(overrides)
        return types.GenerateContentConfig(**config)

    # @testable true
    # @tests tests_unit/test_015_ai_tools.py::test_ai_model_tier_routes_generation_to_primary_or_utility_model
    # @tests tests_unit/test_015_ai_tools.py::test_ai_tool_json_generation_pins_runtime_model_through_structured_final_pass
    # @matrix ai : model-routing request-pinning runtime-settings
    @staticmethod
    def _model_for_prompt(prompt, settings=None):
        """Choose the configured text model for a prompt's requested tier."""
        settings = settings or runtime_ai_settings()
        if prompt.model_tier == "utility":
            return settings["AI_UTILITY_MODEL"]
        return settings["AI_MODEL"]

    # @testable true
    # @tests tests_unit/test_015b_ai_prompt_builders.py::test_prompt_tracks_context_output_examples_and_attachments
    # @matrix ai : attachments prompt
    def _build_contents(self, prompt):
        contents = [prompt.build()]
        for data in prompt.bytes:
            contents.append(
                types.Part.from_bytes(data=data["bytes"], mime_type=data["mime_type"])
            )
        for file in prompt.files:
            contents.append(
                types.Part.from_uri(file_uri=file["uri"], mime_type=file["mime_type"])
            )
        return contents

    # @testable true
    # @tests tests_unit/test_015_ai_tools.py::test_ai_model_cleanup_extracts_json_text_and_blocked_responses
    # @tests tests_unit/test_015_ai_tools.py::test_ai_accepts_empty_json_object_without_retry
    # @matrix ai : empty-json response-extraction safety
    @staticmethod
    def _extract_text(response, output_format):
        if response.candidates:
            candidate = response.candidates[0]

            finish = _finish_reason_name(
                getattr(candidate, "finish_reason", None)
            )
            if finish in BLOCKED_FINISH_REASONS:
                raise exceptions.AIException(
                    f"Content generation blocked. Reason: {finish}"
                )

            if candidate.content and candidate.content.parts:
                text_parts = [
                    p.text
                    for p in candidate.content.parts
                    if hasattr(p, "text") and p.text
                ]
                if text_parts:
                    result = GenAI.cleanup("\n".join(text_parts), output_format)
                    if output_format == "JSON" or result:
                        return result

            if finish and finish not in EMPTY_FINISH_REASONS:
                raise exceptions.AIException(
                    f"Content generation ended without text. Reason: {finish}"
                )

        return None

    # @testable true
    # @tests tests_unit/test_015_ai_tools.py::test_ai_model_tier_routes_generation_to_primary_or_utility_model
    # @tests tests_unit/test_015_ai_tools.py::test_ai_retries_empty_text_response_once
    # @tests tests_unit/test_015_ai_tools.py::test_ai_accepts_empty_json_object_without_retry
    # @tests tests_unit/test_015_ai_tools.py::test_autofill_accepts_summary_backed_json_without_tool_or_final_call
    # @tests tests_unit/test_015_ai_tools.py::test_ai_search_json_generation_keeps_provider_response_unconstrained
    # @tests tests_unit/test_015_ai_tools.py::test_ai_provider_quota_error_is_wrapped_for_tool_loop
    # @matrix ai : output-format provider-errors quota search tool-loop
    # @matrix ai : empty-response-retry model-routing site-policy provider-boundary
    def generate_content(self, prompt, *, validator=None, validation_retries=0):
        """Generate and optionally validate text under one observable call boundary."""
        if not CONFIG.AI_ENABLED:
            raise exceptions.AIException("AI is disabled for this installation.")
        observer = GenerationObserver(prompt)
        token = observer.install()
        terminal_error = None
        control = current_execution_control()
        session = ProviderSession(control) if (
            getattr(control, "report_planning", False)
            or getattr(control, "cancellable_provider", False)
        ) else None
        session_token = current_session.set(session)
        try:
            settings = runtime_ai_settings()
            model = GenAI._model_for_prompt(prompt, settings=settings)
            observer.resolution(model=model, location=settings.get("AI_LOCATION"))
            for attempt in range(EMPTY_TEXT_RETRY_ATTEMPTS):
                try:
                    if validation_retries:
                        result = self._generate_content_once(
                            prompt, model=model, validator=validator,
                            validation_retries=validation_retries,
                        )
                    else:
                        result = self._generate_content_once(prompt, model=model)
                    if not validation_retries:
                        observer.provider_result(result)
                    if validator is not None and not validation_retries:
                        execution_control = current_execution_control()
                        if execution_control is not None:
                            execution_control.set_phase("validating")
                        observer.begin_validation(result)
                        validated = validator(result)
                        observer.validated_result(validated)
                        result = validated
                    return result
                except exceptions.AIException as error:
                    if (
                        str(error) != EMPTY_TEXT_RESPONSE_MESSAGE
                        or validation_retries
                        or attempt + 1 >= EMPTY_TEXT_RETRY_ATTEMPTS
                    ):
                        raise
                    observer.empty_retry()
                    ai_debug(
                        "ai.generate.empty_text_retry",
                        prompt_type=getattr(prompt, "prompt_type", None),
                        attempt=attempt + 2,
                        max_attempts=EMPTY_TEXT_RETRY_ATTEMPTS,
                    )

            raise exceptions.AIException(EMPTY_TEXT_RESPONSE_MESSAGE)
        except BaseException as error:
            terminal_error = error
            raise
        finally:
            current_session.reset(session_token)
            try:
                if session is not None:
                    session.close()
            finally:
                observer.finish(error=terminal_error)
                observer.reset(token)
                observer.persist()

    # @testable infrastructure
    # @covered-by lagniappe/core/tools/ai/core.py::GenAI.generate_content
    def _request_content(self, **kwargs):
        session = current_session.get()
        if session is not None:
            return session.request(**kwargs)
        return self.client.models.generate_content(**kwargs)

    # @testable false
    # @covered-by lagniappe/core/tools/ai/core.py::GenAI.generate_content
    # @covered-by lagniappe/core/tools/ai/category.py::generate_category
    # @covered-by lagniappe/core/tools/ai/project.py::generate_project
    # @reason single-attempt provider flow is exercised through the public retry wrapper and downstream generators
    def _generate_content_once(self, prompt, model, validator=None, validation_retries=0):
        """Generate text content from a Prompt, including optional tool-call loops."""
        contents = self._build_contents(prompt)
        output_format = prompt.output_format.get("type")
        if validator is not None and prompt.response_schema:
            # Keep the contract visible when provider-side schema constraints are
            # disabled. Dynamic form values must survive local validation intact.
            contents.append(types.Content(role="user", parts=[types.Part.from_text(
                text="Return the complete proposal using this JSON schema:\n"
                + json.dumps(prompt.response_schema)
            )]))
        config = GenAI.create_config(prompt)
        final_config = None
        if (prompt.tools or prompt.search) and output_format == "JSON":
            # Search/tool turns can return empty candidates when combined with
            # provider-side JSON constraints. The prompt still requires JSON,
            # and cleanup validates it; schema-bearing tool flows get a separate
            # constrained final pass below.
            config = GenAI.create_config(
                prompt,
                response_mime_type=None,
                response_schema=None,
            )
            if prompt.response_schema and validator is None:
                final_config = GenAI.create_config(
                    prompt,
                    tools=list(GOOGLE_SEARCH_TOOL) if prompt.search else None,
                )
        try:
            observer = current_observer()
            execution_control = current_execution_control()
            if execution_control is not None:
                execution_control.before_provider("initial")
            if observer is not None:
                observer.request("initial")
            response = self._request_content(
                model=model, contents=contents, config=config
            )
        except Exception as e:
            if execution_control is not None:
                execution_control.ensure_active()
            if observer is not None:
                observer.provider_error(
                    e,
                    "initial",
                    quota=is_provider_quota_error(e),
                )
            _raise_provider_error(e)
        if execution_control is not None:
            execution_control.after_provider("initial")
        if observer is not None:
            observer.response(response)
        self._log_response(response, "initial")

        if validator is None and (not prompt.tools or not response.function_calls):
            if final_config:
                return self._generate_structured_final(
                    contents,
                    final_config,
                    prompt,
                    output_format,
                    source_response=response,
                    model=model,
                )
            text = GenAI._extract_text(response, output_format)
            if text is not None:
                return text
            raise exceptions.AIException(EMPTY_TEXT_RESPONSE_MESSAGE)

        return self._tool_loop(
            response,
            contents,
            config,
            prompt,
            output_format,
            final_config=final_config,
            model=model,
            validator=validator,
            validation_retries=validation_retries,
        )

    # @testable false
    # @reason debug-only console logging, not a behavior contract
    @staticmethod
    def _log_response(response, label=""):
        usage = getattr(response, "usage_metadata", None)
        if usage and debug_enabled():
            ai_debug(
                "ai.response.usage",
                label=label,
                prompt_tokens=getattr(usage, "prompt_token_count", None),
                cached_content_tokens=getattr(
                    usage,
                    "cached_content_token_count",
                    None,
                ),
                output_tokens=getattr(usage, "candidates_token_count", None),
                thought_tokens=getattr(usage, "thoughts_token_count", None),
                total_tokens=getattr(usage, "total_token_count", None),
                traffic_type=getattr(usage, "traffic_type", None),
            )

        candidate = response.candidates[0] if response.candidates else None
        if not candidate:
            return

        grounding = getattr(candidate, "grounding_metadata", None)
        if grounding:
            queries = getattr(grounding, "web_search_queries", None)
            if queries and debug_enabled():
                debug_log(f"[ai:{label}] Google Search queries: {queries}")

        if candidate.content and candidate.content.parts and debug_enabled():
            for part in candidate.content.parts:
                if hasattr(part, "text") and part.text:
                    preview = part.text[:200].replace("\n", " ")
                    debug_log(f"[ai:{label}] Model text: {preview}...")

    # @testable true
    # @tests tests_unit/test_015_ai_tools.py::test_ai_tool_loop_limit_exception_includes_trace
    # @matrix ai : error-context tool-dispatch trace validation repair
    def _tool_loop(
        self,
        response,
        contents,
        config,
        prompt,
        output_format,
        final_config=None,
        model=None,
        validator=None,
        validation_retries=0,
    ):
        max_iterations = prompt.max_tool_iterations or MAX_TOOL_ITERATIONS
        model = model or GenAI._model_for_prompt(prompt)
        tool_cache = {}
        tool_trace = []
        validation_attempts = 0
        retrieval_finished = False
        while True:
            observer = current_observer()
            execution_control = current_execution_control()
            iteration = len(tool_trace)
            provider_stage = "tool"
            if not response.function_calls:
                if final_config:
                    return self._generate_structured_final(
                        contents, final_config, prompt, output_format,
                        source_response=response, tool_trace=tool_trace, model=model,
                    )
                try:
                    result = GenAI._extract_text(response, output_format)
                    if result is None:
                        raise exceptions.AIException(EMPTY_TEXT_RESPONSE_MESSAGE)
                    if validator is not None:
                        if execution_control is not None:
                            execution_control.set_phase("validating")
                        if observer is not None:
                            observer.provider_result(result)
                            observer.begin_validation(result)
                        result = validator(result)
                        if observer is not None:
                            observer.validated_result(result)
                    return result
                except exceptions.AIException as error:
                    if validator is None or validation_attempts >= validation_retries:
                        raise
                    validation_attempts += 1
                    mark_outcome("model_repair")
                    ai_debug(
                        "ai.generate.validation_failed", error=str(error),
                        attempt=validation_attempts, max_attempts=validation_retries,
                    )
                    if response.candidates and response.candidates[0].content:
                        contents.append(response.candidates[0].content)
                    contents.append(types.Content(role="user", parts=[
                        types.Part.from_text(text=(
                            f"Response validation failed: {error}\n"
                            "Correct the executable data using the evidence, exact "
                            "references and schemas already in this conversation. "
                            "You may read tools for missing information. Return the "
                            "complete corrected JSON response, preserving all requested "
                            "outcomes and valid values. Follow the original output "
                            "contract and make any summary match the final content. "
                            "Do not turn a formatting or validation error into a "
                            "question for the user or a needs_review action."
                        )),
                    ]))
                    provider_stage = "validation_repair"
            else:
                if retrieval_finished:
                    raise exceptions.AIException(
                        "The model requested more retrieval after the planning budget ended. Retry generation."
                    )
                if iteration >= max_iterations:
                    break
                iteration_trace = {
                    "iteration": iteration + 1,
                    "requested_calls": summarize_function_calls(response.function_calls),
                    "calls": [],
                }
                tool_trace.append(iteration_trace)

                if debug_enabled():
                    debug_log(f"[ai:tool-loop] Iteration {iteration + 1}/{max_iterations}")
                contents.append(response.candidates[0].content)

                try:
                    observer = current_observer()
                    tool_responses, file_parts = execute_function_calls(
                        response.function_calls,
                        prompt.user,
                        cache=tool_cache,
                        debug=debug_enabled(),
                        trace=iteration_trace["calls"],
                        max_file_parts=prompt.max_tool_file_parts_per_turn,
                        execution_control=current_execution_control(),
                    )
                except Exception as e:
                    execution_control = current_execution_control()
                    if execution_control is not None:
                        execution_control.ensure_active()
                    if observer is not None:
                        observer.tool_round(
                            response.function_calls,
                            iteration_trace["calls"],
                        )
                    context = {
                        "ai_tool_loop": {
                            "prompt_type": prompt.prompt_type,
                            "search_enabled": prompt.search,
                            "tools_enabled": prompt.tools,
                            "max_iterations": max_iterations,
                            "failed_iteration": iteration + 1,
                            "trace": tool_trace,
                        }
                    }
                    exceptions.capture(e, context=context)
                    raise exceptions.AIException(
                        f"Error executing function calls: {e}",
                        context=context,
                    ) from e

                if observer is not None:
                    observer.tool_round(
                        response.function_calls,
                        iteration_trace["calls"],
                    )

                contents.append(types.Content(role="tool", parts=tool_responses))

                if file_parts:
                    uri_parts = [
                        types.Part.from_uri(file_uri=f["uri"], mime_type=f["mime_type"])
                        for f in file_parts
                    ]
                    contents.append(types.Content(role="user", parts=uri_parts))

            if getattr(execution_control, "report_planning", False) and (
                len(tool_trace) >= min(16, max_iterations)
                or execution_control.remaining_seconds <= 180
            ):
                retrieval_finished = True
                config = (final_config or config).model_copy(deep=True)
                final_config = None
                config.tools = None
                config.tool_config = None
                contents.append(types.Content(role="user", parts=[
                    types.Part.from_text(text=(
                        "Retrieval is finished. Return the complete final output now "
                        "using the evidence already collected. Do not request tools. "
                        "Clearly identify unsupported changes instead of searching again."
                    )),
                ]))
                provider_stage = "structured_final"

            try:
                execution_control = current_execution_control()
                if execution_control is not None:
                    execution_control.before_provider(provider_stage)
                if observer is not None:
                    observer.request(provider_stage)
                response = self._request_content(
                    model=model, contents=contents, config=config
                )
            except Exception as e:
                if execution_control is not None:
                    execution_control.ensure_active()
                context = {
                    "ai_tool_loop": {
                        "prompt_type": prompt.prompt_type,
                        "search_enabled": prompt.search,
                        "tools_enabled": prompt.tools,
                        "max_iterations": max_iterations,
                        "failed_iteration": iteration + 1,
                        "trace": tool_trace,
                    }
                }
                if observer is not None:
                    observer.provider_error(
                        e,
                        provider_stage,
                        quota=is_provider_quota_error(e),
                    )
                if is_provider_quota_error(e):
                    quota_error = None
                    try:
                        _raise_provider_error(e)
                    except exceptions.AIQuotaError as caught:
                        quota_error = caught
                    quota_error.context.update(context)
                    raise quota_error from e
                raise
            if execution_control is not None:
                execution_control.after_provider(provider_stage)
            if observer is not None:
                observer.response(response)
            self._log_response(response, "tool-loop")

        if response.function_calls:
            context = {
                "ai_tool_loop": {
                    "prompt_type": prompt.prompt_type,
                    "search_enabled": prompt.search,
                    "tools_enabled": prompt.tools,
                    "max_iterations": max_iterations,
                    "completed_iterations": len(tool_trace),
                    "trace": tool_trace,
                    "pending_calls": summarize_function_calls(response.function_calls),
                }
            }
            raise exceptions.AIException(
                f"AI tool limit ({max_iterations} rounds) reached; the model still "
                "requested tools. Try again with less context or a simpler form.",
                context=context,
            )

        text = GenAI._extract_text(response, output_format)
        if text is not None:
            return text
        raise exceptions.AIException(EMPTY_TEXT_RESPONSE_MESSAGE)

    # @testable true
    # @tests tests_unit/test_015_ai_tools.py::test_ai_tool_json_generation_pins_runtime_model_through_structured_final_pass
    # @tests tests_unit/test_015_ai_tools.py::test_ai_tool_json_generation_preserves_no_call_response_in_structured_final
    # @matrix ai : config response-preservation structured-output tool-loop
    def _generate_structured_final(
        self,
        contents,
        config,
        prompt,
        output_format,
        source_response=None,
        tool_trace=None,
        model=None,
    ):
        model = model or GenAI._model_for_prompt(prompt)
        final_contents = [*contents]
        if source_response and getattr(source_response, "candidates", None):
            source_content = getattr(source_response.candidates[0], "content", None)
            if source_content is not None:
                final_contents.append(source_content)
        final_contents.append(
            types.Content(
                role="user",
                parts=[
                    types.Part.from_text(
                        text=(
                            "Return the final JSON response now using the output "
                            "format. Do not request tools."
                        )
                    )
                ],
            )
        )
        try:
            observer = current_observer()
            execution_control = current_execution_control()
            if execution_control is not None:
                execution_control.before_provider("structured_final")
            if observer is not None:
                observer.request("structured_final")
            response = self._request_content(
                model=model,
                contents=final_contents,
                config=config,
            )
        except Exception as e:
            if execution_control is not None:
                execution_control.ensure_active()
            if observer is not None:
                observer.provider_error(
                    e,
                    "structured_final",
                    quota=is_provider_quota_error(e),
                )
            if tool_trace and is_provider_quota_error(e):
                quota_error = None
                try:
                    _raise_provider_error(e)
                except exceptions.AIQuotaError as caught:
                    quota_error = caught
                quota_error.context["ai_tool_loop"] = {
                    "prompt_type": prompt.prompt_type,
                    "search_enabled": prompt.search,
                    "tools_enabled": prompt.tools,
                    "final_response": True,
                    "trace": tool_trace,
                }
                raise quota_error from e
            _raise_provider_error(e)
        if execution_control is not None:
            execution_control.after_provider("structured_final")
        if observer is not None:
            observer.response(response)
        self._log_response(response, "structured-final")

        text = GenAI._extract_text(response, output_format)
        if text is not None:
            return text
        raise exceptions.AIException(EMPTY_TEXT_RESPONSE_MESSAGE)

    # @testable true
    # @tests tests_e2e/005_pages/test_005f_page_image.py::test_generate_image_on_page
    # @tests tests_unit/test_015_ai_tools.py::test_ai_image_generation_config_and_provider_error
    # @matrix ai pages : image-generate site-policy provider-boundary
    def generate_image(self, prompt, aspect_ratio=None):
        """Generate an image from a Prompt and return a BytesIO buffer."""
        if not CONFIG.AI_ENABLED:
            raise exceptions.AIException("AI is disabled for this installation.")
        model = runtime_ai_settings()["AI_IMAGE_MODEL"]
        if _is_imagen_model(model):
            return self._generate_imagen_image(prompt, model, aspect_ratio=aspect_ratio)

        contents = self._build_contents(prompt)
        overrides = {"response_modalities": IMAGE_RESPONSE_MODALITIES}
        if aspect_ratio:
            overrides["image_config"] = types.ImageConfig(aspect_ratio=aspect_ratio)
        config = GenAI.create_config(prompt, **overrides)

        execution_control = current_execution_control()
        if execution_control is not None:
            execution_control.before_provider("initial")
        try:
            response = self._request_content(
                model=model, contents=contents, config=config
            )
        except Exception as e:
            if execution_control is not None:
                execution_control.ensure_active()
            raise exceptions.AIException(provider_error_message(e)) from e
        if execution_control is not None:
            execution_control.after_provider("initial")

        if not response.candidates:
            raise exceptions.AIException("No image generated in response")

        candidate = response.candidates[0]
        finish = _finish_reason_name(getattr(candidate, "finish_reason", None))
        if finish in BLOCKED_FINISH_REASONS:
            raise exceptions.AIException(f"Image generation blocked: {finish}")

        if candidate.content and candidate.content.parts:
            for part in candidate.content.parts:
                if part.inline_data and part.inline_data.data:
                    output = BytesIO(part.inline_data.data)
                    output.seek(0)
                    output.content_type = part.inline_data.mime_type or "image/png"
                    return output

        raise exceptions.AIException("No image data in response")

    # @testable true
    # @tests tests_unit/test_015_ai_tools.py::test_ai_image_generation_config_and_provider_error
    # @matrix ai : config image-generate imagen
    def _generate_imagen_image(self, prompt, model, aspect_ratio=None):
        """Generate an image through Imagen's generate_images endpoint."""
        config_data = {"number_of_images": 1}
        if aspect_ratio:
            config_data["aspect_ratio"] = aspect_ratio
        config = types.GenerateImagesConfig(**config_data)

        execution_control = current_execution_control()
        if execution_control is not None:
            execution_control.before_provider("initial")
        try:
            response = self.client.models.generate_images(
                model=model,
                prompt=_image_prompt_text(prompt),
                config=config,
            )
        except Exception as e:
            if execution_control is not None:
                execution_control.ensure_active()
            raise exceptions.AIException(provider_error_message(e)) from e
        if execution_control is not None:
            execution_control.after_provider("initial")

        for generated in response.generated_images or []:
            image = getattr(generated, "image", None)
            if image and image.image_bytes:
                output = BytesIO(image.image_bytes)
                output.seek(0)
                output.content_type = image.mime_type or "image/png"
                return output

        filtered = next(
            (
                generated.rai_filtered_reason
                for generated in response.generated_images or []
                if getattr(generated, "rai_filtered_reason", None)
            ),
            None,
        )
        if filtered:
            raise exceptions.AIException(f"Image generation blocked: {filtered}")

        raise exceptions.AIException("No image data in response")


ai_model = GenAI()
