"""Node-backed checks for pure frontend build configuration helpers."""


# @matrix build : optional-credentials release-version sentry source-maps
def test_sentry_build_uses_package_release_and_requires_upload_token(run_node):
    run_node(
        r"""
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

import("./build/sentry.mjs").then(({ resolveSentryBuild }) => {
  for (const settings of [{}, { SENTRY_AUTH_TOKEN: null }, { SENTRY_AUTH_TOKEN: "  " }]) {
    const result = resolveSentryBuild(settings, { version: "1.1.0" });
    if (
      result.enabled || result.sourcemap !== false || result.authToken !== null ||
      result.release !== "1.1.0"
    ) {
      throw new Error(`Blank Sentry token enabled uploads: ${JSON.stringify(result)}`);
    }
  }

  const enabled = resolveSentryBuild(
    { SENTRY_AUTH_TOKEN: "  maintainer-token  ", VERSION: "1.0.1" },
    { version: "  1.1.0  " },
  );
  if (!enabled.enabled || enabled.sourcemap !== "hidden") {
    throw new Error(`Valid Sentry token did not enable source maps: ${JSON.stringify(enabled)}`);
  }
  if (enabled.authToken !== "maintainer-token") {
    throw new Error("Sentry token was not normalized");
  }
  if (enabled.release !== "1.1.0") {
    throw new Error(`Sentry release did not use package.json: ${JSON.stringify(enabled)}`);
  }
  try {
    resolveSentryBuild({ SENTRY_AUTH_TOKEN: "token" }, { version: "  " });
    throw new Error("Enabled Sentry upload accepted a blank package version");
  } catch (error) {
    if (!String(error.message).includes("package.json version")) throw error;
  }

  const rollupConfig = readFileSync("./build/rollup.config.mjs", "utf8");
  assert.match(rollupConfig, /resolveSentryBuild\(settings, packageMetadata\)/);
  assert.match(rollupConfig, /name: sentry\.release/);
  assert.doesNotMatch(rollupConfig, /name: settings\.VERSION/);
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
  "admin", "analytics", "builder", "file", "help", "home", "index", "manual", "messages",
  "page", "project", "report", "results", "user",
]);
assert.equal(VIEW_REGISTRY.category.entry, VIEW_REGISTRY.form.entry);
const documentedBudgets = Object.fromEntries(
  [...readFileSync("documentation/INFRA_BUILD.md", "utf8").matchAll(
    /^\| `([a-z]+)` \| [^|]+ \| ([0-9]+) \|$/gm,
  )].map(([, key, kib]) => [key, Number(kib) * 1024]),
);
assert.deepEqual(documentedBudgets, STARTUP_BUDGETS);

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
  "main", "manual", "help", "results", "analytics", "project", "page", "home",
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

// Revision services may be reachable dynamically, but none may become part
// of a Core view's static closure, even through an intermediate chunk.
for (const module of ["watcher", "reconciler", "modals", "preview"]) {
  const revisions = structuredClone(bundle);
  const revisionFile = "chunks/form-revisions.js";
  const bridgeFile = "chunks/revision-bridge.js";
  revisions[revisionFile] = {
    type: "chunk", fileName: revisionFile, name: "form-revisions",
    code: "x", isEntry: false, imports: [],
    modules: { [`/src/script/forms/revisions/${module}.mjs`]: {} },
  };
  revisions[bridgeFile] = {
    type: "chunk", fileName: bridgeFile, name: "revision-bridge",
    code: "x", isEntry: false, imports: [revisionFile], modules: {},
  };
  revisions["chunks/views/page.js"].dynamicImports = [bridgeFile];
  assert.doesNotThrow(() => validateStartupBudgets(revisions));
  revisions["chunks/views/page.js"].imports = [bridgeFile];
  assert.throws(
    () => validateStartupBudgets(revisions),
    /Core view page statically includes .*forms\/revisions\//,
    `${module} must remain outside the Core startup closure`,
  );
}
''',
        module=True,
    )


# @matrix frontend-build : modulepreload view-registry
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


# @matrix frontend-build : chunking interaction-foundation modulepreload
def test_interaction_preloads_have_stable_manual_chunks(run_node):
    run_node(
        r'''
import assert from "node:assert/strict";
import { interactionFoundationChunk } from "./build/utility.mjs";

const root = "/checkout/src/script/";
for (const module of [
  "shared/endpoints.mjs", "shared/errors.mjs", "shared/notificationState.mjs",
  "shared/request.mjs", "shared/transitions.mjs", "shared/utilities.mjs",
  "views/base/shell.mjs",
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
  "views/base/index.mjs", "widgets/tables/visibilityState.mjs",
]) {
  assert.equal(
    interactionFoundationChunk(`${root}${module}`),
    "index-foundation",
  );
}
assert.equal(interactionFoundationChunk(`${root}views/home.mjs`), undefined);
assert.equal(interactionFoundationChunk("\0virtual:styles"), undefined);

''',
        module=True,
    )


# @source build/publication.mjs::recordBuildArtifacts
# @matrix frontend-build : artifact-inventory chunking view-registry warnings build-modes
def test_rollup_modes_preserve_bundle_and_publication_contracts(run_node):
    run_node(
        r'''
import assert from "node:assert/strict";
import { mkdtempSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { pathToFileURL } from "node:url";

// Load style registries from the repository before isolating installer settings.
const { interactionFoundationChunk } = await import("./build/utility.mjs");
const { VIEW_ENTRIES } = await import("./src/script/viewRegistry.mjs");
const root = process.cwd();
const fixture = mkdtempSync(join(tmpdir(), "lagniappe-build-version-"));
const inventory = join(fixture, "inventory.json");
process.env.LAGNIAPPE_FRONTEND_ARTIFACT_INVENTORY = inventory;
process.env.LAGNIAPPE_FRONTEND_BUILD_ID = "bversiontest";
try {
  mkdirSync(join(fixture, "config/files"), { recursive: true });
  writeFileSync(join(fixture, "config/files/lagniappe_settings.yaml"), "VERSION: 9.8.7\n");
  writeFileSync(join(fixture, "package.json"), JSON.stringify({ version: "1.2.3" }));
  process.chdir(fixture);
  for (const [config, mode] of [
    ["rollup.config.mjs", "production"],
    ["rollup.dev.config.mjs", "development"],
  ]) {
    const { default: bundles } = await import(pathToFileURL(join(root, "build", config)));
    assert.equal(bundles.length, 3);
    const [login, sentry, main] = bundles;
    assert.equal(login.input, "./src/script/login.mjs");
    assert.equal(sentry.input, "./src/script/sentry.mjs");
    assert.equal(login.output.file, "./lagniappe/web/static/login.js");
    assert.equal(sentry.output.file, "./lagniappe/web/static/sentry.js");
    assert.equal(main.input.main, "./src/script/main.mjs");
    assert.equal(main.input.public, "./src/script/public.mjs");
    assert.deepEqual(Object.keys(main.input).sort(), ["main", "public", ...Object.keys(VIEW_ENTRIES)].sort());
    for (const [name, source] of Object.entries(VIEW_ENTRIES)) {
      assert.equal(main.input[name], `./src/script/${source.replace(/^\.\//, "")}`);
      assert.equal(main.output.entryFileNames({ name }), "chunks/views/[name].js");
    }
    assert.equal(main.output.entryFileNames({ name: "main" }), "script.js");
    assert.equal(main.output.entryFileNames({ name: "public" }), "chunks/views/[name].js");
    assert.equal(main.output.chunkFileNames, "chunks/[name].js");
    assert.equal(main.output.dir, "./lagniappe/web/static/");
    assert.equal(main.output.manualChunks, interactionFoundationChunk);
    assert.equal(main.output.onlyExplicitManualChunks, true);

    const dependencyEval = { code: "EVAL", id: "/node_modules/vendor/index.js" };
    const applicationEval = { code: "EVAL", id: "/src/script/app.mjs" };
    const editorCycle = { code: "CIRCULAR_DEPENDENCY", ids: ["/node_modules/y-prosemirror/index.js"] };
    const applicationCycle = { code: "CIRCULAR_DEPENDENCY", ids: ["/src/script/app.mjs"] };
    const otherWarning = { code: "OTHER", id: "/node_modules/vendor/index.js" };
    const pluginInstances = new Set();
    for (const bundle of bundles) {
      assert.equal(bundle.output.format, "esm");
      assert.match(bundle.output.banner, /third-party-licenses\.txt/);
      assert.equal(bundle.output.sourcemap, mode === "production" ? false : undefined);
      assert.equal(bundle.output.minifyInternalExports, mode === "production" ? true : undefined);
      assert.equal(bundle.plugins.some(plugin => plugin.name === "esbuild-minify"), mode === "production");
      assert.ok(bundle.plugins.some(plugin => plugin.name === "json"));
      assert.ok(bundle.plugins.some(plugin => plugin.name === "node-resolve"));
      for (const plugin of bundle.plugins) {
        assert.ok(!pluginInstances.has(plugin), `${plugin.name} shares state across bundles`);
        pluginInstances.add(plugin);
      }
      const forwarded = [];
      for (const warning of [dependencyEval, applicationEval, editorCycle, applicationCycle, otherWarning]) {
        bundle.onwarn(warning, warning => forwarded.push(warning));
      }
      assert.deepEqual(forwarded, bundle === main
        ? [applicationEval, applicationCycle, otherWarning]
        : [applicationEval, editorCycle, applicationCycle, otherWarning]);
    }
    const pluginNames = main.plugins.map(plugin => plugin.name);
    assert.equal(pluginNames.includes("startup-budget"), mode === "production");
    assert.ok(pluginNames.indexOf("version-chunk-imports") < pluginNames.indexOf("replace"));
    assert.equal(pluginNames.indexOf("postcss") < pluginNames.indexOf("replace"), mode === "production");
    assert.equal(pluginNames.at(-1), "record-final-build-artifacts");
    const recorder = main.plugins.at(-1);
    recorder.writeBundle();
    const metadata = JSON.parse(readFileSync(inventory, "utf8"));
    assert.equal(metadata.version, "1.2.3", config);
    assert.equal(metadata.mode, mode);
    assert.equal(metadata.build_id, "bversiontest");
    assert.deepEqual(metadata.artifacts, [
      "lagniappe/web/start/styles/fonts.py",
      "lagniappe/web/start/styles/icons.py",
      "lagniappe/web/start/styles/styles.py",
      "lagniappe/web/static/sw.js",
    ]);
    const versions = [];
    for (const bundle of bundles) {
      const replacement = bundle.plugins.find(plugin => plugin.name === "replace");
      const versionCode = mode === "production" ? '"__VERSION__"' : '__VERSION__';
      const transformed = replacement.transform.call(
        {}, `export const version = ${versionCode}; export const mode = process.env.NODE_ENV;`, "version.js",
      );
      const values = await import(`data:text/javascript,${encodeURIComponent(transformed.code)}`);
      assert.equal(values.mode, mode);
      versions.push(values.version);
      if (mode === "production") assert.equal(values.version, "1.2.3");
      else assert.equal(new Date(values.version).toISOString(), values.version);
      if (bundle === main) {
        const buildId = replacement.transform.call({}, 'export default __BUILD_ID__;', "build.js");
        assert.equal(buildId.code, 'export default "bversiontest";');
      }
    }
    assert.equal(new Set(versions).size, 1);

  }
} finally {
  process.chdir(root);
  rmSync(fixture, { recursive: true, force: true });
}
''',
        module=True,
    )
