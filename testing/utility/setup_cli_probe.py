"""Run the real setup CLI dispatcher with subprocess-safe fake entry points."""

import runpy
import os
import sys
import tempfile
import types
from pathlib import Path


def _entry_point(name, behavior, status):
    def invoke(*args, **kwargs):
        details = ""
        if args or kwargs:
            details = f" args={args!r} kwargs={kwargs!r}"
        print(f"CALL {name}{details}", flush=True)
        if behavior == "raise":
            raise RuntimeError(f"{name} provider failure")
        if behavior == "cancel":
            return None
        return status

    return invoke


def _install_module(name, function_name, function):
    module_name = f"installer.{name}"
    module = types.ModuleType(module_name)
    setattr(module, function_name, function)
    sys.modules[module_name] = module


def main():
    if len(sys.argv) < 3:
        raise SystemExit(
            "usage: setup_cli_probe.py RETURN|CANCEL|RAISE STATUS [setup arguments]"
        )

    behavior = sys.argv[1].lower()
    status = int(sys.argv[2])
    cli_arguments = sys.argv[3:]
    if behavior not in {"return", "cancel", "raise"}:
        raise SystemExit(f"unknown behavior: {behavior}")

    repository_root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(repository_root))

    _install_module(
        "custom_domain",
        "add_custom_domain",
        _entry_point("url", behavior, status),
    )
    _install_module(
        "auth_email",
        "configure_auth_email",
        _entry_point("email", behavior, status),
    )
    _install_module("ai", "configure_ai", _entry_point("ai", behavior, status))
    _install_module(
        "security",
        "configure_security",
        _entry_point("security", behavior, status),
    )
    _install_module(
        "development",
        "setup_development",
        _entry_point("development", behavior, status),
    )
    _install_module("install", "install", _entry_point("install", behavior, status))
    _install_module("doctor", "run_doctor", _entry_point("doctor", behavior, status))

    def update(*args, **kwargs):
        return _entry_point("update", behavior, status)(*args, **kwargs)

    _install_module("upgrade", "update", update)
    sys.modules["installer.upgrade"].upgrade = (
        lambda *args, **kwargs: _entry_point("upgrade", behavior, status)(
            *args,
            **kwargs,
        )
    )

    verify_module = types.ModuleType("installer.verify")
    verify_module.prepare_existing_installation = _entry_point(
        "verify", "return", 0
    )
    verify_module.repair_installation = _entry_point(
        "repair", behavior, status
    )
    sys.modules["installer.verify"] = verify_module

    def create_deferred_job_reconciler():
        result = _entry_point("jobs", behavior, status)()
        if behavior == "cancel":
            return None
        return result == 0

    _install_module(
        "gcloud",
        "create_deferred_job_reconciler",
        create_deferred_job_reconciler,
    )
    package_install_module = types.ModuleType("installer.package_install")
    package_install_module.ensure_pip_is_available = lambda: None
    package_install_module.ensure_setup_dependencies = lambda: None
    sys.modules["installer.package_install"] = package_install_module
    runner_gcloud_module = types.ModuleType("runner.gcloud")
    runner_gcloud_module.activate_repository_gcloud = lambda **_kwargs: True
    sys.modules["runner.gcloud"] = runner_gcloud_module

    setup_path = repository_root / "installer" / "__main__.py"
    os.environ["LAGNIAPPE_SETUP_STATE_DIR"] = tempfile.mkdtemp(
        prefix="lagniappe-cli-probe-"
    )
    sys.argv = ["-m installer", *cli_arguments]
    runpy.run_path(setup_path, run_name="__main__")


if __name__ == "__main__":
    main()
