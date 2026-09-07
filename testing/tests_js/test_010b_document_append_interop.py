"""Real Yjs/ProseMirror compatibility for server-created document additions."""

import json

from lagniappe.core.tools.document_crdt import append_fragment, undo_fragment
from lagniappe.core.tools.files.html import render_markdown


# @source lagniappe/core/tools/document_crdt.py::append_fragment
# @source lagniappe/core/tools/document_crdt.py::undo_fragment
# @matrix editor sync : document append browser-interop offline-replay undo
def test_server_append_round_trips_through_yjs_and_editor_schema(run_node):
    baseline, _ = append_fragment(None, "<p>Existing 🌿</p>", "initial")
    html = render_markdown(
        "# Added\n\n**Bold** and *italic* [link](https://example.com).\n\n- [x] Complete\n\n| Field | Value |\n|---|---|\n| A | B |\n\n```\ncode\n```\n"
    )
    appended, _ = append_fragment(baseline, html, "append")
    undone = undo_fragment(appended, "append")
    payload = json.dumps({"baseline": baseline, "appended": appended, "undone": undone})
    run_node(
        r"""
const assert = require('node:assert/strict');
const Y = require('yjs');
const { yDocToProsemirrorJSON } = require('y-prosemirror');
const { getSchema } = require('@tiptap/core');
const { StarterKit } = require('@tiptap/starter-kit');
const { TaskList, TaskItem } = require('@tiptap/extension-list');
const { TableKit } = require('@tiptap/extension-table');
const schema = getSchema([StarterKit, TaskList, TaskItem, TableKit]);
const data = PAYLOAD;
const ydoc = new Y.Doc();
Y.applyUpdate(ydoc, Buffer.from(data.baseline, 'base64'));
const text = ydoc.getXmlFragment('default').get(0).get(0);
text.insert(text.length, ' offline draft');
Y.applyUpdate(ydoc, Buffer.from(data.appended, 'base64'));
const json = yDocToProsemirrorJSON(ydoc, 'default');
schema.nodeFromJSON(json).check();
assert.equal(json.content[0].content[0].text, 'Existing 🌿 offline draft');
assert.equal(json.content[1].type, 'heading');
assert.equal(json.content[3].type, 'taskList');
assert.equal(json.content[3].content[0].attrs.checked, true);
assert.ok(json.content[2].content.some(node => node.marks?.some(mark => mark.type === 'bold')));
assert.ok(json.content[2].content.some(node => node.marks?.some(mark => mark.type === 'link')));
Y.applyUpdate(ydoc, Buffer.from(data.undone, 'base64'));
const restored = yDocToProsemirrorJSON(ydoc, 'default');
schema.nodeFromJSON(restored).check();
assert.equal(restored.content.length, 1);
assert.equal(restored.content[0].content[0].text, 'Existing 🌿 offline draft');
""".replace("PAYLOAD", payload)
    )
