"""Gemini model catalog, discovery, and retry defaults."""

import time

AI_PRICING_URL = "https://cloud.google.com/gemini-enterprise-agent-platform/generative-ai/pricing"

AI_RETRY_STATUS_CODES = [408, 429, 500, 502, 503, 504]
AI_RETRY_ATTEMPTS = 5
AI_RETRY_INITIAL_DELAY = 1.0
AI_RETRY_MAX_DELAY = 30.0
AI_RETRY_EXP_BASE = 2.0
AI_RETRY_JITTER = 1.0
AI_REQUEST_TIMEOUT_MS = 120 * 1000

DISCOVERY_TIMEOUT_MS = 2500
DISCOVERY_CACHE_SECONDS = 6 * 60 * 60

_DISCOVERY_CACHE = {}


MODEL_CATALOG = [
    {
        "id": "gemini-3.5-flash",
        "label": "Gemini 3.5 Flash",
        "kind": "text",
        "tier": "primary",
        "description": "Best default for rich generation, reports, and durable workspace changes.",
    },
    {
        "id": "gemini-3.1-flash-lite",
        "label": "Gemini 3.1 Flash-Lite",
        "kind": "text",
        "tier": "utility",
        "description": "Lowest-cost default for short parsing, classification, and summaries.",
    },
    {
        "id": "gemini-2.5-flash",
        "label": "Gemini 2.5 Flash",
        "kind": "text",
        "tier": "primary",
        "description": "Stable fallback for general text generation at Flash latency and cost.",
    },
    {
        "id": "gemini-2.5-flash-lite",
        "label": "Gemini 2.5 Flash-Lite",
        "kind": "text",
        "tier": "utility",
        "description": "Stable low-cost utility fallback for simple structured outputs.",
    },
    {
        "id": "gemini-2.5-pro",
        "label": "Gemini 2.5 Pro",
        "kind": "text",
        "tier": "primary",
        "description": "Higher-capability option for complex reasoning when cost is less important.",
    },
    {
        "id": "gemini-3.1-flash-image",
        "label": "Gemini 3.1 Flash Image",
        "kind": "image",
        "tier": "image",
        "description": "Default image generation/editing model for page and visual asset workflows.",
    },
    {
        "id": "gemini-2.5-flash-image",
        "label": "Gemini 2.5 Flash Image",
        "kind": "image",
        "tier": "image",
        "description": "Stable image fallback when the default image model is unavailable.",
    },
]


# @testable false
# @covered-by config/ai_models.py::discover_model_options
# @reason formatting helper exercised through discovery/catalog tests
def _preview_label(option):
    if option.get("preview") and "Preview" not in option["label"]:
        option["label"] = f"{option['label']} (Preview)"
    return option


# @testable false
# @covered-by config/ai_models.py::discover_model_options
# @reason model id normalization is covered through discovery/catalog tests
def _model_id(name):
    return str(name or "").split("/")[-1]


# @testable false
# @covered-by config/ai_models.py::discover_model_options
# @reason simple catalog copy covered through public discovery behavior
def _catalog_options():
    options = []
    for item in MODEL_CATALOG:
        option = {
            **item,
            "source": "catalog",
            "preview": "preview" in item["id"].lower(),
            "custom": False,
        }
        options.append(_preview_label(option))
    return options


# @testable false
# @covered-by config/ai_models.py::discover_model_options
# @reason provider model adapter covered through public discovery behavior
def _option_from_model(model):
    model_id = _model_id(getattr(model, "name", None))
    if not model_id.startswith("gemini-"):
        return None

    supported_actions = list(getattr(model, "supported_actions", None) or [])
    action_text = " ".join(str(action).lower() for action in supported_actions)
    if action_text and not any(
        action in action_text
        for action in (
            "generatecontent",
            "generate_content",
            "generateimages",
            "generate_images",
        )
    ):
        return None

    kind = "image" if "image" in model_id else "text"
    display_name = getattr(model, "display_name", None) or model_id
    description = getattr(model, "description", None) or ""
    option = {
        "id": model_id,
        "label": display_name,
        "kind": kind,
        "tier": "image" if kind == "image" else "primary",
        "description": description,
        "source": "provider",
        "preview": "preview" in f"{model_id} {display_name}".lower(),
        "custom": False,
    }
    return _preview_label(option)


# @testable false
# @covered-by config/ai_models.py::discover_model_options
# @reason merge behavior covered through public discovery behavior
def _merge_options(catalog_options, provider_options):
    merged = {option["id"]: dict(option) for option in catalog_options}
    for option in provider_options:
        existing = merged.get(option["id"], {})
        if existing.get("description") and not option.get("description"):
            option["description"] = existing["description"]
        if existing.get("tier") and option.get("tier") == "primary":
            option["tier"] = existing["tier"]
        merged[option["id"]] = {**existing, **option}
    ordered_ids = [option["id"] for option in catalog_options]
    ordered = [merged.pop(model_id) for model_id in ordered_ids if model_id in merged]
    ordered.extend(sorted(merged.values(), key=lambda option: option["label"].lower()))
    return ordered


# @testable false
# @covered-by config/ai_models.py::discover_model_options
# @reason custom option preservation covered through public discovery behavior
def _add_current_model(options, model_id, kind):
    if not model_id or any(option["id"] == model_id for option in options):
        return

    options.append(
        {
            "id": model_id,
            "label": f"Current custom model: {model_id}",
            "kind": kind,
            "tier": "image" if kind == "image" else "primary",
            "description": "Saved model name from this installation.",
            "source": "current",
            "preview": "preview" in model_id.lower(),
            "custom": True,
        }
    )


# @testable false
# @covered-by config/ai_models.py::discover_model_options
# @reason response shaping covered through public discovery behavior
def _options_response(options, current_settings=None):
    current_settings = current_settings or {}
    _add_current_model(options, current_settings.get("AI_MODEL"), "text")
    _add_current_model(options, current_settings.get("AI_UTILITY_MODEL"), "text")
    _add_current_model(options, current_settings.get("AI_IMAGE_MODEL"), "image")

    text_options = [option for option in options if option["kind"] == "text"]
    image_options = [option for option in options if option["kind"] == "image"]
    return {
        "pricing_url": AI_PRICING_URL,
        "text": text_options,
        "image": image_options,
    }


# @testable true
# @tests tests_unit/test_015_ai_tools.py::test_ai_model_discovery_falls_back_to_catalog_and_preserves_custom
# @features ai
# @dimensions model-discovery fallback custom-current
def discover_model_options(
    project=None,
    location="global",
    credentials=None,
    client=None,
    current_settings=None,
    use_cache=True,
):
    """Return Gemini model options, using live SDK discovery when available."""
    catalog = _catalog_options()
    cache_key = (project, location)
    now = time.monotonic()

    if use_cache and client is None:
        cached = _DISCOVERY_CACHE.get(cache_key)
        if cached and now - cached["time"] < DISCOVERY_CACHE_SECONDS:
            return _options_response(
                [dict(option) for option in cached["options"]],
                current_settings=current_settings,
            )

    provider_options = []
    try:
        if client is None:
            if not project:
                raise RuntimeError("project is required for live model discovery")

            from google import genai
            from google.genai import types

            http_options = types.HttpOptions(
                api_version="v1",
                timeout=DISCOVERY_TIMEOUT_MS,
            )
            client = genai.Client(
                vertexai=True,
                project=project,
                location=location,
                credentials=credentials,
                http_options=http_options,
            )
            config = types.ListModelsConfig(
                page_size=100,
                http_options=types.HttpOptions(timeout=DISCOVERY_TIMEOUT_MS),
            )
            models = client.models.list(config=config)
        else:
            models = client.models.list()

        for model in models:
            option = _option_from_model(model)
            if option:
                provider_options.append(option)
    except Exception:
        provider_options = []

    merged = _merge_options(catalog, provider_options)
    if use_cache and client is None:
        _DISCOVERY_CACHE[cache_key] = {
            "time": now,
            "options": [dict(option) for option in merged],
        }

    return _options_response(merged, current_settings=current_settings)


# @testable true
# @tests tests_unit/test_015_ai_tools.py::test_ai_model_discovery_falls_back_to_catalog_and_preserves_custom
# @features ai
# @dimensions model-discovery validation
def known_model_ids(model_options=None, kind=None):
    """Return known model ids from a discovery response or the curated catalog."""
    model_options = model_options or discover_model_options(use_cache=False)
    buckets = []
    if kind in (None, "text"):
        buckets.extend(model_options.get("text", []))
    if kind in (None, "image"):
        buckets.extend(model_options.get("image", []))
    return {option["id"] for option in buckets}
