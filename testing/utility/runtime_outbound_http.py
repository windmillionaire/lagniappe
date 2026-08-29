"""Repository inventory helpers for direct runtime outbound-HTTP imports."""

import ast
from pathlib import Path


DIRECT_HTTP_MODULES = frozenset({"requests", "httpx", "urllib.request"})


# @testable true
# @tests tests_tooling/test_010_runtime_outbound_http.py::test_direct_http_inventory_recognizes_supported_import_forms
# @matrix outbound-http tooling : import-syntax source-inventory
def direct_http_imports(path: Path) -> frozenset[str]:
    """Return direct HTTP libraries imported by one Python source file."""
    imports = set()
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                module = alias.name
                for direct_module in DIRECT_HTTP_MODULES:
                    if module == direct_module or module.startswith(
                        f"{direct_module}."
                    ):
                        imports.add(direct_module)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module == "requests" or module.startswith("requests."):
                imports.add("requests")
            elif module == "httpx" or module.startswith("httpx."):
                imports.add("httpx")
            elif module == "urllib.request":
                imports.add("urllib.request")
            elif module == "urllib" and any(
                alias.name == "request" for alias in node.names
            ):
                imports.add("urllib.request")
    return frozenset(imports)


# @testable true
# @tests tests_tooling/test_010_runtime_outbound_http.py::test_runtime_direct_http_imports_match_shared_boundary_and_audited_providers
# @matrix outbound-http tooling : direct-call-guard provider-ownership source-inventory
def runtime_direct_http_imports(
    runtime_root: Path,
    *,
    repository_root: Path,
) -> dict[str, frozenset[str]]:
    """Inventory every direct HTTP import below the runtime package."""
    found = {}
    for path in sorted(runtime_root.rglob("*.py")):
        imports = direct_http_imports(path)
        if imports:
            found[path.relative_to(repository_root).as_posix()] = imports
    return found
