import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { getSchema } from "@tiptap/core";
import { TaskItem, TaskList } from "@tiptap/extension-list";
import { TableKit } from "@tiptap/extension-table";
import { StarterKit } from "@tiptap/starter-kit";
import { yDocToProsemirrorJSON } from "y-prosemirror";
import * as Y from "yjs";

const schema = getSchema([StarterKit, TaskList, TaskItem, TableKit]);
const data = JSON.parse(readFileSync(0, "utf8"));
const ydoc = new Y.Doc();
Y.applyUpdate(ydoc, Buffer.from(data.baseline, "base64"));
const text = ydoc.getXmlFragment("default").get(0).get(0);
text.insert(text.length, " offline draft");
Y.applyUpdate(ydoc, Buffer.from(data.appended, "base64"));
const json = yDocToProsemirrorJSON(ydoc, "default");
schema.nodeFromJSON(json).check();
assert.equal(json.content[0].content[0].text, "Existing 🌿 offline draft");
assert.equal(json.content[1].type, "heading");
assert.equal(json.content[3].type, "taskList");
assert.equal(json.content[3].content[0].attrs.checked, true);
assert.ok(
	json.content[2].content.some((node) =>
		node.marks?.some((mark) => mark.type === "bold"),
	),
);
assert.ok(
	json.content[2].content.some((node) =>
		node.marks?.some((mark) => mark.type === "link"),
	),
);
Y.applyUpdate(ydoc, Buffer.from(data.appended, "base64"));
const restored = yDocToProsemirrorJSON(ydoc, "default");
schema.nodeFromJSON(restored).check();
assert.equal(restored.content.length, json.content.length);
assert.equal(ydoc.getMap("lagniappeReports").get("append").state, "applied");
assert.equal(restored.content[0].content[0].text, "Existing 🌿 offline draft");
