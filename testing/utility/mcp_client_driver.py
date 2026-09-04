"""Isolated official-SDK driver for the managed MCP boundary E2E test.

This file executes under the standalone package interpreter.  It deliberately
does not import the application or repository test process, and it receives the
real API credential only through the child environment.
"""

from __future__ import annotations

import asyncio
import io
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from typing import Any

import httpx
from mcp import Client
from mcp.client.stdio import StdioServerParameters, stdio_client


_PRIVATE_TRANSPORT_MARKERS = (
    "storage.googleapis.com",
    "x-goog-",
    "upload_id",
)
_URL_RE = re.compile(r"https?://[^\s\"']+", re.IGNORECASE)
_SAFE_FINDING_KEY = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,47}")
_MAX_PRIVACY_FINDINGS = 24
_MAX_FINDING_PATH_CHARS = 160


def _dump(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json", by_alias=True, exclude_none=True)
    return value


def _write_json(path: Path, value: Any) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    descriptor = os.open(temporary, flags, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            descriptor = -1
            json.dump(value, stream, ensure_ascii=False, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException:
        if descriptor >= 0:
            os.close(descriptor)
        temporary.unlink(missing_ok=True)
        raise


def _connection(specification: dict[str, Any]) -> tuple[Any, io.TextIOBase]:
    key = os.environ["LAGNIAPPE_API_KEY"]
    site_url = os.environ["LAGNIAPPE_URL"]
    arguments = ["-I", "-m", "lagniappe_mcp", "serve", "--from-env"]
    parameters = StdioServerParameters(
        command=sys.executable,
        args=arguments,
        env={
            "LAGNIAPPE_API_KEY": key,
            "LAGNIAPPE_URL": site_url,
        },
    )
    diagnostics = tempfile.TemporaryFile(mode="w+", encoding="utf-8")
    return stdio_client(parameters, errlog=diagnostics), diagnostics


def _finish_diagnostics(diagnostics: io.TextIOBase) -> str:
    try:
        diagnostics.flush()
        diagnostics.seek(0)
        return diagnostics.read()
    finally:
        diagnostics.close()


async def _call(client: Client, name: str, arguments: dict[str, Any]) -> dict:
    return _dump(await client.call_tool(name, arguments))


def _structured(result: dict[str, Any]) -> Any:
    if result.get("isError") is True:
        raise RuntimeError(f"MCP tool call failed: {result.get('content')!r}")
    if "structuredContent" not in result:
        raise RuntimeError("MCP tool result omitted structuredContent")
    return result["structuredContent"]


async def _revoke_browser_key(specification: dict[str, Any]) -> dict[str, Any]:
    revoke = specification["revoke"]
    site_url = os.environ["LAGNIAPPE_URL"].rstrip("/")
    headers = {
        "Accept": "application/json",
        "Origin": site_url,
        "Referer": f"{site_url}/",
        "X-CSRFToken": revoke["csrf_token"],
        "X-Lagniappe-Request": "true",
    }
    async with httpx.AsyncClient(
        cookies=revoke["cookies"],
        follow_redirects=False,
        trust_env=False,
        timeout=30,
    ) as client:
        response = await client.delete(
            f"{site_url}/users/me/api-key",
            headers=headers,
        )
    try:
        body = response.json()
    except ValueError as error:
        raise RuntimeError("Browser key revocation did not return JSON") from error
    return {"status": response.status_code, "body": body}


async def _workflow(specification: dict[str, Any]) -> tuple[dict[str, Any], str]:
    transport, diagnostics = _connection(specification)
    result: dict[str, Any] = {}
    async with Client(transport, mode="auto", cache=None) as client:
        result["protocol_version"] = client.protocol_version
        result["server_info"] = _dump(client.server_info)
        result["server_capabilities"] = _dump(client.server_capabilities)
        result["instructions"] = client.instructions
        result["tools"] = _dump(await client.list_tools())["tools"]

        actor_call = await _call(client, "get_actor", {})
        actor = _structured(actor_call)
        result["actor"] = actor_call

        ask_start = await _call(
            client,
            "start_ask",
            {
                "name": "MCP live Ask",
                "instructions": (
                    "Which workspace Page is named "
                    f"{specification['search_name']}?"
                ),
            },
        )
        ask = _structured(ask_start)
        search = await _call(
            client,
            "search_entities",
            {
                "plan_id": ask["id"],
                "query": specification["search_name"],
                "kinds": ["page"],
                "match_mode": "exact_name",
                "limit": 10,
            },
        )
        ask_contract = await _call(
            client, "get_plan_contract", {"plan_id": ask["id"]}
        )
        ask_contract_value = _structured(ask_contract)
        ask_receipt = await _call(
            client,
            "submit_plan",
            {
                "plan_id": ask["id"],
                "contract_version": ask_contract_value["contract_version"],
                "proposal": {
                    "summary": (
                        "The authenticated actor can view the requested workspace "
                        "Page."
                    ),
                    "answer_markdown": (
                        f"The permitted workspace Page is "
                        f"**{specification['search_name']}**."
                    ),
                    "confidence": 1.0,
                    "actions": [],
                },
            },
        )
        ask_get = await _call(client, "get_plan", {"plan_id": ask["id"]})
        result["ask"] = {
            "start": ask_start,
            "search": search,
            "contract": ask_contract,
            "receipt": ask_receipt,
            "get": ask_get,
        }

        create_start = await _call(
            client,
            "start_create",
            {
                "name": "MCP live Create",
                "instructions": "Prepare a browser-reviewable field guide Page.",
            },
        )
        create = _structured(create_start)
        create_contract = await _call(
            client, "get_plan_contract", {"plan_id": create["id"]}
        )
        create_contract_value = _structured(create_contract)
        create_proposal = {
            "summary": "Create a field guide Page.",
            "confidence": 1.0,
            "issues": [],
            "actions": [
                {
                    "id": "field-guide",
                    "type": "create_page",
                    "data": {
                        "name": "MCP Live Field Guide",
                        "document_markdown": (
                            "# MCP Live Field Guide\n\nPrepared for browser review."
                        ),
                    },
                }
            ],
        }
        create_receipt = await _call(
            client,
            "submit_plan",
            {
                "plan_id": create["id"],
                "contract_version": create_contract_value["contract_version"],
                "proposal": create_proposal,
            },
        )
        create_get = await _call(client, "get_plan", {"plan_id": create["id"]})
        replacement = {
            **create_proposal,
            "summary": "Create the revised field guide Page.",
            "actions": [
                {
                    **create_proposal["actions"][0],
                    "data": {
                        **create_proposal["actions"][0]["data"],
                        "document_markdown": (
                            "# MCP Live Field Guide\n\nRevised before browser review."
                        ),
                    },
                }
            ],
        }
        replacement_receipt = await _call(
            client,
            "submit_plan",
            {
                "plan_id": create["id"],
                "contract_version": create_contract_value["contract_version"],
                "proposal": replacement,
            },
        )
        replacement_get = await _call(
            client, "get_plan", {"plan_id": create["id"]}
        )
        result["create"] = {
            "start": create_start,
            "contract": create_contract,
            "receipt": create_receipt,
            "get": create_get,
            "replacement_receipt": replacement_receipt,
            "replacement_get": replacement_get,
        }

        organize_start = await _call(
            client,
            "start_organize",
            {
                "name": "MCP live Organize",
                "instructions": "Attach and summarize the supplied image file.",
            },
        )
        organize = _structured(organize_start)
        organize_contract_before = await _call(
            client, "get_plan_contract", {"plan_id": organize["id"]}
        )
        invalid_type = await _call(
            client,
            "upload_local_files",
            {"plan_id": organize["id"], "files": [{"path": 7}]},
        )
        invalid_field = await _call(
            client,
            "upload_local_files",
            {
                "plan_id": organize["id"],
                "files": [{"path": specification["upload_path"], "filename": "bad"}],
            },
        )
        upload = await _call(
            client,
            "upload_local_files",
            {
                "plan_id": organize["id"],
                "files": [{"path": specification["upload_path"]}],
            },
        )
        upload_value = _structured(upload)
        organize_contract = await _call(
            client, "get_plan_contract", {"plan_id": organize["id"]}
        )
        organize_contract_value = _structured(organize_contract)
        file_ref = organize_contract_value["required_file_refs"][0]
        file_metadata = await _call(
            client,
            "get_file",
            {
                "plan_id": organize["id"],
                "id": file_ref,
            },
        )
        file_original = await _call(
            client,
            "get_file",
            {
                "plan_id": organize["id"],
                "id": file_ref,
                "include_original": True,
            },
        )
        personal_page_ref = actor["user"]["personal_page"]["hash"]
        organize_proposal = {
            "summary": "Attach and summarize the uploaded MCP boundary image.",
            "confidence": 1.0,
            "issues": [],
            "actions": [
                {
                    "id": "attach-image",
                    "type": "attach_file_to_page",
                    "data": {"page": personal_page_ref, "file": file_ref},
                },
                {
                    "id": "summarize-image",
                    "type": "summarize_file",
                    "data": {
                        "file": file_ref,
                        "summary": (
                            "A deterministic image uploaded by the managed MCP "
                            "boundary test."
                        ),
                        "retrieval_terms": ["managed MCP", "boundary image"],
                        "search": True,
                    },
                },
            ],
        }
        organize_receipt = await _call(
            client,
            "submit_plan",
            {
                "plan_id": organize["id"],
                "contract_version": organize_contract_value["contract_version"],
                "proposal": organize_proposal,
            },
        )
        organize_get = await _call(
            client, "get_plan", {"plan_id": organize["id"]}
        )
        result["organize"] = {
            "start": organize_start,
            "contract_before_upload": organize_contract_before,
            "invalid_type": invalid_type,
            "invalid_field": invalid_field,
            "upload": upload,
            "contract": organize_contract,
            "file_metadata": file_metadata,
            "file_original": file_original,
            "receipt": organize_receipt,
            "get": organize_get,
            "uploaded_count": len(upload_value["upload_inventory"]),
        }

        result["revocation"] = await _revoke_browser_key(specification)
        result["revoked_call"] = await _call(client, "get_actor", {})
    diagnostics_text = _finish_diagnostics(diagnostics)

    return result, diagnostics_text


async def _foreign_plan(specification: dict[str, Any]) -> tuple[dict[str, Any], str]:
    transport, diagnostics = _connection(specification)
    try:
        async with Client(transport, mode="auto", cache=None) as client:
            result = {
                "protocol_version": client.protocol_version,
                "tools": _dump(await client.list_tools())["tools"],
                "foreign_plan": await _call(
                    client,
                    "get_plan",
                    {"plan_id": specification["plan_id"]},
                ),
            }
    finally:
        diagnostics_text = _finish_diagnostics(diagnostics)
    return result, diagnostics_text


def _sensitive_material(
    specification: dict[str, Any], *, extra_paths: tuple[str, ...] = ()
) -> list[tuple[str, str]]:
    revoke = specification.get("revoke") or {}
    candidates = (
        (
            "credential",
            (
                os.environ.get("LAGNIAPPE_API_KEY"),
                revoke.get("csrf_token"),
                *(revoke.get("cookies") or {}).values(),
            ),
        ),
        (
            "local_path",
            (
                specification.get("upload_path"),
                *extra_paths,
            ),
        ),
    )
    result: list[tuple[str, str]] = []
    seen: set[str] = set()
    for kind, values in candidates:
        for value in values:
            if isinstance(value, str) and value and value not in seen:
                seen.add(value)
                result.append((kind, value))
    return result


def _unsafe_kinds(value: str, sensitive: list[tuple[str, str]]) -> tuple[str, ...]:
    result = {kind for kind, secret in sensitive if secret in value}
    lowered = value.casefold()
    if any(marker in lowered for marker in _PRIVATE_TRANSPORT_MARKERS):
        result.add("transport")
    return tuple(sorted(result))


def _finding_path(
    parent: str,
    key: Any,
    *,
    key_is_unsafe: bool = False,
    sensitive: list[tuple[str, str]],
) -> str:
    if (
        isinstance(key, str)
        and not key_is_unsafe
        and _SAFE_FINDING_KEY.fullmatch(key)
    ):
        candidate = f"{parent}.{key}"
    elif isinstance(key, int) and not isinstance(key, bool) and key >= 0:
        candidate = f"{parent}[{key}]"
    else:
        candidate = f"{parent}.<field>"
    if _unsafe_kinds(candidate, sensitive):
        candidate = f"{parent}.<field>"
    if len(candidate) <= _MAX_FINDING_PATH_CHARS:
        return candidate
    return candidate[: _MAX_FINDING_PATH_CHARS - 3] + "..."


def _privacy_findings(
    result: Any,
    diagnostics: str,
    sensitive: list[tuple[str, str]],
) -> tuple[list[dict[str, Any]], bool]:
    findings: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    truncated = False

    def record(kind: str, path: str, value_type: str) -> None:
        nonlocal truncated
        identity = (kind, path, value_type)
        if identity in seen:
            return
        seen.add(identity)
        if len(findings) >= _MAX_PRIVACY_FINDINGS:
            truncated = True
            return
        findings.append(
            {
                "kind": kind,
                "path": path,
                "redacted": True,
                "type": value_type,
            }
        )

    pending: list[tuple[Any, str]] = [
        (result, "$.result"),
        (diagnostics, "$.diagnostics"),
    ]
    while pending:
        current, path = pending.pop()
        if isinstance(current, str):
            for kind in _unsafe_kinds(current, sensitive):
                record(kind, path, "string")
        elif isinstance(current, dict):
            for key, item in current.items():
                key_kinds = (
                    _unsafe_kinds(key, sensitive) if isinstance(key, str) else ()
                )
                child_path = _finding_path(
                    path,
                    key,
                    key_is_unsafe=bool(key_kinds),
                    sensitive=sensitive,
                )
                for kind in key_kinds:
                    record(kind, child_path, "object_key")
                pending.append((item, child_path))
        elif isinstance(current, (list, tuple)):
            pending.extend(
                (item, _finding_path(path, index, sensitive=sensitive))
                for index, item in enumerate(current)
            )
    return findings, truncated


def _diagnostic_summary(diagnostics: str, *, leaking: bool) -> dict[str, Any]:
    byte_count = len(diagnostics.encode("utf-8", errors="replace"))
    event_sizes: list[int] = []
    invalid_events = 0
    for line in diagnostics.splitlines():
        event_sizes.append(len(line.encode("utf-8", errors="replace")) + 1)
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            invalid_events += 1
        else:
            if not isinstance(value, dict):
                invalid_events += 1
    return {
        "bytes": byte_count,
        "contains_sensitive_value": leaking,
        "events": len(event_sizes),
        "invalid_events": invalid_events,
        "max_event_bytes": max(event_sizes, default=0),
        "truncated": False,
    }


def _exception_summary(error: BaseException) -> str:
    pending = [error]
    leaves: list[str] = []
    while pending and len(leaves) < 8:
        current = pending.pop(0)
        if isinstance(current, BaseExceptionGroup):
            pending[0:0] = list(current.exceptions)
            continue
        leaves.append(f"{type(current).__name__}: {current}")
    if pending:
        leaves.append("additional nested errors omitted")
    return "; ".join(leaves)


def _privacy_failure(
    findings: list[dict[str, Any]],
    *,
    truncated: bool,
    diagnostics: str,
) -> dict[str, Any]:
    return {
        "diagnostics": _diagnostic_summary(diagnostics, leaking=True),
        "driver_error": "MCP evidence failed privacy screening.",
        "privacy_findings": findings,
        "privacy_findings_truncated": truncated,
    }


def main(arguments: list[str]) -> int:
    if len(arguments) != 3:
        return 2
    mode, specification_path, result_path = arguments
    specification = json.loads(Path(specification_path).read_text(encoding="utf-8"))
    target = Path(result_path)
    try:
        if mode == "workflow":
            result, diagnostics = asyncio.run(_workflow(specification))
        elif mode == "foreign":
            result, diagnostics = asyncio.run(_foreign_plan(specification))
        else:
            raise ValueError("unknown MCP E2E driver mode")
        sensitive = _sensitive_material(specification)
        findings, findings_truncated = _privacy_findings(
            result,
            diagnostics,
            sensitive,
        )
        if findings:
            _write_json(
                target,
                _privacy_failure(
                    findings,
                    truncated=findings_truncated,
                    diagnostics=diagnostics,
                ),
            )
            return 1
        result["diagnostics"] = _diagnostic_summary(diagnostics, leaking=False)
        _write_json(target, result)
        return 0
    except BaseException as error:
        message = _exception_summary(error)
        sensitive = _sensitive_material(
            specification,
            extra_paths=(
                str(specification_path),
                str(result_path),
                str(Path(specification_path).resolve().parent),
                str(Path(result_path).resolve().parent),
            ),
        )
        findings, findings_truncated = _privacy_findings(
            {"driver_error": message},
            "",
            sensitive,
        )
        if findings:
            _write_json(
                target,
                _privacy_failure(
                    findings,
                    truncated=findings_truncated,
                    diagnostics="",
                ),
            )
            return 1
        for _kind, value in sorted(
            sensitive,
            key=lambda item: len(item[1]),
            reverse=True,
        ):
            message = message.replace(value, "[redacted]")
        message = _URL_RE.sub("[redacted URL]", message)
        encoded = message.encode("utf-8", errors="replace")
        if len(encoded) > 8 * 1024:
            message = encoded[: 8 * 1024 - 3].decode(
                "utf-8", errors="ignore"
            ) + "..."
        _write_json(target, {"driver_error": message})
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
