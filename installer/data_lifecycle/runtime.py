"""Isolated runtime-owned migration and cache actions for data recovery."""

from __future__ import annotations

import json
import sys


# @testable false
# @covered-by installer/data_lifecycle/provider.py::ProviderContext
# @reason subprocess-only adapter is owned by the restore provider boundary
def main(argv=None):
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments == ["migrate"]:
        from lagniappe.core.tools.site.admin import run_site_updates

        result = run_site_updates()
        if result.get("status") != "current":
            raise RuntimeError(f"Data migrations did not become current: {result}")
    elif arguments == ["rebuild-cache"]:
        from lagniappe.core.tools.site.admin import rebuild_application_cache

        rebuilt = rebuild_application_cache()
        result = {
            "rebuilt": rebuilt.rebuilt,
            "migration_status": rebuilt.migration_status,
        }
        if not rebuilt.rebuilt:
            raise RuntimeError(
                f"Cache rebuild was blocked: {rebuilt.migration_status}"
            )
    else:
        raise RuntimeError("Expected one data-lifecycle action: migrate or rebuild-cache.")
    print(json.dumps(result, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
