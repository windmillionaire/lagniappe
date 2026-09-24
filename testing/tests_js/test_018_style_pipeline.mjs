import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import { test } from "node:test";
import { rollup } from "rollup";
import {
	buildStyles,
	javascriptIconModuleSource,
	javascriptStyleModuleSource,
	normalizeIconRegistry,
	normalizeStyleRegistry,
	pythonStyleModuleSource,
	STYLE_PIPELINE,
} from "../../build/utility.mjs";
import { createBrowser } from "../utility/js/environment.mjs";
import { validateStyleCandidates } from "../utility/style_compile.mjs";

async function bundle(input) {
	const build = await rollup({
		input,
		plugins: [buildStyles()],
	});
	try {
		const { output } = await build.generate({ format: "esm" });
		return await import(
			`data:text/javascript,${encodeURIComponent(output[0].code)}`
		);
	} finally {
		await build.close();
	}
}

// @pair style-build:runtime-parity
test("test_virtual_and_python_style_payloads_share_one_runtime_value", async () => {
	const typedRegistry = {
		button: {
			submit: {
				classes: "flex items-center",
				intent: "primary submission control",
				surfaces: ["server", "frontend"],
			},
		},
		label: {
			default: {
				classes: "font-semibold",
				intent: "default field label",
				surfaces: ["server"],
			},
		},
	};
	const registry = normalizeStyleRegistry(typedRegistry);
	const icons = { page: { glyph: "draft", fill: 1 } };
	const virtualStyles = await import(
		`data:text/javascript,${encodeURIComponent(javascriptStyleModuleSource(registry))}`
	);
	const virtualIcons = await import(
		`data:text/javascript,${encodeURIComponent(javascriptIconModuleSource(icons))}`
	);
	const pythonSource = pythonStyleModuleSource("STYLES", registry);
	const pythonPayload = JSON.parse(pythonSource.split("STYLES = ", 2)[1]);

	assert.deepEqual(virtualStyles.STYLES, registry);
	assert.deepEqual(virtualIcons.ICONS, icons);
	assert.deepEqual(Object.keys(virtualStyles), ["STYLES"]);
	assert.deepEqual(Object.keys(virtualIcons), ["ICONS"]);
	assert.deepEqual(pythonPayload, registry);
	assert.deepEqual(virtualStyles.STYLES, pythonPayload);
});

// @pair style-build:schema-validation
test("test_style_registry_rejects_untyped_and_unknown_leaves", () => {
	assert.throws(
		() => normalizeStyleRegistry({ button: { submit: "flex" } }),
		/typed style record/,
	);
	assert.throws(
		() =>
			normalizeStyleRegistry({
				button: {
					submit: {
						classes: "flex",
						intent: "button",
						surfaces: ["server"],
						typo: true,
					},
				},
			}),
		/unknown style fields: typo/,
	);
	assert.deepEqual(
		normalizeStyleRegistry({
			button: {
				submit: {
					classes: "flex",
					intent: "button",
					surfaces: ["server"],
				},
				alternate: {
					alias: "button.submit",
					intent: "alternate button",
					surfaces: ["frontend"],
				},
			},
		}),
		{ button: { submit: "flex", alternate: "flex" } },
	);
	assert.throws(
		() =>
			normalizeStyleRegistry({
				button: {
					one: {
						alias: "button.two",
						intent: "one",
						surfaces: ["server"],
					},
					two: {
						alias: "button.one",
						intent: "two",
						surfaces: ["server"],
					},
				},
			}),
		/style alias cycle/,
	);
});

// @pair style-build:icon-schema-validation
test("test_icon_registry_rejects_invalid_ids_and_material_symbol_records", () => {
	assert.deepEqual(
		normalizeIconRegistry({
			dueDate: { glyph: "event", fill: 1 },
			filter: {
				active: { glyph: "filter_alt", fill: 1 },
				inactive: { glyph: "filter_alt", fill: 0 },
			},
		}),
		{
			dueDate: { glyph: "event", fill: 1 },
			filter: {
				active: { glyph: "filter_alt", fill: 1 },
				inactive: { glyph: "filter_alt", fill: 0 },
			},
		},
	);
	assert.throws(
		() =>
			normalizeIconRegistry({
				"due-date": { glyph: "event", fill: 1 },
			}),
		/invalid icon ID segment due-date/,
	);
	assert.throws(
		() =>
			normalizeIconRegistry({
				dueDate: { glyph: "Calendar Event", fill: 1 },
			}),
		/Material Symbol name/,
	);
	assert.throws(
		() => normalizeIconRegistry({ dueDate: { glyph: "event", fill: 2 } }),
		/fill must be 0 or 1/,
	);
	assert.throws(
		() =>
			normalizeIconRegistry({
				spinner: { glyph: "progress_activity", fill: 1, spin: "yes" },
			}),
		/spin must be a boolean/,
	);
	assert.throws(
		() =>
			normalizeIconRegistry({
				plus: { glyph: "add_2", fill: 1, weight: 700 },
			}),
		/weight must be one of 300, 400, 500, 600/,
	);
	assert.throws(
		() => normalizeIconRegistry({ dueDate: [] }),
		/icons.dueDate must be a non-empty mapping/,
	);
});

// @pair style-build:pipeline-contract
// @style button.submit
// @style dropdown.option.action
// @style dropdown.option.flow
// @style dropdown.search.result
// @style home.toggleLabel
test("test_style_pipeline_contract_names_authored_inputs_and_outputs", async () => {
	assert.equal(STYLE_PIPELINE.registry.styles, "src/style/styles.yaml");
	assert.equal(
		STYLE_PIPELINE.registry.schema,
		"src/style/registry.schema.json",
	);
	assert.equal(STYLE_PIPELINE.registry.icons, "src/style/icons.yaml");
	assert.equal(
		STYLE_PIPELINE.registry.icons_schema,
		"src/style/icons.schema.json",
	);
	assert.equal(
		STYLE_PIPELINE.registry.javascript_styles,
		"src/script/generated/styles.mjs",
	);
	assert.equal(
		STYLE_PIPELINE.registry.javascript_icons,
		"src/script/generated/icons.mjs",
	);
	assert.equal(
		STYLE_PIPELINE.registry.python_styles,
		"lagniappe/web/start/styles/styles.py",
	);
	assert.equal(STYLE_PIPELINE.css.entry, "src/style/main.css");
	assert.deepEqual(STYLE_PIPELINE.css.tailwind_sources, [
		"src/style/styles.yaml",
	]);
	assert.ok(
		STYLE_PIPELINE.css.authored_stylesheets.some(
			({ path, ownership }) =>
				path === "src/style/navigation.css" && ownership === "semantic",
		),
	);
	assert.deepEqual(STYLE_PIPELINE.builds.production.transforms, [
		"tailwindcss",
		"cssnano",
	]);
	const plugin = buildStyles();
	plugin.buildStart();
	const runtimeStyles = await import(
		`../../${STYLE_PIPELINE.registry.javascript_styles}`
	);
	const runtimeIcons = await import(
		`../../${STYLE_PIPELINE.registry.javascript_icons}`
	);
	assert.equal(typeof runtimeStyles.STYLES.button.submit, "string");
	assert.match(runtimeStyles.STYLES.button.submit, /\bw-full\b/);
	assert.match(runtimeStyles.STYLES.button.submit, /\bgrow\b/);
	assert.match(runtimeStyles.STYLES.button.submit, /\baction-button\b/);
	assert.deepEqual(runtimeIcons.ICONS.page, { glyph: "draft", fill: 1 });
	assert.equal(runtimeStyles.ICONS, undefined);
	assert.equal(runtimeIcons.STYLES, undefined);
	assert.match(
		runtimeStyles.STYLES.dropdown.option.action,
		/\bdropdown-option-action\b/,
	);
	assert.match(
		runtimeStyles.STYLES.home.toggleLabel,
		/\bflex\b[\s\S]*\bitems-center\b[\s\S]*\bgap-2\b/,
	);
	assert.doesNotMatch(runtimeStyles.STYLES.home.toggleLabel, /\bflow-root\b/);
	assert.match(
		runtimeStyles.STYLES.dropdown.option.flow,
		/\bdropdown-option-flow\b/,
	);
	assert.equal(
		runtimeStyles.STYLES.dropdown.search.result,
		runtimeStyles.STYLES.dropdown.option.flow,
	);
});

// @matrix ui-action : fixed-layout loading-state
// @style button.submit
test("test_active_action_buttons_preserve_full_width_icon_slots", async (t) => {
	createBrowser(t);
	const module = await bundle("./src/script/elements/buttons.mjs");
	const button = document.createElement("button");
	button.textContent = "Refresh Cache";
	const action = module.buttons.active({
		existingButton: button,
		icon: "database",
		text: "Refresh Cache",
		processingText: "Refreshing Cache",
		completedText: "Cache Refreshed",
		completedIcon: "check",
	});

	const iconSlot = button.querySelector("[data-role='icon']");
	const textSlot = button.querySelector("[data-role='text']");
	assert.ok(iconSlot);
	assert.ok(textSlot);
	assert.equal(iconSlot.children[0]?.dataset.icon, "database");
	assert.equal(textSlot.textContent, "Refresh Cache");

	action.activate();
	assert.equal(button.disabled, true);
	assert.equal(button.querySelector("[data-role='icon']"), iconSlot);
	assert.equal(button.querySelector("[data-role='text']"), textSlot);
	assert.equal(iconSlot.children[0]?.dataset.icon, "spinner");
	assert.equal(textSlot.textContent, "Refreshing Cache");

	action.deactivate();
	assert.equal(button.disabled, false);
	assert.equal(button.querySelector("[data-role='icon']"), iconSlot);
	assert.equal(button.querySelector("[data-role='text']"), textSlot);
	assert.equal(iconSlot.children[0]?.dataset.icon, "check");
	assert.equal(textSlot.textContent, "Cache Refreshed");
});

// @matrix frontend-icons : accessibility animation element-creation fill lookup nested-ids registry semantic-markup weight
test("test_frontend_icon_helpers_render_structured_material_symbols", async (t) => {
	createBrowser(t);
	const module = await bundle("./src/script/shared/icons.mjs");

	const project = module.createIcon("project", "text-project-default");
	assert.equal(project.textContent, "flowsheet");
	assert.equal(project.dataset.icon, "project");
	assert.equal(project.dataset.fill, "0");
	assert.equal(project.getAttribute("aria-hidden"), "true");
	assert.match(project.className, /icon/);
	assert.match(project.className, /text-project-default/);
	assert.equal(project.children.length, 1);
	assert.equal(project.children[0].className, "icon-glyph");
	assert.equal(project.children[0].textContent, "flowsheet");

	const plus = module.createIcon("plus");
	assert.equal(plus.textContent, "add_2");
	assert.equal(plus.dataset.weight, "600");

	const edit = module.createIcon("edit");
	assert.equal(edit.textContent, "amend");
	assert.equal(edit.dataset.fill, "0");

	const clear = module.createIcon("clear");
	assert.equal(clear.textContent, "do_not_disturb_on");

	const historyFill = module.createIcon("historyFill");
	assert.equal(historyFill.textContent, "settings_backup_restore");

	const attributeRemove = module.createIcon("attribute.remove");
	assert.equal(attributeRemove.textContent, "do_not_disturb_on");

	const close = module.createIcon("x");
	assert.equal(close.dataset.weight, "600");

	const spinner = module.createIcon("spinner");
	assert.match(spinner.className, /icon-spin/);

	const trash = module.createIcon("trash.active");
	assert.equal(trash.textContent, "delete_forever");
	assert.equal(trash.dataset.fill, "1");

	module.setIcon(plus, "star.inactive");
	assert.equal(plus.textContent, "star");
	assert.equal(plus.dataset.fill, "0");
	assert.equal(plus.dataset.weight, "300");
	assert.equal(plus.children[0].className, "icon-glyph");
});

// @style dropdown.icon
// @style entity.tabIcon
// @style index.header.iconContext
test("test_material_symbol_size_exceptions_use_semantic_css", () => {
	const css = readFileSync("./src/style/icons.css", "utf8");
	const buttonsCss = readFileSync("./src/style/buttons.css", "utf8");
	const contentCss = readFileSync("./src/style/content.css", "utf8");
	const navigationCss = readFileSync("./src/style/navigation.css", "utf8");
	for (const pattern of [
		/\.icon\s*\{[\s\S]*?--icon-xs-box-size: 1\.125rem;[\s\S]*?--icon-xs-glyph-size: 1rem;[\s\S]*?--icon-sm-box-size: 1\.25rem;[\s\S]*?--icon-sm-glyph-size: 1\.125rem;[\s\S]*?--icon-base-box-size: 1\.5rem;[\s\S]*?--icon-base-glyph-size: 1\.25rem;[\s\S]*?--icon-lg-box-size: 1\.625rem;[\s\S]*?--icon-lg-glyph-size: 1\.5rem;[\s\S]*?--icon-xl-box-size: 1\.875rem;[\s\S]*?--icon-xl-glyph-size: 1\.625rem;[\s\S]*?--icon-2xl-box-size: 2\.25rem;[\s\S]*?--icon-2xl-glyph-size: 2rem;[\s\S]*?--icon-box-size: var\(--icon-base-box-size\);[\s\S]*?--icon-default-size: var\(--icon-base-glyph-size\);[\s\S]*?font-size: 1rem;[\s\S]*?inline-size: var\(--icon-box-size\);[\s\S]*?block-size: var\(--icon-box-size\);/,
		/\.icon-glyph\s*\{[\s\S]*?font-size: var\(--icon-size, var\(--icon-default-size\)\);[\s\S]*?inset-block-start: var\(--icon-offset-y, 0\);[\s\S]*?inset-inline-start: var\(--icon-offset-x, 0\);[\s\S]*?position: relative;/,
		/\.icon\[data-icon="document"\],\s*\.icon\[data-icon="info"\]\s*\{\s*--icon-size: var\(--icon-lg-glyph-size\);/,
		/button\.tab-icon \.icon\s*\{[\s\S]*?--icon-box-size: var\(--icon-xl-box-size\);[\s\S]*?--icon-size: var\(--icon-xl-glyph-size\);/,
		/\.icon\[data-icon="close"\],\s*\.icon\[data-icon="x"\]\s*\{[\s\S]*?--icon-offset-x: 0\.5px;[\s\S]*?--icon-offset-y: 0\.5px;/,
		/\.task-history-icon\s*\{\s*--icon-offset-y: 1px;/,
		/\.editor-toolbar-icon-context \.icon\s*\{[\s\S]*?--icon-box-size: var\(--icon-base-box-size\);[\s\S]*?--icon-default-size: var\(--icon-lg-glyph-size\);[\s\S]*?--icon-size: var\(--icon-lg-glyph-size\);/,
		/\.editor-toolbar-icon-context \.editor-toolbar-menu-icon\s*\{\s*--icon-offset-y: 1px;/,
		/\.editor-toolbar-portal-icon-context \.icon\s*\{[\s\S]*?--icon-box-size: var\(--icon-base-box-size\);[\s\S]*?--icon-default-size: var\(--icon-base-glyph-size\);[\s\S]*?--icon-size: var\(--icon-base-glyph-size\);/,
		/\.editor-toolbar-icon-context \.editor-toolbar-caret\s*\{[\s\S]*?--icon-box-size: var\(--icon-sm-box-size\);[\s\S]*?--icon-size: var\(--icon-sm-glyph-size\);[\s\S]*?--icon-offset-y: 1px;/,
		/\.icon\[data-icon="menu"\]\s*\{[\s\S]*?--icon-box-size: var\(--icon-sm-box-size\);[\s\S]*?--icon-size: var\(--icon-base-glyph-size\);/,
		/\[lp-menu="title"\] \.icon\[data-icon="menu"\]\s*\{[\s\S]*?--icon-box-size: var\(--icon-base-box-size\);[\s\S]*?--icon-offset-y: 0\.125rem;/,
		/\.icon\[data-icon="spinner"\]\s*\{\s*--icon-size: var\(--icon-sm-glyph-size\);/,
		/\.icon\[data-icon="spinner"\] \.icon-glyph\s*\{\s*display: none;/,
		/\.icon\[data-icon="spinner"\]::before\s*\{[\s\S]*?box-shadow:[\s\S]*?color-mix\([\s\S]*?content: "";/,
		/\.icon-spin\s*\{\s*animation: icon-spin 1\.25s linear infinite;/,
		/\.icon\[data-icon="star\.active"\],\s*\.icon\[data-icon="star\.inactive"\]\s*\{\s*--icon-size: var\(--icon-lg-glyph-size\);/,
		/\.icon\[data-icon="star\.home"\]\s*\{[\s\S]*?--icon-size: var\(--icon-lg-glyph-size\);[\s\S]*?--icon-offset-y: -1px;/,
		/\.icon\[data-icon="addRow"\],\s*\.icon\[data-icon="reset"\]\s*\{\s*--icon-offset-y: -1px;/,
		/button\[data-role="history-fill"\] \.icon\[data-icon="historyFill"\]\s*\{\s*--icon-offset-y: -1px;/,
		/\.layout-nav-title \.icon\s*\{[\s\S]*?--icon-box-size: var\(--icon-lg-box-size\);[\s\S]*?--icon-default-size: var\(--icon-lg-glyph-size\);/,
		/\.index-header-icon-context \.icon\s*\{[\s\S]*?--icon-box-size: var\(--icon-lg-box-size\);[\s\S]*?--icon-default-size: var\(--icon-lg-glyph-size\);/,
		/\.checkbox-icon\s*\{[\s\S]*?--icon-box-size: 1rem;[\s\S]*?--icon-size: 1rem;[\s\S]*?font-size: 1rem;/,
		/\.nav-search-icon\s*\{[\s\S]*?--icon-offset-y: 1px;[\s\S]*?font-size: 1rem;/,
		/\.task-control-group \.icon\s*\{[\s\S]*?--icon-box-size: var\(--icon-base-box-size\);[\s\S]*?--icon-default-size: var\(--icon-base-glyph-size\);/,
		/\.select-icon\s*\{[\s\S]*?--icon-box-size: 1\.25rem;[\s\S]*?font-size: 1rem;/,
	]) {
		assert.match(css, pattern);
	}
	for (const name of ["plus", "page", "help"]) {
		assert.match(
			css,
			new RegExp(
				`\\.icon\\[data-icon="${name}"\\]\\s*\\{\\s*--icon-size: var\\(--icon-base-glyph-size\\);`,
			),
		);
	}
	for (const pattern of [
		/--icon-(?:box-size|default-size|size):[^;]*\d(?:\.\d+)?em;/,
		/\.icon-glyph\s*\{[^}]*transform:/,
		/\.task-control-icon/,
		/\.dropdown-icon/,
		/\.dropdown-option-action \.icon\[data-icon=/,
		/\.home-toggle-label > \.icon/,
	]) {
		assert.doesNotMatch(css, pattern);
	}
	for (const pattern of [
		/\.dropdown-option\s*\{[\s\S]*?border-radius: var\(--radius-sm\);[\s\S]*?line-height: 1\.5;[\s\S]*?padding: 0\.375rem 0\.5rem;[\s\S]*?text-align: left;[\s\S]*?width: 100%;/,
		/\.dropdown-option-flow\s*\{\s*display: block;/,
		/\.dropdown-option-action\s*\{[\s\S]*?align-items: center;[\s\S]*?display: flex;[\s\S]*?gap: 0\.25rem;/,
		/\.dropdown-option-flow \.dropdown-option-icon\s*\{\s*margin-inline-end: 0\.25rem;/,
	]) {
		assert.match(contentCss, pattern);
	}
	assert.doesNotMatch(
		contentCss,
		/\.dropdown-option-action > span:not\(\.icon\)/,
	);
	for (const name of ["xs", "sm", "base", "lg", "xl", "2xl"]) {
		assert.match(
			css,
			new RegExp(
				`\\.icon\\.icon-${name}\\s*\\{[\\s\\S]*?--icon-box-size: var\\(--icon-${name}-box-size\\);[\\s\\S]*?--icon-size: var\\(--icon-${name}-glyph-size\\);`,
			),
		);
	}
	for (const path of [
		"categories/index.html",
		"forms/index.html",
		"tasks/index.html",
		"users/index.html",
	]) {
		const template = readFileSync(`./lagniappe/web/templates/${path}`, "utf8");
		assert.match(
			template,
			/<nav class="\{\{ styles\.layout\.view\.title \}\} \{\{ styles\.index\.header\.iconContext \}\}"/,
			`${path} must use the shared large index-header icon context`,
		);
	}
	for (const pattern of [
		/\.action-icon-button \.icon\s*\{\s*grid-area: 1 \/ 1;\s*\}/,
		/\.action-icon-button\s*\{[\s\S]*?translate: var\(--action-offset-x, 0\) var\(--action-offset-y, 0\);/,
		/\.action-icon-button\s*\{[\s\S]*?vertical-align: middle;/,
		/\.action-icon-button\[data-role="menu-trigger"\]\s*\{\s*--action-offset-y: -0\.125rem;/,
	]) {
		assert.match(buttonsCss, pattern);
	}
	assert.doesNotMatch(buttonsCss, /--action-icon(?:-button)?-size/);
	assert.doesNotMatch(navigationCss, /--action-icon(?:-button)?-size/);
	for (const filename of readdirSync("./src/style")) {
		if (!filename.endsWith(".css") || filename === "icons.css") continue;
		assert.doesNotMatch(
			readFileSync(`./src/style/${filename}`, "utf8"),
			/--icon-(?:box-size|default-size|size|offset-[xy])/,
			`${filename} must not override icon-owned geometry`,
		);
	}
	assert.doesNotMatch(navigationCss, /button\.tab-icon > \.icon/);
});

test("test_style_candidate_validator_uses_the_authored_tailwind_design_system", async () => {
	const result = await validateStyleCandidates({
		cssEntry: "src/style/main.css",
		candidates: [
			"flex",
			"text-kind-default",
			"group/example",
			"not-a-real-utility",
		],
		ignored: ["group/example"],
	});

	assert.equal(result.checked, 4);
	assert.deepEqual(result.ignored, ["group/example"]);
	assert.deepEqual(result.invalid, ["not-a-real-utility"]);
});
