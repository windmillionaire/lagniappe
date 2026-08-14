"""Node-backed checks for declarative Tiptap editor decorations."""

import textwrap


# @pairs editor:selected-text editor:replace-selection
def test_selection_highlight_decorations_and_range_mapping(run_node):
    run_node(
        textwrap.dedent(
            r"""
            import assert from "node:assert/strict";
            import { getSchema } from "@tiptap/core";
            import { StarterKit } from "@tiptap/starter-kit";
            import { EditorState, TextSelection } from "@tiptap/pm/state";
            import { SelectionHighlight } from "./src/script/elements/editor/extensions/highlight.mjs";

            const schema = getSchema([StarterKit]);
            const doc = schema.nodeFromJSON({
              type: "doc",
              content: [
                {
                  type: "paragraph",
                  content: [{ type: "text", text: "alpha" }],
                },
                {
                  type: "paragraph",
                  content: [{ type: "text", text: "beta" }],
                },
              ],
            });
            let state = EditorState.create({
              schema,
              doc,
              selection: TextSelection.create(doc, 2, 10),
            });

            const storage = SelectionHighlight.config.addStorage();
            const context = { storage };
            const decorationSpec =
              SelectionHighlight.config.addDecorations.call(context);
            const commands = SelectionHighlight.config.addCommands();
            const decorationUpdates = [];
            const editor = {
              state,
              storage: { selectionHighlight: storage },
              commands: {
                updateDecorations(name) {
                  decorationUpdates.push(name);
                  return true;
                },
              },
            };

            assert.equal(decorationSpec.update, "manual");
            assert.deepEqual(decorationSpec.create({ state }), []);

            assert.equal(commands.setSelectionHighlight()({ editor }), true);
            assert.deepEqual(decorationUpdates, ["selectionHighlight"]);
            assert.deepEqual(
              decorationSpec.create({ state }).map(({ from, to, attrs, kind }) => ({
                from,
                to,
                attrs,
                kind,
              })),
              [
                {
                  from: 2,
                  to: 6,
                  attrs: {
                    "data-role": "selection-highlight",
                    style: "background: #a8cde9;",
                  },
                  kind: "inline",
                },
                {
                  from: 8,
                  to: 10,
                  attrs: {
                    "data-role": "selection-highlight",
                    style: "background: #a8cde9;",
                  },
                  kind: "inline",
                },
              ],
            );

            const insertBefore = state.tr.insertText("Z", 1);
            state = state.apply(insertBefore);
            editor.state = state;
            SelectionHighlight.config.onTransaction.call(context, {
              transaction: insertBefore,
              appendedTransactions: [],
            });

            assert.deepEqual(
              commands.getSelectionHighlightRange()({ editor }),
              { from: 3, to: 11 },
            );
            assert.deepEqual(
              decorationSpec.create({ state }).map(({ from, to }) => [from, to]),
              [
                [3, 7],
                [9, 11],
              ],
            );
            assert.deepEqual(decorationUpdates, ["selectionHighlight"]);

            const deleteSelection = state.tr.delete(3, 11);
            state = state.apply(deleteSelection);
            editor.state = state;
            SelectionHighlight.config.onTransaction.call(context, {
              transaction: deleteSelection,
              appendedTransactions: [],
            });

            assert.equal(storage.active, false);
            assert.equal(storage.from, null);
            assert.equal(storage.to, null);
            assert.deepEqual(decorationSpec.create({ state }), []);

            assert.equal(commands.clearSelectionHighlight()({ editor }), true);
            assert.deepEqual(decorationUpdates, [
              "selectionHighlight",
              "selectionHighlight",
            ]);

            editor.state = state.apply(
              state.tr.setSelection(TextSelection.create(state.doc, 1)),
            );
            assert.equal(commands.setSelectionHighlight()({ editor }), true);
            assert.equal(storage.active, false);
            assert.equal(decorationUpdates.length, 2);
            """
        ),
        module=True,
    )


# @pair editor:remote-highlight
def test_remote_change_flash_decorations_map_and_expire(run_node):
    run_node(
        textwrap.dedent(
            r"""
            import assert from "node:assert/strict";
            import { getSchema } from "@tiptap/core";
            import { StarterKit } from "@tiptap/starter-kit";
            import { EditorState } from "@tiptap/pm/state";
            import { FlashRemoteChanges } from "./src/script/elements/editor/extensions/remote.mjs";

            const scheduled = new Map();
            let nextTimeout = 0;
            globalThis.setTimeout = (callback, delay) => {
              const id = ++nextTimeout;
              scheduled.set(id, {
                delay,
                callback() {
                  scheduled.delete(id);
                  callback();
                },
              });
              return id;
            };
            globalThis.clearTimeout = (id) => scheduled.delete(id);

            const schema = getSchema([StarterKit]);
            const makeState = (text) => EditorState.create({
              schema,
              doc: schema.nodeFromJSON({
                type: "doc",
                content: [
                  {
                    type: "paragraph",
                    content: [{ type: "text", text }],
                  },
                ],
              }),
            });

            const storage = FlashRemoteChanges.config.addStorage();
            storage.color = "rgb(1, 2, 3)";
            storage.author = "Ada";
            const context = { storage };
            const decorationSpec =
              FlashRemoteChanges.config.addDecorations.call(context);
            const decorationUpdates = [];
            const editor = {
              isDestroyed: false,
              commands: {
                updateDecorations(name) {
                  decorationUpdates.push(name);
                  return true;
                },
              },
            };

            assert.equal(decorationSpec.update, "manual");
            assert.deepEqual(decorationSpec.create(), []);

            let state = makeState("old text");
            const remote = state.tr
              .insertText("new ", 1)
              .setMeta("y-sync$", { remote: true });
            const afterRemote = state.apply(remote);
            const appendedLocal = afterRemote.tr.insertText("!", 1);
            state = afterRemote.apply(appendedLocal);

            FlashRemoteChanges.config.onTransaction.call(context, {
              editor,
              transaction: remote,
              appendedTransactions: [appendedLocal],
            });

            assert.deepEqual(decorationUpdates, ["flashRemoteChanges"]);
            assert.equal(storage.flashes.length, 1);
            const [flash] = decorationSpec.create();
            assert.equal(flash.kind, "inline");
            assert.deepEqual([flash.from, flash.to], [2, 6]);
            assert.equal(flash.attrs.class, "remote-change-flash");
            assert.equal(
              flash.attrs.style,
              "color: rgb(1, 2, 3); --remote-change-color: rgb(1, 2, 3);",
            );
            assert.equal(flash.attrs.title, "Edited by Ada");
            assert.equal(flash.attrs["data-editor-author"], "Ada");
            assert.match(flash.attrs["data-decoration-id"], /^flash-/);
            assert.equal(scheduled.size, 1);
            assert.equal([...scheduled.values()][0].delay, 1050);

            [...scheduled.values()][0].callback();
            assert.equal(storage.flashes.length, 0);
            assert.deepEqual(decorationSpec.create(), []);
            assert.equal(scheduled.size, 0);
            assert.deepEqual(decorationUpdates, [
              "flashRemoteChanges",
              "flashRemoteChanges",
            ]);

            const deletionOnly = state.tr
              .delete(2, 6)
              .setMeta("y-sync$", { remote: true });
            state = state.apply(deletionOnly);
            FlashRemoteChanges.config.onTransaction.call(context, {
              editor,
              transaction: deletionOnly,
              appendedTransactions: [],
            });
            assert.equal(storage.flashes.length, 0);
            assert.equal(decorationUpdates.length, 2);

            storage.color = "";
            const missingColor = state.tr
              .insertText("ignored ", 1)
              .setMeta("y-sync$", { remote: true });
            state = state.apply(missingColor);
            FlashRemoteChanges.config.onTransaction.call(context, {
              editor,
              transaction: missingColor,
              appendedTransactions: [],
            });
            assert.equal(storage.flashes.length, 0);
            assert.equal(decorationUpdates.length, 2);

            storage.color = "rgb(1, 2, 3)";
            const local = state.tr.insertText("local ", 1);
            state = state.apply(local);
            FlashRemoteChanges.config.onTransaction.call(context, {
              editor,
              transaction: local,
              appendedTransactions: [],
            });
            assert.equal(storage.flashes.length, 0);
            assert.equal(decorationUpdates.length, 2);

            state = makeState("replace me");
            const first = schema.nodes.paragraph.create(
              null,
              schema.text("first"),
            );
            const second = schema.nodes.paragraph.create(
              null,
              schema.text("second"),
            );
            const multiBlock = state.tr
              .replaceWith(0, state.doc.content.size, [first, second])
              .setMeta("y-sync$", { remote: true });
            state = state.apply(multiBlock);
            FlashRemoteChanges.config.onTransaction.call(context, {
              editor,
              transaction: multiBlock,
              appendedTransactions: [],
            });

            const blockFlashes = decorationSpec.create();
            assert.equal(blockFlashes.length, 2);
            assert.equal(
              blockFlashes.filter(
                ({ attrs }) => attrs["data-editor-author"] === "Ada",
              ).length,
              1,
            );
            assert.equal(
              new Set(
                blockFlashes.map(
                  ({ attrs }) => attrs["data-decoration-id"],
                ),
              ).size,
              1,
            );
            assert.equal(decorationUpdates.length, 3);
            assert.equal(scheduled.size, 1);

            FlashRemoteChanges.config.onDestroy.call(context);
            assert.equal(scheduled.size, 0);
            assert.equal(storage.timeouts.size, 0);
            """
        ),
        module=True,
    )
