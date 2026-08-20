import { Decoration, Extension } from "@tiptap/core";

/**
 * @testable true
 * @tests tests_js/test_041_editor_decorations.py::test_selection_highlight_decorations_and_range_mapping
 * @tests tests_e2e/005_pages/test_005g_page_document_ai.py::test_generate_text_replaces_selection_and_posts_selected_text
 * @features editor ai
 * @dimensions selected-text replace-selection
 */
export const SelectionHighlight = Extension.create({
	name: "selectionHighlight",

	addStorage() {
		return {
			active: false,
			from: null,
			to: null,
		};
	},

	addCommands() {
		return {
			setSelectionHighlight:
				() =>
				({ editor }) => {
					const { from, to } = editor.state.selection;
					if (from !== to) {
						editor.storage.selectionHighlight.active = true;
						editor.storage.selectionHighlight.from = from;
						editor.storage.selectionHighlight.to = to;
						editor.commands.updateDecorations("selectionHighlight");
					}
					return true;
				},
			clearSelectionHighlight:
				() =>
				({ editor }) => {
					editor.storage.selectionHighlight.active = false;
					editor.storage.selectionHighlight.from = null;
					editor.storage.selectionHighlight.to = null;
					editor.commands.updateDecorations("selectionHighlight");
					return true;
				},
			getSelectionHighlightRange:
				() =>
				({ editor }) => {
					const storage = editor.storage.selectionHighlight;
					if (storage.active && storage.from !== null && storage.to !== null) {
						return { from: storage.from, to: storage.to };
					}
					return null;
				},
		};
	},

	addDecorations() {
		const storage = this.storage;

		return {
			update: "manual",
			create: ({ state }) => {
				if (!storage.active || storage.from === null || storage.to === null) {
					return [];
				}

				const docEnd = state.doc.content.size;
				const rangeStart = Math.min(storage.from, storage.to);
				const rangeEnd = Math.max(storage.from, storage.to);
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

	onTransaction({ transaction, appendedTransactions }) {
		const storage = this.storage;
		if (!storage.active || storage.from === null || storage.to === null) {
			return;
		}

		for (const tr of [transaction, ...appendedTransactions]) {
			if (!tr.docChanged) continue;

			const from = tr.mapping.map(storage.from, 1);
			const to = tr.mapping.map(storage.to, -1);
			if (from >= to) {
				storage.active = false;
				storage.from = null;
				storage.to = null;
				return;
			}

			storage.from = from;
			storage.to = to;
		}
	},
});
