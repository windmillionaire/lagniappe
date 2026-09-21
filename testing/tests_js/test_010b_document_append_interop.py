"""Real Yjs/ProseMirror compatibility for server-created document additions."""

import json
from pathlib import Path
import subprocess

from lagniappe.core.tools.document_crdt import append_fragment
from lagniappe.core.tools.files.html import render_markdown


REPO_ROOT = Path(__file__).resolve().parents[2]
NODE_PROGRAM = REPO_ROOT / "testing/utility/js/document_append_interop.mjs"


# @source lagniappe/core/tools/document_crdt.py::append_fragment
# @matrix editor sync : document append browser-interop offline-replay
# @node-program testing/utility/js/document_append_interop.mjs
def test_server_append_round_trips_through_yjs_and_editor_schema(node_binary):
    baseline, _ = append_fragment(None, "<p>Existing 🌿</p>", "initial")
    html = render_markdown(
        "# Added\n\n**Bold** and *italic* [link](https://example.com).\n\n- [x] Complete\n\n| Field | Value |\n|---|---|\n| A | B |\n\n```\ncode\n```\n"
    )
    appended, _ = append_fragment(baseline, html, "append")
    result = subprocess.run(
        [node_binary, str(NODE_PROGRAM)],
        cwd=REPO_ROOT,
        input=json.dumps({"baseline": baseline, "appended": appended}),
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr + result.stdout
