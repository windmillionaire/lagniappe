import fs from "node:fs";
import * as parser from "@babel/parser";

const files = process.argv.slice(2);
const symbols = [];

function cleanComment(comment) {
	return comment.value
		.split("\n")
		.map((line) => line.replace(/^\s*\*\s?/, "").trimEnd())
		.join("\n")
		.trim();
}

function leadingText(...nodes) {
	const comments = [];
	const seen = new Set();

	for (const node of nodes) {
		for (const comment of node?.leadingComments || []) {
			const key = `${comment.start}:${comment.end}`;
			if (!seen.has(key)) {
				seen.add(key);
				comments.push(comment);
			}
		}
	}

	return comments.map(cleanComment).filter(Boolean).join("\n");
}

function keyName(key) {
	if (!key) return "<anonymous>";
	if (key.type === "Identifier") return key.name;
	if (key.type === "PrivateName") return `#${key.id.name}`;
	if (key.type === "StringLiteral" || key.type === "NumericLiteral") {
		return String(key.value);
	}
	return "<computed>";
}

function record(file, language, kind, qualname, node, metadataText, subkind = null) {
	symbols.push({
		path: file,
		language,
		kind,
		subkind,
		qualname,
		lineno: node.loc?.start?.line || 1,
		end_lineno: node.loc?.end?.line || node.loc?.start?.line || 1,
		metadata_text: metadataText || "",
	});
}

function childNodes(node) {
	const skip = new Set([
		"comments",
		"leadingComments",
		"trailingComments",
		"innerComments",
		"loc",
		"start",
		"end",
		"extra",
	]);
	const children = [];

	for (const [key, value] of Object.entries(node)) {
		if (skip.has(key)) continue;
		if (Array.isArray(value)) {
			for (const child of value) {
				if (child?.type) children.push(child);
			}
		} else if (value?.type) {
			children.push(value);
		}
	}

	return children;
}

function walk(node, state) {
	if (!node?.type) return;

	if (node.type === "ExportNamedDeclaration" || node.type === "ExportDefaultDeclaration") {
		if (node.declaration) {
			walk(node.declaration, { ...state, exportNode: node });
		}
		return;
	}

	if (node.type === "ClassDeclaration" || node.type === "ClassExpression") {
		const name = node.id?.name || "default";
		const qualname = [...state.stack, name].join(".");
		record(
			state.file,
			"javascript",
			"class",
			qualname,
			node,
			leadingText(node, state.exportNode),
			node.type,
		);

		for (const member of node.body?.body || []) {
			walk(member, { ...state, stack: [...state.stack, name], exportNode: null });
		}
		return;
	}

	if (node.type === "ClassMethod" || node.type === "ClassPrivateMethod") {
		const name = keyName(node.key);
		const qualname = [...state.stack, name].join(".");
		record(
			state.file,
			"javascript",
			"method",
			qualname,
			node,
			leadingText(node),
			node.kind,
		);
		walk(node.body, { ...state, stack: [...state.stack, name], exportNode: null });
		return;
	}

	if (
		(node.type === "ClassProperty" || node.type === "ClassPrivateProperty") &&
		["ArrowFunctionExpression", "FunctionExpression"].includes(node.value?.type)
	) {
		const name = keyName(node.key);
		const qualname = [...state.stack, name].join(".");
		record(
			state.file,
			"javascript",
			"method",
			qualname,
			node,
			leadingText(node),
			"property-function",
		);
		walk(node.value.body, { ...state, stack: [...state.stack, name], exportNode: null });
		return;
	}

	if (node.type === "FunctionDeclaration") {
		const name = node.id?.name || "<anonymous>";
		const qualname = [...state.stack, name].join(".");
		record(
			state.file,
			"javascript",
			"function",
			qualname,
			node,
			leadingText(node, state.exportNode),
			"function",
		);
		walk(node.body, { ...state, stack: [...state.stack, name], exportNode: null });
		return;
	}

	if (
		node.type === "VariableDeclarator" &&
		node.id?.type === "Identifier" &&
		["ArrowFunctionExpression", "FunctionExpression"].includes(node.init?.type)
	) {
		const name = node.id.name;
		const qualname = [...state.stack, name].join(".");
		record(
			state.file,
			"javascript",
			"function",
			qualname,
			node,
			leadingText(node, state.parent, state.exportNode),
			node.init.type,
		);
		walk(node.init.body, { ...state, stack: [...state.stack, name], exportNode: null });
		return;
	}

	if (node.type === "VariableDeclarator" && node.id?.type === "Identifier") {
		const metadataText = leadingText(node, state.parent, state.exportNode);
		if (metadataText.includes("@testable")) {
			const name = node.id.name;
			record(
				state.file,
				"javascript",
				"declaration",
				[...state.stack, name].join("."),
				node,
				metadataText,
				node.init?.type || "variable",
			);
		}
	}

	for (const child of childNodes(node)) {
		walk(child, { ...state, parent: node, exportNode: state.exportNode });
	}
}

for (const file of files) {
	try {
		const code = fs.readFileSync(file, "utf8");
		const ast = parser.parse(code, {
			sourceType: "unambiguous",
			attachComment: true,
			plugins: [
				"classProperties",
				"classPrivateProperties",
				"classPrivateMethods",
				"dynamicImport",
				"importMeta",
				"topLevelAwait",
			],
		});
		walk(ast.program, { file, stack: [], parent: null, exportNode: null });
	} catch (error) {
		console.error(`${file}: ${error.message}`);
		process.exitCode = 1;
	}
}

if (!process.exitCode) {
	console.log(JSON.stringify(symbols));
}
