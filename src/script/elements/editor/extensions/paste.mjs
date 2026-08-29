import { Extension } from "@tiptap/core";
import { Plugin, PluginKey } from "@tiptap/pm/state";

const SAFE_TAGS = new Set([
	"a",
	"blockquote",
	"br",
	"code",
	"em",
	"h1",
	"h2",
	"h3",
	"h4",
	"h5",
	"h6",
	"hr",
	"li",
	"ol",
	"p",
	"pre",
	"s",
	"strike",
	"strong",
	"sub",
	"sup",
	"table",
	"tbody",
	"td",
	"th",
	"thead",
	"tr",
	"u",
	"ul",
]);

const DROP_TAGS = new Set([
	"applet",
	"base",
	"button",
	"canvas",
	"embed",
	"form",
	"frame",
	"frameset",
	"iframe",
	"img",
	"input",
	"link",
	"math",
	"meta",
	"noscript",
	"object",
	"option",
	"picture",
	"script",
	"select",
	"source",
	"style",
	"svg",
	"textarea",
	"video",
]);

const SAFE_LINK_SCHEMES = new Set(["", "http", "https", "mailto"]);
const HTML_FRAGMENT_PATTERN = /<\/?[a-z][\s\S]*>/i;

// @testable false
// @covered-by src/script/elements/editor/extensions/paste.mjs::markdownToHtml
// @reason tiny string escaping helper owned by paste normalization
const escapeHtml = (value) =>
	String(value ?? "")
		.replaceAll("&", "&amp;")
		.replaceAll("<", "&lt;")
		.replaceAll(">", "&gt;")
		.replaceAll('"', "&quot;");

// @testable false
// @covered-by src/script/elements/editor/extensions/paste.mjs::sanitizePastedHtml
// @reason link scheme filtering is part of the paste sanitizer contract
const safeHref = (href) => {
	const value = String(href || "").trim();
	if (!value) return null;

	try {
		const parsed = new URL(value, globalThis.window?.location?.href);
		if (SAFE_LINK_SCHEMES.has(parsed.protocol.replace(":", "").toLowerCase())) {
			return value;
		}
	} catch (_error) {
		if (value.startsWith("#") || value.startsWith("/")) return value;
	}

	return null;
};

// @testable false
// @covered-by src/script/elements/editor/extensions/paste.mjs::sanitizePastedHtml
// @reason table cell span filtering is part of the paste sanitizer contract
const safeSpan = (value) => {
	const span = Number.parseInt(value, 10);
	return Number.isInteger(span) && span > 1 && span <= 100
		? String(span)
		: null;
};

// @testable false
// @covered-by src/script/elements/editor/extensions/paste.mjs::sanitizePastedHtml
// @reason helper-owned-by-paste-sanitizer
const unwrapElement = (element) => {
	const parent = element.parentNode;
	if (!parent) return;

	while (element.firstChild) parent.insertBefore(element.firstChild, element);
	element.remove();
};

// @testable true
// @tests tests_e2e/004_projects/test_004d_document.py::test_pasting_plain_html_inserts_safe_formatted_content
// @matrix editor : paste-html sanitization
export const sanitizePastedHtml = (content) => {
	if (!content || !HTML_FRAGMENT_PATTERN.test(content)) return "";

	const parser = new DOMParser();
	const document = parser.parseFromString(content, "text/html");

	for (const node of Array.from(
		document.body.querySelectorAll("script, style, template"),
	)) {
		node.remove();
	}

	const walker = document.createTreeWalker(
		document.body,
		NodeFilter.SHOW_ELEMENT,
	);
	const elements = [];
	while (walker.nextNode()) elements.push(walker.currentNode);

	for (const element of elements) {
		const name = element.tagName.toLowerCase();

		if (DROP_TAGS.has(name)) {
			element.remove();
			continue;
		}

		if (!SAFE_TAGS.has(name)) {
			unwrapElement(element);
			continue;
		}

		const attrs = {};
		if (name === "a") {
			const href = safeHref(element.getAttribute("href"));
			if (href) attrs.href = href;
			const title = element.getAttribute("title");
			if (title) attrs.title = title;
		} else if (name === "td" || name === "th") {
			const colspan = safeSpan(element.getAttribute("colspan"));
			const rowspan = safeSpan(element.getAttribute("rowspan"));
			if (colspan) attrs.colspan = colspan;
			if (rowspan) attrs.rowspan = rowspan;
		}

		for (const attr of Array.from(element.attributes)) {
			element.removeAttribute(attr.name);
		}
		for (const [key, value] of Object.entries(attrs)) {
			element.setAttribute(key, value);
		}
	}

	return document.body.innerHTML.trim();
};

// @testable false
// @covered-by src/script/elements/editor/extensions/paste.mjs::markdownToHtml
// @reason helper-owned-by-markdown-table-parser
const splitMarkdownRow = (line) => {
	const trimmed = line.trim();
	const source = trimmed.startsWith("|") ? trimmed.slice(1) : trimmed;
	const withoutTrailingPipe = source.endsWith("|")
		? source.slice(0, -1)
		: source;
	const cells = [];
	let current = "";
	let escaped = false;

	for (const char of withoutTrailingPipe) {
		if (escaped) {
			current += char;
			escaped = false;
		} else if (char === "\\") {
			escaped = true;
		} else if (char === "|") {
			cells.push(current.trim());
			current = "";
		} else {
			current += char;
		}
	}
	cells.push(current.trim());

	return cells;
};

// @testable false
// @covered-by src/script/elements/editor/extensions/paste.mjs::markdownToHtml
// @reason helper-owned-by-markdown-table-parser
const isDividerRow = (line) => {
	const cells = splitMarkdownRow(line);
	return (
		cells.length > 1 &&
		cells.every((cell) => /^:?-{3,}:?$/.test(cell.replaceAll(" ", "")))
	);
};

// @testable false
// @covered-by src/script/elements/editor/extensions/paste.mjs::markdownToHtml
// @reason helper-owned-by-markdown-table-parser
const looksLikeTableRow = (line) =>
	line.includes("|") && splitMarkdownRow(line).length > 1;

// @testable false
// @covered-by src/script/elements/editor/extensions/paste.mjs::markdownToHtml
// @reason helper-owned-by-markdown-parser
const renderInlineMarkdown = (value) => {
	const parts = String(value ?? "").split(/(`[^`]+`)/g);
	const linkPlaceholders = [];

	// @testable false
	// @covered-by src/script/elements/editor/extensions/paste.mjs::renderInlineMarkdown
	// @reason helper-owned-by-inline-markdown-renderer
	const linkToken = (html) => {
		const token = `\u0000LINK${linkPlaceholders.length}\u0000`;
		linkPlaceholders.push([token, html]);
		return token;
	};

	const html = parts
		.map((part) => {
			if (part.startsWith("`") && part.endsWith("`") && part.length > 1) {
				return `<code>${escapeHtml(part.slice(1, -1))}</code>`;
			}

			let linked = "";
			let start = 0;
			const linkPattern = /\[([^\]]+)\]\(([^)\s]+)(?:\s+"([^"]*)")?\)/g;

			for (const match of part.matchAll(linkPattern)) {
				linked += escapeHtml(part.slice(start, match.index));

				const href = safeHref(match[2]);
				if (href) {
					const title = match[3] ? ` title="${escapeHtml(match[3])}"` : "";
					linked += linkToken(
						`<a href="${escapeHtml(href)}"${title}>${escapeHtml(match[1])}</a>`,
					);
				} else {
					linked += escapeHtml(match[1]);
				}

				start = match.index + match[0].length;
			}

			linked += escapeHtml(part.slice(start));
			return linked
				.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
				.replace(/__([^_]+)__/g, "<strong>$1</strong>")
				.replace(/~~([^~]+)~~/g, "<s>$1</s>")
				.replace(/\*([^*\s][^*]*?)\*/g, "<em>$1</em>")
				.replace(/_([^_\s][^_]*?)_/g, "<em>$1</em>");
		})
		.join("");

	return linkPlaceholders.reduce(
		(result, [token, link]) => result.replaceAll(token, link),
		html,
	);
};

// @testable false
// @covered-by src/script/elements/editor/extensions/paste.mjs::markdownToHtml
// @reason helper-owned-by-markdown-parser
const renderList = (type, items) =>
	`<${type}>${items.map((item) => `<li><p>${renderInlineMarkdown(item)}</p></li>`).join("")}</${type}>`;

// @testable false
// @covered-by src/script/elements/editor/extensions/paste.mjs::markdownToHtml
// @reason helper-owned-by-markdown-parser
const renderMarkdownTable = (headers, rows) =>
	[
		"<table>",
		"<thead><tr>",
		...headers.map((cell) => `<th><p>${renderInlineMarkdown(cell)}</p></th>`),
		"</tr></thead>",
		"<tbody>",
		...rows.map((row) => {
			const cells = headers.map((_, cellIndex) => row[cellIndex] || "");
			return [
				"<tr>",
				...cells.map((cell) => `<td><p>${renderInlineMarkdown(cell)}</p></td>`),
				"</tr>",
			].join("");
		}),
		"</tbody>",
		"</table>",
	].join("");

// @testable false
// @covered-by src/script/elements/editor/extensions/paste.mjs::markdownToHtml
// @reason helper-owned-by-markdown-parser
const renderCodeBlock = (lines) =>
	`<pre><code>${escapeHtml(lines.join("\n"))}</code></pre>`;

// @testable false
// @covered-by src/script/elements/editor/extensions/paste.mjs::markdownToHtml
// @reason helper-owned-by-markdown-parser
const headingMatch = (line) => line.match(/^(#{1,6})\s+(.+)$/);

// @testable false
// @covered-by src/script/elements/editor/extensions/paste.mjs::markdownToHtml
// @reason helper-owned-by-markdown-parser
const unorderedListMatch = (line) => line.match(/^\s{0,3}[-*+]\s+(.+)$/);

// @testable false
// @covered-by src/script/elements/editor/extensions/paste.mjs::markdownToHtml
// @reason helper-owned-by-markdown-parser
const orderedListMatch = (line) => line.match(/^\s{0,3}\d+[.)]\s+(.+)$/);

// @testable false
// @covered-by src/script/elements/editor/extensions/paste.mjs::markdownToHtml
// @reason helper-owned-by-markdown-parser
const quoteMatch = (line) => line.match(/^\s{0,3}>\s?(.*)$/);

// @testable false
// @covered-by src/script/elements/editor/extensions/paste.mjs::markdownToHtml
// @reason helper-owned-by-markdown-parser
const isHorizontalRule = (line) =>
	/^\s{0,3}([-*_])(?:\s*\1){2,}\s*$/.test(line);

// @testable true
// @tests tests_e2e/004_projects/test_004d_document.py::test_pasting_markdown_table_preserves_table_after_reload
// @tests tests_e2e/004_projects/test_004d_document.py::test_pasting_common_markdown_preserves_formatting
// @matrix editor : paste-markdown paste-markdown-table reload
export const markdownToHtml = (content) => {
	const lines = String(content || "")
		.replaceAll("\r\n", "\n")
		.split("\n");
	const html = [];
	let convertedMarkdown = false;
	let paragraph = [];
	let codeBlock = null;

	// @testable false
	// @covered-by src/script/elements/editor/extensions/paste.mjs::markdownToHtml
	// @reason helper-owned-by-markdown-parser
	const flushParagraph = () => {
		if (paragraph.length === 0) return;
		html.push(`<p>${paragraph.map(renderInlineMarkdown).join("<br>")}</p>`);
		paragraph = [];
	};

	for (let index = 0; index < lines.length; index += 1) {
		const line = lines[index];
		const next = lines[index + 1];
		const trimmed = line.trim();

		if (codeBlock) {
			if (trimmed.startsWith("```")) {
				html.push(renderCodeBlock(codeBlock.lines));
				codeBlock = null;
				convertedMarkdown = true;
			} else {
				codeBlock.lines.push(line);
			}
			continue;
		}

		if (trimmed.startsWith("```")) {
			flushParagraph();
			codeBlock = { lines: [] };
			continue;
		}

		if (looksLikeTableRow(line) && next && isDividerRow(next)) {
			flushParagraph();
			const headers = splitMarkdownRow(line);
			const rows = [];
			index += 2;

			while (index < lines.length && looksLikeTableRow(lines[index])) {
				rows.push(splitMarkdownRow(lines[index]));
				index += 1;
			}
			index -= 1;
			convertedMarkdown = true;

			html.push(renderMarkdownTable(headers, rows));
			continue;
		}

		const heading = headingMatch(line);
		if (heading) {
			flushParagraph();
			const level = heading[1].length;
			html.push(`<h${level}>${renderInlineMarkdown(heading[2])}</h${level}>`);
			convertedMarkdown = true;
			continue;
		}

		const unordered = unorderedListMatch(line);
		if (unordered) {
			flushParagraph();
			const items = [];
			while (index < lines.length) {
				const item = unorderedListMatch(lines[index]);
				if (!item) break;
				items.push(item[1]);
				index += 1;
			}
			index -= 1;
			html.push(renderList("ul", items));
			convertedMarkdown = true;
			continue;
		}

		const ordered = orderedListMatch(line);
		if (ordered) {
			flushParagraph();
			const items = [];
			while (index < lines.length) {
				const item = orderedListMatch(lines[index]);
				if (!item) break;
				items.push(item[1]);
				index += 1;
			}
			index -= 1;
			html.push(renderList("ol", items));
			convertedMarkdown = true;
			continue;
		}

		const quote = quoteMatch(line);
		if (quote) {
			flushParagraph();
			const quoteLines = [];
			while (index < lines.length) {
				const item = quoteMatch(lines[index]);
				if (!item) break;
				quoteLines.push(item[1]);
				index += 1;
			}
			index -= 1;
			html.push(
				`<blockquote><p>${quoteLines.map(renderInlineMarkdown).join("<br>")}</p></blockquote>`,
			);
			convertedMarkdown = true;
			continue;
		}

		if (isHorizontalRule(line)) {
			flushParagraph();
			html.push("<hr>");
			convertedMarkdown = true;
			continue;
		}

		if (line.trim()) paragraph.push(line);
		else flushParagraph();
	}

	if (codeBlock) {
		html.push(renderCodeBlock(codeBlock.lines));
		convertedMarkdown = true;
	}

	flushParagraph();

	return convertedMarkdown ? html.join("") : "";
};

// @testable true
// @tests tests_e2e/004_projects/test_004d_document.py::test_pasting_markdown_table_preserves_table_after_reload
// @tests tests_e2e/004_projects/test_004d_document.py::test_pasting_plain_html_inserts_safe_formatted_content
// @tests tests_e2e/004_projects/test_004d_document.py::test_pasting_common_markdown_preserves_formatting
// @matrix editor : paste-html paste-markdown paste-markdown-table sanitization
export const EditorPaste = Extension.create({
	name: "editorPaste",

	addProseMirrorPlugins() {
		return [
			new Plugin({
				key: new PluginKey("editorPaste"),
				props: {
					handlePaste: (_view, event) => {
						const clipboard = event.clipboardData;
						if (!clipboard) return false;

						const richHtml = clipboard.getData("text/html");
						const text = clipboard.getData("text/plain");
						if (!text || richHtml) return false;

						const html = markdownToHtml(text) || sanitizePastedHtml(text);
						if (!html) return false;

						event.preventDefault();
						return this.editor.commands.insertContent(html);
					},
				},
			}),
		];
	},
});
