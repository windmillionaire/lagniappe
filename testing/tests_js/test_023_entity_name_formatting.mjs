import assert from "node:assert/strict";
import { test } from "node:test";
import { createBrowser } from "../utility/js/environment.mjs";

async function setup(t) {
	createBrowser(t, { url: "https://example.test/" });
	const [{ formatting }, { Results }, { STYLES }] = await Promise.all([
		import("../../src/script/elements/formatting.mjs"),
		import("../../src/script/elements/combobox/results.mjs"),
		import("../../src/script/generated/styles.mjs"),
	]);
	return { formatting, Results, STYLES };
}

/**
 * @matrix entity-name : accessibility parent-separator wrapping
 * @styles entity.name.wrapper entity.name.parent entity.name.separator
 */
test("test_formatting_name_uses_a_text_separator_and_shared_wrapping_structure", async (t) => {
	const { formatting, STYLES } = await setup(t);
	const formatted = formatting.name({
		id: "task-1",
		kind: "page",
		link: true,
		name: "A long child name",
		parent: { id: "category-1", kind: "category", name: "Medical" },
	});

	assert.equal(
		formatted.className,
		STYLES.entity.name.wrapper,
		`Unexpected wrapper style: ${formatted.className}`,
	);
	assert.equal(
		formatted.children.length,
		3,
		"Parent group, break opportunity, and entity name are not sibling flow items",
	);

	const [parent, breakOpportunity, name] = formatted.children;
	assert.ok(
		parent.className.includes(STYLES.entity.name.parent),
		"Parent and separator are not kept together",
	);
	assert.equal(parent.children.length, 2, "Parent name structure changed");
	assert.equal(
		parent.children[0].textContent,
		"Medical",
		"Parent name structure changed",
	);

	const separator = parent.children[1];
	const details = `Separator is not shared accessible text: ${separator.outerHTML}`;
	assert.equal(separator.tagName, "SPAN", details);
	assert.equal(separator.textContent, "/", details);
	assert.equal(separator.className, STYLES.entity.name.separator, details);
	assert.equal(separator.getAttribute("aria-hidden"), "true", details);
	assert.equal(
		breakOpportunity.tagName,
		"WBR",
		"Parent and entity name have no explicit wrapping opportunity",
	);
	assert.equal(
		name.tagName,
		"A",
		"Entity link is not a direct wrapping sibling of its parent group",
	);
	assert.equal(
		name.children.length,
		0,
		"Entity link is not a direct wrapping sibling of its parent group",
	);
	assert.equal(
		name.href,
		"https://example.test/pages/task-1",
		`Unexpected entity URL: ${name.href}`,
	);
});

/** @pair user-groups:query-route */
test("test_group_name_uses_canonical_user_index_url", async (t) => {
	const { formatting } = await setup(t);
	const formatted = formatting.name({
		id: "group-1",
		kind: "group",
		link: true,
		name: "Editors",
	});
	const link = formatted.children[0];
	assert.equal(
		link.href,
		"https://example.test/users/index?group=group-1",
		`Unexpected group URL: ${link.href}`,
	);
});

/** @pair model-task:reference-links */
test("test_model_task_link_opens_in_progress_filter", async (t) => {
	const { formatting } = await setup(t);
	const project = { id: "project-1", kind: "project", name: "Project" };
	const model = { id: "model-1", kind: "model", parent: project };
	assert.equal(
		String(formatting.url(model)),
		"https://example.test/projects/project-1/status/model-1?completed=false",
		`Wrong model task URL: ${formatting.url(model)}`,
	);
	assert.equal(
		String(formatting.url(project)),
		"https://example.test/projects/project-1",
		`Wrong project URL: ${formatting.url(project)}`,
	);
});

/**
 * @matrix combobox entity-name : parent-separator recent-results
 * @styles entity.name.wrapper entity.name.parent entity.name.separator
 */
test("test_recent_combobox_results_reuse_shared_parent_name_formatting", async (t) => {
	const { Results, STYLES } = await setup(t);
	localStorage.setItem(
		"recent-page",
		JSON.stringify([
			{
				id: "page-1",
				kind: "page",
				name: "A long child name",
				parent: { id: "category-1", kind: "category", name: "Medical" },
			},
		]),
	);

	const recentHtml = new Results("page").create();
	assert.ok(
		recentHtml.includes('class="min-w-0"'),
		`Recent result skipped the shared name wrapper: ${recentHtml}`,
	);
	assert.ok(
		recentHtml.includes("whitespace-nowrap"),
		`Recent result can separate its parent and slash: ${recentHtml}`,
	);
	assert.ok(
		recentHtml.includes('aria-hidden="true"'),
		`Recent result did not render the text separator: ${recentHtml}`,
	);
	assert.ok(
		recentHtml.includes(">/</span>"),
		`Recent result did not render the text separator: ${recentHtml}`,
	);
	assert.equal(
		recentHtml.includes("<i"),
		false,
		`Recent result did not use semantic Material markup: ${recentHtml}`,
	);
	assert.ok(
		recentHtml.includes("icon"),
		`Recent result did not use semantic Material markup: ${recentHtml}`,
	);
	assert.ok(
		recentHtml.includes(STYLES.dropdown.icon),
		`Recent result skipped shared dropdown icon spacing: ${recentHtml}`,
	);
});

/** @pair search:snippet-safety */
test("test_recent_search_snippets_allow_only_highlight_markup", async (t) => {
	const { Results } = await setup(t);
	const recentHtml = new Results("search").create([
		{
			details: {
				id: "page-1",
				kind: "page",
				name: "Safe result",
			},
			text:
				"Before <b>hit &lt;tag&gt;</b> " +
				'<img src=x onerror="globalThis.compromised=true"> ' +
				"&#x3c;script&#x3e;globalThis.compromised=true&#x3c;/script&#x3e;",
			url: "/pages/page-1",
		},
	]);
	const container = document.createElement("div");
	container.innerHTML = recentHtml;
	const snippet = container.querySelector("[data-result] p:last-child");

	assert.ok(
		snippet.innerHTML.includes("<b>hit &lt;tag&gt;</b>"),
		`Generated highlight markup was not preserved: ${recentHtml}`,
	);
	assert.equal(
		snippet.querySelector("img, script"),
		null,
		`Unexpected snippet markup reached the result DOM: ${recentHtml}`,
	);
	assert.equal(
		snippet.innerHTML.includes("<img"),
		false,
		`Unexpected snippet markup reached the result DOM: ${recentHtml}`,
	);
	assert.equal(
		snippet.innerHTML.includes("<script"),
		false,
		`Unexpected snippet markup reached the result DOM: ${recentHtml}`,
	);
	assert.ok(
		snippet.innerHTML.includes("&lt;img"),
		`Unexpected markup was not rendered as inert text: ${recentHtml}`,
	);
	assert.ok(
		snippet.innerHTML.includes(
			"&lt;script&gt;globalThis.compromised=true&lt;/script&gt;",
		),
		`Unexpected markup was not rendered as inert text: ${recentHtml}`,
	);
	assert.equal(
		Object.hasOwn(globalThis, "compromised"),
		false,
		"Snippet markup executed in the result renderer",
	);
});
