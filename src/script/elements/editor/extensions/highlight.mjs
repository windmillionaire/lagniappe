import { Decoration, Extension } from "@tiptap/core";

const SELECTION_RANGE = "selectionHighlight";

// @testable false
// @covered-by src/script/elements/editor/extensions/highlight.mjs::SelectionHighlight
// @reason storage lookup is exercised through the selection highlight contract
const selectionRange = (editor) => {
	const range = editor?.storage?.trackedRanges?.ranges?.get(SELECTION_RANGE);
	return range ? { ...range } : null;
};

/**
 * @testable true
 * @tests tests_js/test_041_editor_decorations.py::test_selection_highlight_decorations_and_range_mapping
 * @tests tests_e2e/005_pages/test_005g_page_document_ai.py::test_generate_text_replaces_selection_and_posts_selected_text
 * @matrix ai editor : replace-selection selected-text
 */
export const SelectionHighlight = Extension.create({
	name: "selectionHighlight",

	addCommands() {
		return {
			setSelectionHighlight:
				() =>
				({ editor }) => {
					const { from, to } = editor.state.selection;
					if (from !== to) {
						editor.commands.setTrackedRange(SELECTION_RANGE, { from, to });
						editor.commands.updateDecorations("selectionHighlight");
					}
					return true;
				},
			clearSelectionHighlight:
				() =>
				({ editor }) => {
					editor.commands.clearTrackedRange(SELECTION_RANGE);
					editor.commands.updateDecorations("selectionHighlight");
					return true;
				},
			getSelectionHighlightRange:
				() =>
				({ editor }) => {
					return selectionRange(editor);
				},
		};
	},

	addDecorations() {
		const editor = this.editor;

		return {
			update: "manual",
			create: ({ state }) => {
				const range = selectionRange(editor);
				if (!range) return [];

				const docEnd = state.doc.content.size;
				const rangeStart = Math.min(range.from, range.to);
				const rangeEnd = Math.max(range.from, range.to);
				const from = Math.max(0, Math.min(rangeStart, docEnd));
				const to = Math.max(from, Math.min(rangeEnd, docEnd));
				if (from >= to) return [];

				const decorations = [];
				state.doc.nodesBetween(from, to, (node, pos) => {
					if (!node.isText) return true;
					const start = Math.max(from, pos);
					const end = Math.min(to, pos + node.nodeSize);
					if (end > start) {
						decorations.push(
							Decoration.Inline(start, end, {
								"data-role": "selection-highlight",
								style: "background: #a8cde9;",
							}),
						);
					}
					return true;
				});

				return decorations;
			},
		};
	},
});
