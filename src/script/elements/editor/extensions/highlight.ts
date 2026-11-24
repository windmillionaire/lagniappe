import { Decoration, Extension } from "@tiptap/core";

const SELECTION_RANGE = "selectionHighlight";

const selectionRange = (editor) => {
	const range = editor?.storage?.trackedRanges?.ranges?.get(SELECTION_RANGE);
	return range ? { ...range } : null;
};

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
