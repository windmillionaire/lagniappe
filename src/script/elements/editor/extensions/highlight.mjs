import { Extension } from "@tiptap/core";
import { Plugin, PluginKey } from "@tiptap/pm/state";
import { Decoration, DecorationSet } from "@tiptap/pm/view";

/**
 * @testable true
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
						editor.view.dispatch(editor.state.tr);
					}
					return true;
				},
			clearSelectionHighlight:
				() =>
				({ editor }) => {
					editor.storage.selectionHighlight.active = false;
					editor.storage.selectionHighlight.from = null;
					editor.storage.selectionHighlight.to = null;
					editor.view.dispatch(editor.state.tr);
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

	addProseMirrorPlugins() {
		const storage = this.storage;

		return [
			new Plugin({
				key: new PluginKey("selectionHighlight"),
				props: {
					decorations: (state) => {
						if (
							!storage.active ||
							storage.from === null ||
							storage.to === null
						) {
							return DecorationSet.empty;
						}

						const docEnd = state.doc.content.size;
						const rangeStart = Math.min(storage.from, storage.to);
						const rangeEnd = Math.max(storage.from, storage.to);
						const from = Math.max(0, Math.min(rangeStart, docEnd));
						const to = Math.max(from, Math.min(rangeEnd, docEnd));
						if (from >= to) {
							return DecorationSet.empty;
						}
						const decorations = [];

						state.doc.nodesBetween(from, to, (node, pos) => {
							if (!node.isText) return true;
							const start = Math.max(from, pos);
							const end = Math.min(to, pos + node.nodeSize);
							if (end > start) {
								decorations.push(
									Decoration.inline(start, end, {
										style: "background: #a8cde9;",
									}),
								);
							}
							return true;
						});

						return DecorationSet.create(state.doc, decorations);
					},
				},
			}),
		];
	},
});
