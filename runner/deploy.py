import ast
import fnmatch
import json
from pathlib import Path
import re
import sys

from runner.context import GCLOUD_CLI, NPM_CLI
from config import (
    SETTINGS,
    Directory,
    File,
    _atomic_write_text,
    verify_generation_manifest,
)
from runner.process import run_command

PACKAGE_IMPORTS = {
    "bs4": "beautifulsoup4",
    "dateutil": "python-dateutil",
    "flask_login": "flask-login",
    "flask_wtf": "flask-wtf",
    "google.api_core": "google-api-core",
    "google.auth": "google-auth",
    "google.cloud.datastore": "google-cloud-datastore",
    "google.cloud.documentai": "google-cloud-documentai",
    "google.cloud.storage": "google-cloud-storage",
    "google.cloud.tasks_v2": "google-cloud-tasks",
    "google.genai": "google-genai",
    "google.oauth2": "google-auth",
    "google.protobuf": "protobuf",
    "PIL": "pillow",
    "sentry_sdk": "sentry-sdk",
    "yaml": "PyYAML",
}


# @testable false
# @covered-by runner/deploy.py::runtime_deploy_surface_issues
# @reason small normalization helper for requirements/import comparison
def _canonical_package_name(name):
    return re.sub(r"[-_.]+", "-", name).lower()


# @testable false
# @covered-by runner/deploy.py::runtime_deploy_surface_issues
# @reason requirements parser branch owned by deploy surface verification
def _requirements_packages(app_dir):
    requirements_path = app_dir / "requirements.txt"
    if not requirements_path.exists():
        return set()

    packages = set()
    for line in requirements_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("-"):
            continue
        package = re.split(r"\s*(?:===|==|~=|!=|<=|>=|<|>|\[)", line, maxsplit=1)[0]
        if package:
            packages.add(_canonical_package_name(package))

    return packages


# @testable false
# @covered-by runner/deploy.py::runtime_deploy_surface_issues
# @reason .gcloudignore parser branch owned by deploy surface verification
def _gcloudignore_patterns(app_dir):
    ignore_path = app_dir / ".gcloudignore"
    if not ignore_path.exists():
        return []

    patterns = []
    for raw_line in ignore_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if (
            not line
            or line.startswith("#")
            or line.startswith("!")
            or line.startswith("#!")
        ):
            continue
        patterns.append(line)

    return patterns


# @testable false
# @covered-by runner/deploy.py::runtime_deploy_surface_issues
# @reason local root discovery branch owned by deploy surface verification
def _local_import_roots(app_dir):
    roots = {
        path.stem
        for path in app_dir.glob("*.py")
        if path.is_file() and path.name != "__init__.py"
    }
    roots.update(
        path.name
        for path in app_dir.iterdir()
        if path.is_dir() and (path / "__init__.py").exists()
    )
    return roots


# @testable false
# @covered-by runner/deploy.py::runtime_deploy_surface_issues
# @reason ignore matching branch owned by deploy surface verification
def _matches_ignore_pattern(relative_path, pattern):
    path = relative_path.as_posix()
    anchored = pattern.startswith("/")
    directory_only = pattern.endswith("/")
    normalized = pattern.rstrip("/").lstrip("/")
    if not normalized:
        return False

    if anchored:
        if directory_only:
            return path == normalized or path.startswith(f"{normalized}/")
        return fnmatch.fnmatch(path, normalized)

    if "/" not in normalized:
        return any(fnmatch.fnmatch(part, normalized) for part in relative_path.parts)

    if directory_only:
        return path == normalized or path.startswith(f"{normalized}/")

    return fnmatch.fnmatch(path, normalized)


# @testable false
# @covered-by runner/deploy.py::runtime_deploy_surface_issues
# @reason ignore matching branch owned by deploy surface verification
def _is_ignored_runtime_path(relative_path, ignored_patterns):
    return any(
        _matches_ignore_pattern(relative_path, pattern) for pattern in ignored_patterns
    )


# @testable false
# @covered-by runner/deploy.py::runtime_deploy_surface_issues
# @reason file selection branch owned by deploy surface verification
def _runtime_python_files(app_dir, ignored_patterns):
    for path in app_dir.rglob("*.py"):
        relative_path = path.relative_to(app_dir)
        if any(part == "__pycache__" for part in relative_path.parts):
            continue
        if _is_ignored_runtime_path(relative_path, ignored_patterns):
            continue
        yield path


# @testable false
# @covered-by runner/deploy.py::runtime_deploy_surface_issues
# @reason relative import resolution branch owned by deploy surface verification
def _module_name_for_path(app_dir, path):
    relative_path = path.relative_to(app_dir)
    parts = list(relative_path.with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


# @testable false
# @covered-by runner/deploy.py::runtime_deploy_surface_issues
# @reason relative import resolution branch owned by deploy surface verification
def _resolve_import_from_module(path, app_dir, node):
    if node.level == 0:
        return node.module

    current_module = _module_name_for_path(app_dir, path)
    current_parts = current_module.split(".") if current_module else []
    if path.name != "__init__.py":
        current_parts = current_parts[:-1]

    base_parts = current_parts[: max(0, len(current_parts) - node.level + 1)]
    if node.module:
        base_parts.extend(node.module.split("."))

    return ".".join(base_parts)


# @testable false
# @covered-by runner/deploy.py::runtime_deploy_surface_issues
# @reason AST extraction branch owned by deploy surface verification
def _imported_modules(path, app_dir):
    try:
        tree = ast.parse(
            path.read_text(encoding="utf-8"),
            filename=str(path),
        )
    except SyntaxError as e:
        return [("", e.lineno or 0, f"could not parse Python file: {e}")]

    modules = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                modules.append((alias.name, node.lineno, None))
        elif isinstance(node, ast.ImportFrom):
            base_module = _resolve_import_from_module(path, app_dir, node)
            if not base_module:
                continue
            for alias in node.names:
                if alias.name == "*":
                    modules.append((base_module, node.lineno, None))
                else:
                    modules.append((f"{base_module}.{alias.name}", node.lineno, None))

    return modules


# @testable false
# @covered-by runner/deploy.py::runtime_deploy_surface_issues
# @reason local module path branch owned by deploy surface verification
def _local_module_path(app_dir, module_name):
    parts = module_name.split(".")
    for length in range(len(parts), 0, -1):
        candidate = app_dir.joinpath(*parts[:length])
        if candidate.is_dir() and (candidate / "__init__.py").exists():
            return candidate
        if candidate.with_suffix(".py").exists():
            return candidate.with_suffix(".py")
    return None


# @testable false
# @covered-by runner/deploy.py::runtime_deploy_surface_issues
# @reason package mapping branch owned by deploy surface verification
def _required_package_for_import(module_name):
    for import_prefix in sorted(PACKAGE_IMPORTS, key=len, reverse=True):
        if module_name == import_prefix or module_name.startswith(f"{import_prefix}."):
            return PACKAGE_IMPORTS[import_prefix]
    return module_name.split(".", 1)[0]


# @testable false
# @covered-by runner/deploy.py::runtime_deploy_surface_issues
# @reason stdlib predicate branch owned by deploy surface verification
def _is_stdlib_module(root):
    return root in sys.builtin_module_names or root in getattr(
        sys, "stdlib_module_names", set()
    )


# @testable true
# @tests tests_tooling/test_003_config.py::test_runtime_deploy_surface_flags_ignored_local_imports_and_missing_requirements
# @tests tests_tooling/test_003_config.py::test_runtime_upload_boundary_has_no_local_orchestration_imports
# @features deploy
# @dimensions deploy-surface imports requirements gcloudignore package-boundary
def runtime_deploy_surface_issues(app_dir=None):
    """Return import issues that would break after App Engine upload/install."""
    app_dir = Path(app_dir or Directory.APP.value)
    ignored_patterns = _gcloudignore_patterns(app_dir)
    local_roots = _local_import_roots(app_dir)
    requirements = _requirements_packages(app_dir)
    issues = []

    for path in _runtime_python_files(app_dir, ignored_patterns):
        relative_path = path.relative_to(app_dir)
        for module_name, line_number, parse_error in _imported_modules(path, app_dir):
            if parse_error:
                issues.append(f"{relative_path}:{line_number}: {parse_error}")
                continue

            local_module_path = _local_module_path(app_dir, module_name)
            if local_module_path:
                local_relative_path = local_module_path.relative_to(app_dir)
                if _is_ignored_runtime_path(local_relative_path, ignored_patterns):
                    ignored_label = local_relative_path.as_posix()
                    if local_module_path.is_dir():
                        ignored_label = f"{ignored_label}/"
                    issues.append(
                        f"{relative_path}:{line_number}: imports '{module_name}', "
                        f"but '{ignored_label}' is excluded by .gcloudignore"
                    )
                continue

            root = module_name.split(".", 1)[0]
            if root in local_roots:
                issues.append(
                    f"{relative_path}:{line_number}: imports '{module_name}', "
                    f"but local module '{root}' could not be resolved"
                )
                continue

            if _is_stdlib_module(root):
                continue

            package_name = _required_package_for_import(module_name)
            if _canonical_package_name(package_name) not in requirements:
                issues.append(
                    f"{relative_path}:{line_number}: imports '{module_name}', "
                    f"but '{package_name}' is not in requirements.txt"
                )

    return issues


# @testable true
# @tests tests_tooling/test_003_config.py::test_runtime_deploy_surface_flags_ignored_local_imports_and_missing_requirements
# @features deploy
# @dimensions deploy-surface imports requirements gcloudignore
def verify_runtime_deploy_surface(app_dir=None):
    issues = runtime_deploy_surface_issues(app_dir)
    if not issues:
        return True

    message = "Runtime deploy surface check failed:\n" + "\n".join(
        f"- {issue}" for issue in issues
    )
    raise RuntimeError(message)


# @testable true
# @tests tests_tooling/test_003_config.py::test_deploy_version_update_keeps_package_lock_in_sync
# @features deploy
# @dimensions version package-lock transactional-state
def update_package_lock_version(version, lock_path=None):
    """Keep package-lock root metadata aligned with package.json."""
    path = lock_path or File.PACKAGE_JSON.value.with_name("package-lock.json")
    if not path.exists():
        return False

    with open(path, "r", encoding="utf-8", newline="") as f:
        package_lock = json.load(f)

    package_lock["version"] = version
    root_package = package_lock.get("packages", {}).get("")
    if root_package is not None:
        root_package["version"] = version

    _atomic_write_text(
        path,
        f"{json.dumps(package_lock, indent=2)}\n",
    )

    return True


def increment_version():
    """Increment version in package.json, package-lock.json, and settings YAML."""
    # Read and update package.json

    current_version = float(SETTINGS.NODE["version"])
    new_version = str(round(current_version + 0.01, 2))
    SETTINGS.NODE["version"] = new_version
    update_package_lock_version(new_version)

    # Read and update settings YAML
    SETTINGS.APP["VERSION"] = new_version

    return new_version


def update_manifest():
    app_name = SETTINGS.APP["APP_NAME"]

    SETTINGS.MANIFEST["name"] = app_name
    SETTINGS.MANIFEST["short_name"] = app_name

    image_version = SETTINGS.APP.get("SITE_IMAGE_VERSION", 0)
    if image_version:
        for icon in SETTINGS.MANIFEST["icons"]:
            base_src = icon["src"].split("?", 1)[0]
            icon["src"] = f"{base_src}?v={image_version}"


# @testable false
# @covered-by runner/deploy.py::deploy
# @reason gcloud deployment adapter is exercised through publish-mode deployment
def _deploy_app_yaml(file_ref, quiet=False):
    command = [GCLOUD_CLI, "app", "deploy", str(file_ref.value)]
    if quiet:
        command.append("--quiet")
    result = run_command(command, check=False, capture_output=False)
    if result.returncode != 0:
        raise RuntimeError(
            f"gcloud app deploy failed with exit code {result.returncode}."
        )


# @testable true
# @tests tests_tooling/test_003_config.py::test_deploy_modes_separate_dev_build_from_setup_publish
# @features deploy
# @dimensions version build app-yaml index-yaml
def deploy(
    *,
    build_assets=True,
    deploy_indexes=False,
    quiet=False,
    announce_completion=True,
):
    """Build frontend assets, refresh generated metadata, and deploy the app."""
    verify_runtime_deploy_surface()

    if build_assets:
        update_manifest()
        SETTINGS.save()

    if build_assets:
        Directory.JS_CHUNKS.clean()

        print("Building static files...")
        run_command([NPM_CLI, "run", "build"], check=True, capture_output=False)

    verify_generation_manifest()
    print(
        "Deployment includes config/files/lagniappe_settings.yaml and, when "
        "configured, config/files/redis_ca.pem. Keep both files secure."
    )

    if deploy_indexes:
        print("Deploying indexes...")
        _deploy_app_yaml(File.INDEX_YAML, quiet=quiet)

    print("Deploying app...")
    _deploy_app_yaml(File.APP_YAML, quiet=quiet)

    if announce_completion:
        print("Deployment complete!")
    return True
