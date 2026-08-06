"""Node-backed checks for pure frontend build configuration helpers."""


# @features build
# @dimensions sentry source-maps optional-credentials
def test_sentry_build_requires_nonblank_upload_token(run_node):
    run_node(
        """
import("./build/sentry.mjs").then(({ resolveSentryBuild }) => {
  for (const settings of [{}, { SENTRY_AUTH_TOKEN: null }, { SENTRY_AUTH_TOKEN: "  " }]) {
    const result = resolveSentryBuild(settings);
    if (result.enabled || result.sourcemap !== false || result.authToken !== null) {
      throw new Error(`Blank Sentry token enabled uploads: ${JSON.stringify(result)}`);
    }
  }

  const enabled = resolveSentryBuild({ SENTRY_AUTH_TOKEN: "  maintainer-token  " });
  if (!enabled.enabled || enabled.sourcemap !== "hidden") {
    throw new Error(`Valid Sentry token did not enable source maps: ${JSON.stringify(enabled)}`);
  }
  if (enabled.authToken !== "maintainer-token") {
    throw new Error("Sentry token was not normalized");
  }
});
"""
    )


# @pair frontend-build:view-registry
def test_frontend_entries_and_startup_budget_contract(run_node):
    run_node(
        r'''
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import {
  CORE_FORBIDDEN_MODULES,
  STARTUP_BUDGETS,
  validateStartupBudgets,
} from "./build/startupBudget.mjs";
import {
  VIEW_ENTRIES,
  VIEW_REGISTRY,
  viewEntryUrl,
} from "./src/script/viewRegistry.mjs";

assert.equal(viewEntryUrl("manual"), "./chunks/views/manual.js?v=development");
assert.equal(viewEntryUrl("task"), "./chunks/views/index.js?v=development");
assert.equal(viewEntryUrl("missing"), null);
assert.deepEqual(Object.keys(VIEW_ENTRIES).sort(), [
  "admin", "analytics", "builder", "file", "home", "index", "manual",
  "page", "project", "report", "results", "user",
]);
assert.equal(VIEW_REGISTRY.category.entry, VIEW_REGISTRY.form.entry);
assert.equal(STARTUP_BUDGETS.core, 120 * 1024);

for (const configPath of [
  "build/rollup.config.mjs",
  "build/rollup.dev.config.mjs",
]) {
  const source = readFileSync(configPath, "utf8");
  assert.match(source, /VIEW_ENTRIES/);
  assert.match(source, /chunks\/views\/\[name\]\.js/);
  assert.match(source, /manualChunks: interactionFoundationChunk/);
  assert.match(source, /onlyExplicitManualChunks: true/);
  assert.equal((source.match(/manualChunks:/g) || []).length, 1);
}

const chunk = ({ name, code = "x", imports = [], modules = {} }) => ({
  type: "chunk",
  fileName: name === "main" ? "script.js" : `chunks/views/${name}.js`,
  name,
  code,
  imports,
  modules,
  isEntry: true,
});
const bundle = {};
for (const name of [
  "main", "manual", "results", "analytics", "project", "page", "home",
  "user", "index", "file", "report", "admin", "builder",
]) {
  const item = chunk({
    name,
    code: "x".repeat(name === "builder" ? 180 * 1024 : 1024),
    modules: { [`/src/script/views/${name}.mjs`]: {} },
  });
  bundle[item.fileName] = item;
}
validateStartupBudgets(bundle);

const oversized = structuredClone(bundle);
oversized["script.js"].code = "x".repeat(STARTUP_BUDGETS.main + 1);
assert.throws(
  () => validateStartupBudgets(oversized),
  /main boot closure/,
);

const forbidden = structuredClone(bundle);
forbidden["chunks/views/page.js"].modules = {
  [`/src/script${CORE_FORBIDDEN_MODULES[0]}`]: {},
};
assert.throws(
  () => validateStartupBudgets(forbidden),
  /statically includes/,
);
''',
        module=True,
    )


# @pair frontend-build:modulepreload
# @pair frontend-build:view-registry
def test_templates_preload_registered_view_and_interaction_foundations(run_node):
    run_node(
        r'''
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { VIEW_ENTRIES } from "./src/script/viewRegistry.mjs";

const base = readFileSync("lagniappe/web/templates/layouts/base.html", "utf8");
assert.match(base, /rel="modulepreload"/);
assert.match(
  base,
  /\/chunks\/views\/\{\{ view_entry \}\}\.js\?v=\{\{ CONFIG\.BUILD_ID \}\}/,
);
assert.match(base, /\/chunks\/connectivity\.js\?v=\{\{ CONFIG\.BUILD_ID \}\}/);
assert.match(base, /\/chunks\/foundation\.js\?v=\{\{ CONFIG\.BUILD_ID \}\}/);
assert.match(
  base,
  /view_entry in \['project',[\s\S]*\/chunks\/core-foundation\.js\?v=\{\{ CONFIG\.BUILD_ID \}\}/,
);
assert.match(
  base,
  /view_entry in \['project', 'page', 'file', 'admin'\][\s\S]*\/chunks\/entity-foundation\.js\?v=\{\{ CONFIG\.BUILD_ID \}\}/,
);
assert.match(
  base,
  /view_entry == 'index'[\s\S]*\/chunks\/index-foundation\.js\?v=\{\{ CONFIG\.BUILD_ID \}\}/,
);
assert.doesNotMatch(
  base,
  /\/chunks\/(?:core|endpoints|errors|request|shell|utilities)\.js/,
);

const templates = [
  "analytics/index.html", "categories/index.html", "files/file.html",
  "forms/builder.html", "forms/index.html", "home/admin.html",
  "home/home.html", "manual/index.html", "pages/page.html",
  "projects/project.html", "search/search.html", "tasks/index.html",
  "tools/report.html", "users/index.html",
];
for (const template of templates) {
  const source = readFileSync(`lagniappe/web/templates/${template}`, "utf8");
  const match = source.match(/^\{% set view_entry = "([^"]+)" %\}/);
  assert.ok(match, `${template} does not declare its view entry`);
  assert.ok(VIEW_ENTRIES[match[1]], `${template} uses unknown entry ${match[1]}`);
  assert.equal(
    (source.match(/view_entry\s*=/g) || []).length,
    1,
    `${template} declares multiple view preloads`,
  );
}
''',
        module=True,
    )


# @pair frontend-build:modulepreload
# @pair frontend-build:interaction-foundation
# @pair frontend-build:chunking
def test_interaction_preloads_have_stable_manual_chunks(run_node):
    run_node(
        r'''
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { interactionFoundationChunk } from "./build/utility.mjs";

const root = "/checkout/src/script/";
for (const module of [
  "shared/endpoints.mjs", "shared/errors.mjs", "shared/notificationState.mjs",
  "shared/request.mjs", "shared/utilities.mjs", "views/base/shell.mjs",
]) {
  assert.equal(interactionFoundationChunk(`${root}${module}`), "foundation");
}
assert.equal(
  interactionFoundationChunk(`${root}shared/connectivity.mjs`),
  "connectivity",
);
assert.equal(
  interactionFoundationChunk("/checkout/config/browser_protocol.json"),
  "connectivity",
);
for (const module of [
  "elements/nav.mjs", "views/base/component.mjs", "views/base/core.mjs",
  "views/base/reconciliation.mjs", "views/base/services.mjs",
  "views/base/task.mjs", "widgets/loader.mjs",
]) {
  assert.equal(
    interactionFoundationChunk(`${root}${module}`),
    "core-foundation",
  );
}
assert.equal(
  interactionFoundationChunk(`${root}views/base/entity.mjs`),
  "entity-foundation",
);
for (const module of [
  "views/base/index.mjs", "widgets/tableVisibilityState.mjs",
]) {
  assert.equal(
    interactionFoundationChunk(`${root}${module}`),
    "index-foundation",
  );
}
assert.equal(interactionFoundationChunk(`${root}views/home.mjs`), undefined);
assert.equal(interactionFoundationChunk("\0virtual:styles"), undefined);

for (const config of ["build/rollup.config.mjs", "build/rollup.dev.config.mjs"]) {
  const source = readFileSync(config, "utf8");
  assert.match(source, /manualChunks: interactionFoundationChunk/);
  assert.match(source, /onlyExplicitManualChunks: true/);
}
''',
        module=True,
    )
