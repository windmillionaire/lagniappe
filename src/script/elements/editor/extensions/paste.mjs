import { Extension } from "@tiptap/core";
import { Plugin, PluginKey, TextSelection } from "@tiptap/pm/state";
import { setTrackedRangeInTransaction } from "./trackedRanges.mjs";

const BLOCK_MARKDOWN_PATTERNS = [
	/^\s{0,3}#{1,6}\s+\S/,
	/^\s{0,3}(?:\x60{3}|~{3})/,
	/^\s{0,3}>\s?\S/,
	/^\s{0,3}(?:[-+*]|\d+\.)\s+\S/,
	/^\s{0,3}([-*_])(?:\s*\1){2,}\s*$/,
];
const INLINE_MARKDOWN_PATTERNS = [
	/\x60[^\x60\n]+\x60/,
	/\*\*[^*\n]+\*\*/,
	/__[^_\n]+__/,
	/~~[^~\n]+~~/,
	/(^|[^*])\*(?!\s)[^*\n]+\*/,
	/(^|[^_])_(?!\s)[^_\n]+_/,
	/!?\[[^\]\n]+\]\([^\s)]+(?:\s+"[^"]*")?\)/,
];
const HTML_FRAGMENT_PATTERN = /<\/?[a-z][^>]*>/i;
const TABLE_DIVIDER_PATTERN =
	/^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*$/;
const SETEXT_PATTERN = /^\s{0,3}(?:=+|-+)\s*$/;
const FENCE_PATTERN = /^\s{0,3}(\x60{3}|~{3})/;
const INDENTED_CODE_PATTERN = /^(?: {4}|\t)/;
const HARD_BREAK_PATTERN = /(?: {2,}|\\)$/;
const SOFT_WRAP_MINIMUM = 40;

// @testable false
// @covered-by src/script/elements/editor/extensions/paste.mjs::looksLikeConvertibleMarkup
// @reason clipboard line-ending normalization is part of Markdown detection
const normalizeLineEndings = (value) =>
	String(value || "")
		.replaceAll("\r\n", "\n")
		.replaceAll("\r", "\n");

/**
 * Conservatively identify plain clipboard text worth offering to the shared
 * Markdown renderer. This detects; it never interprets or converts source.
 *
 * @testable true
 * @tests tests_js/test_048_markdown_paste.py::test_markdown_detection_is_conservative
 * @matrix editor markdown : detection paste soft-wrap
 */
export const looksLikeConvertibleMarkup = (content) => {
	const source = normalizeLineEndings(content);
	if (!source.trim()) return false;
	const lines = source.split("\n");

	if (
		HTML_FRAGMENT_PATTERN.test(source) ||
		lines.some((line) =>
			BLOCK_MARKDOWN_PATTERNS.some((pattern) => pattern.test(line)),
		) ||
		lines.some((line, index) => {
			return index > 0 && lines[index - 1].trim() && SETEXT_PATTERN.test(line);
		}) ||
		lines.some((line) => TABLE_DIVIDER_PATTERN.test(line)) ||
		INLINE_MARKDOWN_PATTERNS.some((pattern) => pattern.test(source))
	) {
		return true;
	}

	let fence = null;
	const proseLines = lines.map((line) => {
		const marker = line.match(FENCE_PATTERN)?.[1] || null;
		if (marker) {
			fence = fence === marker ? null : fence || marker;
			return false;
		}
		return !fence && !INDENTED_CODE_PATTERN.test(line);
	});

	return lines.some((line, index) => {
		const next = lines[index + 1];
		if (next === undefined || !proseLines[index] || !proseLines[index + 1]) {
			return false;
		}
		return (
			line.trim().length >= SOFT_WRAP_MINIMUM &&
			next.trim() &&
			!HARD_BREAK_PATTERN.test(line)
		);
	});
};

/**
 * Insert source as one MarkdownSource node and atomically register its exact
 * transaction-produced range.
 *
 * @testable true
 * @tests tests_js/test_048_markdown_paste.py::test_source_insertion_tracks_the_inserted_block
 * @matrix editor markdown : inserted-range paste source-block
 */
export const insertMarkdownSource = (view, content, rangeKey) => {
	const { state } = view;
	const sourceType = state.schema.nodes.markdownSource;
	if (!sourceType || typeof rangeKey !== "string" || !rangeKey) return false;

	const source = normalizeLineEndings(content);
	const node = sourceType.create(
		null,
		source ? state.schema.text(source) : undefined,
	);
	const transaction = state.tr.replaceSelectionWith(node);
	let range = null;
	transaction.doc.descendants((child, position) => {
		if (child === node) {
			range = { from: position, to: position + node.nodeSize };
		}
		return range === null;
	});
	if (!range) return false;

	transaction.setSelection(TextSelection.create(transaction.doc, range.to - 1));
	setTrackedRangeInTransaction(transaction, rangeKey, range);
	view.dispatch(transaction.scrollIntoView());
	return true;
};

/**
 * Intercept only detected plain-text markup when an owning toolbar can offer
 * an explicit conversion decision.
 *
 * @testable true
 * @tests tests_e2e/004_projects/test_004d_document.py::test_pasting_markdown_table_preserves_table_after_reload
 * @tests tests_e2e/004_projects/test_004d_document.py::test_pasting_plain_html_inserts_safe_formatted_content
 * @tests tests_e2e/004_projects/test_004d_document.py::test_pasting_common_markdown_preserves_formatting
 * @tests tests_e2e/004_projects/test_004d_document.py::test_keeping_pasted_markdown_preserves_source_block
 * @matrix editor markdown : conversion paste source-block
 */
export const EditorPaste = Extension.create({
	name: "editorPaste",

	addStorage() {
		return {
			confirm: null,
			sequence: 0,
		};
	},

	addProseMirrorPlugins() {
		const editor = this.editor;
		const storage = this.storage;
		return [
			new Plugin({
				key: new PluginKey("editorPaste"),
				props: {
					handlePaste: (view, event) => {
						const clipboard = event.clipboardData;
						if (!clipboard || typeof storage.confirm !== "function") {
							return false;
						}

						const richHtml = clipboard.getData("text/html");
						const text = clipboard.getData("text/plain");
						if (!text || richHtml || !looksLikeConvertibleMarkup(text)) {
							return false;
						}

						const rangeKey = ["markdownPaste", ++storage.sequence].join(":");
						if (!insertMarkdownSource(view, text, rangeKey)) return false;

						event.preventDefault();
						storage.confirm({ editor, rangeKey });
						return true;
					},
				},
			}),
		];
	},
});
