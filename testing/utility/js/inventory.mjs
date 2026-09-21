import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { parse } from "@babel/parser";

// Parse declarations only. Never import a test or application during discovery.
export function inventory(file) {
	const source = readFileSync(file, "utf8");
	const ast = parse(source, { sourceType: "module" });
	const cases = [];
	const imports = [];
	const testBindings = new Set();
	for (const node of ast.program.body) {
		if (node.type !== "ImportDeclaration") continue;
		imports.push(node.source.value);
		if (node.source.value !== "node:test") continue;
		for (const spec of node.specifiers) {
			if (
				spec.type === "ImportNamespaceSpecifier" ||
				["describe", "it", "suite"].includes(spec.imported?.name)
			) {
				throw new Error(
					`${file}:${node.loc.start.line}: Import test directly from node:test; suites and aliases such as it are not collected`,
				);
			}
			if (
				spec.type === "ImportDefaultSpecifier" ||
				spec.imported?.name === "test"
			) {
				testBindings.add(spec.local.name);
			}
		}
	}
	function walk(node, visitor) {
		if (!node?.type) return;
		visitor(node);
		for (const [key, value] of Object.entries(node)) {
			if (key.endsWith("Comments") || key === "comments") continue;
			if (Array.isArray(value))
				value.forEach((child) => {
					walk(child, visitor);
				});
			else if (value?.type) walk(value, visitor);
		}
	}
	const topLevel = new Map(
		ast.program.body
			.filter((node) => node.type === "ExpressionStatement")
			.map((node) => [node.expression, node]),
	);
	walk(ast.program, (node) => {
		if (
			node.type === "ImportExpression" &&
			node.source.type === "StringLiteral"
		)
			imports.push(node.source.value);
		if (node.type !== "CallExpression") return;
		const callee = node.callee;
		const binding =
			callee.type === "Identifier" ? callee.name : callee.object?.name;
		if (!testBindings.has(binding)) return;
		const statement = topLevel.get(node);
		const method =
			callee.type === "Identifier" ? "test" : callee.property?.name;
		const name = node.arguments[0]?.value;
		const fail = (reason) => {
			throw new Error(`${file}:${node.loc.start.line}: ${reason}`);
		};
		if (!statement || !["test", "skip", "todo"].includes(method))
			fail(
				"Use flat top-level test(), test.skip(), or test.todo(); no .only or dynamic registration",
			);
		if (
			node.arguments[0]?.type !== "StringLiteral" ||
			!/^test_[A-Za-z0-9_]+$/.test(name)
		)
			fail(
				"Use a literal test_ name containing letters, digits, or underscores",
			);
		if (cases.some((row) => row.name === name))
			fail(`Duplicate test name ${name}`);
		const options = node.arguments[1];
		if (options?.type === "ObjectExpression") {
			for (const option of options.properties) {
				if (
					option.type !== "ObjectProperty" ||
					!["timeout", "signal"].includes(option.key.name)
				)
					fail(
						"Only timeout/signal options are supported; use test.skip/test.todo for unfinished cases",
					);
			}
		}
		const calls = [];
		const selectors = [];
		const callback = node.arguments.at(-1);
		const contextName = callback.params?.[0]?.name;
		walk(node, (child) => {
			if (child.type === "StringLiteral" && /(?:data-|lp-)/.test(child.value))
				selectors.push(child.value);
			if (child.type === "TemplateLiteral") {
				const value = child.quasis.map((part) => part.value.cooked).join("*");
				if (/(?:data-|lp-)/.test(value)) selectors.push(value);
			}
			if (child.type !== "CallExpression") return;
			const fn = child.callee;
			if (
				contextName &&
				fn.type === "MemberExpression" &&
				fn.object.name === contextName &&
				fn.property.name === "test"
			)
				fail(
					"Nested subtests are not collected; use a scenario loop inside the case",
				);
			if (fn.type === "Identifier") calls.push(fn.name);
			else if (fn.property?.name) calls.push(fn.property.name);
		});
		const comments = statement.leadingComments || [];
		cases.push({
			name,
			lineno: node.loc.start.line,
			end_lineno: node.loc.end.line,
			start_lineno: comments[0]?.loc.start.line || node.loc.start.line,
			metadata_text: comments.map((comment) => comment.value).join("\n"),
			status: method,
			calls,
			selectors,
			source: source.slice(node.start, node.end),
		});
	});
	return { cases, imports: [...new Set(imports)] };
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
	try {
		const files = JSON.parse(readFileSync(0, "utf8"));
		process.stdout.write(
			JSON.stringify(
				Object.fromEntries(files.map((file) => [file, inventory(file)])),
			),
		);
	} catch (error) {
		console.error(error.stack);
		process.exitCode = 1;
	}
}
