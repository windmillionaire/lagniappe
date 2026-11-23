import { mergeAttributes, Node } from "@tiptap/core";

/**
 * An editable, persistable source block for pasted Markdown awaiting a user
 * conversion decision.
 *
 */
export const MarkdownSource = Node.create({
	name: "markdownSource",
	priority: 1000,
	content: "text*",
	marks: "",
	group: "block",
	code: true,
	defining: true,

	addOptions() {
		return { HTMLAttributes: {} };
	},

	parseHTML() {
		return [
			{
				tag: 'pre[data-type="markdownSource"]',
				preserveWhitespace: "full",
			},
		];
	},

	renderHTML({ HTMLAttributes }) {
		return [
			"pre",
			mergeAttributes(this.options.HTMLAttributes, HTMLAttributes, {
				"data-type": this.name,
			}),
			["code", 0],
		];
	},
});
