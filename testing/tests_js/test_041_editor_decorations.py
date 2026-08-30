"""Node-backed checks for declarative Tiptap editor decorations."""

import textwrap


# @matrix editor : replace-selection selected-text
def test_selection_highlight_decorations_and_range_mapping(run_node):
    run_node(
        textwrap.dedent(
            r"""
            import assert from "node:assert/strict";
            import { getSchema } from "@tiptap/core";
            import { StarterKit } from "@tiptap/starter-kit";
            import { EditorState, TextSelection } from "@tiptap/pm/state";
            import { SelectionHighlight } from "./src/script/elements/editor/extensions/highlight.mjs";
            import { TrackedRanges } from "./src/script/elements/editor/extensions/trackedRanges.mjs";

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

            const trackedStorage = TrackedRanges.config.addStorage();
            const trackedContext = { storage: trackedStorage };
            const trackedCommands = TrackedRanges.config.addCommands();
            let editor;
            const dispatch = transaction => {
              state = state.apply(transaction);
              editor.state = state;
              TrackedRanges.config.onTransaction.call(trackedContext, {
                transaction,
                appendedTransactions: [],
              });
            };
            editor = {
              state,
              storage: { trackedRanges: trackedStorage },
              commands: {},
            };
            editor.commands.setTrackedRange = (key, range) =>
              trackedCommands.setTrackedRange(key, range)({
                state,
                tr: state.tr,
                dispatch,
              });
            editor.commands.clearTrackedRange = key =>
              trackedCommands.clearTrackedRange(key)({ tr: state.tr, dispatch });

            const context = { editor };
            const decorationSpec =
              SelectionHighlight.config.addDecorations.call(context);
            const commands = SelectionHighlight.config.addCommands();
            const decorationUpdates = [];
            editor.commands.updateDecorations = name => {
              decorationUpdates.push(name);
              return true;
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
            dispatch(insertBefore);

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
            dispatch(deleteSelection);

            assert.equal(trackedStorage.ranges.has("selectionHighlight"), false);
            assert.deepEqual(decorationSpec.create({ state }), []);

            assert.equal(commands.clearSelectionHighlight()({ editor }), true);
            assert.deepEqual(decorationUpdates, [
              "selectionHighlight",
              "selectionHighlight",
            ]);

            dispatch(state.tr.setSelection(TextSelection.create(state.doc, 1)));
            assert.equal(commands.setSelectionHighlight()({ editor }), true);
            assert.equal(trackedStorage.ranges.has("selectionHighlight"), false);
            assert.equal(decorationUpdates.length, 2);
            """
        ),
        module=True,
    )


# @matrix ai editor markdown : inserted-range range-mapping
def test_named_tracked_ranges_map_independently(run_node):
    run_node(
        textwrap.dedent(
            r"""
            import assert from "node:assert/strict";
            import { getSchema } from "@tiptap/core";
            import { StarterKit } from "@tiptap/starter-kit";
            import { EditorState } from "@tiptap/pm/state";
            import {
              setTrackedRangeInTransaction,
              TrackedRanges,
            } from "./src/script/elements/editor/extensions/trackedRanges.mjs";

            const schema = getSchema([StarterKit]);
            let state = EditorState.create({
              schema,
              doc: schema.nodeFromJSON({
                type: "doc",
                content: [
                  { type: "paragraph", content: [{ type: "text", text: "alpha" }] },
                  { type: "paragraph", content: [{ type: "text", text: "beta" }] },
                ],
              }),
            });
            const storage = TrackedRanges.config.addStorage();
            const context = { storage };
            const apply = (transaction, appendedTransactions = []) => {
              state = state.apply(transaction);
              for (const appended of appendedTransactions) state = state.apply(appended);
              TrackedRanges.config.onTransaction.call(context, {
                transaction,
                appendedTransactions,
              });
            };

            const setup = state.tr;
            setTrackedRangeInTransaction(setup, "first", { from: 2, to: 6 });
            setTrackedRangeInTransaction(setup, "second", { from: 8, to: 12 });
            apply(setup);
            assert.deepEqual([...storage.ranges], [
              ["first", { from: 2, to: 6 }],
              ["second", { from: 8, to: 12 }],
            ]);

            apply(state.tr.insertText("Z", 1));
            assert.deepEqual([...storage.ranges], [
              ["first", { from: 3, to: 7 }],
              ["second", { from: 9, to: 13 }],
            ]);

            apply(state.tr.delete(3, 7));
            assert.equal(storage.ranges.has("first"), false);
            assert.deepEqual(storage.ranges.get("second"), { from: 5, to: 9 });

            const primary = state.tr.insertText("P", 1);
            const intermediate = state.apply(primary);
            const appended = intermediate.tr.insertText("Q", 1);
            apply(primary, [appended]);
            assert.deepEqual(storage.ranges.get("second"), { from: 7, to: 11 });
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
