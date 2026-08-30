import { mergeAttributes, Node } from "@tiptap/core";

/**
 * An editable, persistable source block for pasted Markdown awaiting a user
 * conversion decision.
 *
 * @testable true
 * @tests tests_js/test_048_markdown_paste.py::test_markdown_source_schema_is_distinct_from_code_blocks
 * @tests tests_e2e/004_projects/test_004d_document.py::test_keeping_pasted_markdown_preserves_source_block
 * @matrix editor markdown : paste source-block
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
