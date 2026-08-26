"""Isolated runtime-owned migration action for data recovery."""

from __future__ import annotations

import json
import sys


# @testable false
# @covered-by installer/data_lifecycle/provider.py::ProviderContext
# @reason subprocess-only adapter is owned by the restore provider boundary
def main(argv=None):
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments == ["migrate"]:
        from lagniappe.core.tools.database.migrations import run_data_migrations

        result = run_data_migrations()
        if result.get("status") != "current":
            raise RuntimeError(f"Data migrations did not become current: {result}")
    else:
        raise RuntimeError("Expected the data-lifecycle action: migrate.")
    print(json.dumps(result, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
