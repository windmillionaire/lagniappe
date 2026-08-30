"""Node-backed checks for Markdown paste detection and source insertion."""

import textwrap


# @matrix editor markdown : detection paste soft-wrap
def test_markdown_detection_is_conservative(run_node):
    run_node(
        textwrap.dedent(
            r"""
            import assert from "node:assert/strict";
            import { looksLikeConvertibleMarkup } from "./src/script/elements/editor/extensions/paste.mjs";

            for (const source of [
              "# Heading",
              "- [x] Completed task",
              "A **formatted** sentence.",
              "| Name | Value |\n| --- | --- |\n| A | B |",
              "<p>Plain HTML source</p>",
              "This is a long line of copied prose that should clearly exceed the threshold\nand continue on the next source line.",
            ]) {
              assert.equal(looksLikeConvertibleMarkup(source), true, source);
            }

            for (const source of [
              "Ordinary single-line text",
              "123 Main Street\nSeattle, WA",
              "Short line\nAnother short line",
              "This is a long line with an intentional Markdown hard break.  \nNext line",
              "    const longIndentedCodeLine = 'not wrapped prose despite its length';\n    return longIndentedCodeLine;",
            ]) {
              assert.equal(looksLikeConvertibleMarkup(source), false, source);
            }
            """
        ),
        module=True,
    )


# @matrix editor markdown : source-block
def test_markdown_source_schema_is_distinct_from_code_blocks(run_node):
    run_node(
        textwrap.dedent(
            r"""
            import assert from "node:assert/strict";
            import { getSchema } from "@tiptap/core";
            import { StarterKit } from "@tiptap/starter-kit";
            import { MarkdownSource } from "./src/script/elements/editor/extensions/markdownSource.mjs";

            const schema = getSchema([StarterKit, MarkdownSource]);
            const source = schema.nodes.markdownSource.create(
              null,
              schema.text("# Editable source\n- [ ] Task"),
            );

            assert.equal(source.type.name, "markdownSource");
            assert.equal(source.type.spec.code, true);
            assert.equal(source.textContent, "# Editable source\n- [ ] Task");
            assert.notEqual(source.type, schema.nodes.codeBlock);
            assert.equal(source.type.spec.parseDOM[0].tag, 'pre[data-type="markdownSource"]');
            """
        ),
        module=True,
    )


# @matrix editor markdown : inserted-range paste source-block
def test_source_insertion_tracks_the_inserted_block(run_node):
    run_node(
        textwrap.dedent(
            r"""
            import assert from "node:assert/strict";
            import { getSchema } from "@tiptap/core";
            import { StarterKit } from "@tiptap/starter-kit";
            import { EditorState, TextSelection } from "@tiptap/pm/state";
            import { MarkdownSource } from "./src/script/elements/editor/extensions/markdownSource.mjs";
            import { insertMarkdownSource } from "./src/script/elements/editor/extensions/paste.mjs";
            import { TrackedRanges } from "./src/script/elements/editor/extensions/trackedRanges.mjs";

            const schema = getSchema([StarterKit, MarkdownSource]);
            const doc = schema.nodeFromJSON({
              type: "doc",
              content: [
                { type: "paragraph", content: [{ type: "text", text: "Existing" }] },
              ],
            });
            let state = EditorState.create({
              schema,
              doc,
              selection: TextSelection.create(doc, 1),
            });
            const storage = TrackedRanges.config.addStorage();
            const context = { storage };
            const view = {
              state,
              dispatch(transaction) {
                state = state.apply(transaction);
                this.state = state;
                TrackedRanges.config.onTransaction.call(context, {
                  transaction,
                  appendedTransactions: [],
                });
              },
            };

            assert.equal(
              insertMarkdownSource(view, "# Source\r\n- [ ] Task", "paste"),
              true,
            );
            const range = storage.ranges.get("paste");
            const source = state.doc.nodeAt(range.from);

            assert.deepEqual(range, { from: 0, to: source.nodeSize });
            assert.equal(source.type.name, "markdownSource");
            assert.equal(source.textContent, "# Source\n- [ ] Task");
            assert.equal(state.selection.$from.parent.type.name, "markdownSource");
            """
        ),
        module=True,
    )
