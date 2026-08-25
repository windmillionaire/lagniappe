"""Node-backed checks for stable frontend chunk versioning."""


# @features frontend-build cache
# @dimensions chunk-versioning bundle-consistency
def test_rollup_versions_generated_chunk_imports_and_precache_urls(run_node):
    run_node(
        r"""
import assert from "node:assert/strict";
import { rollup } from "rollup";
import {
  precacheUrls,
  versionChunkImports,
} from "./build/utility.mjs";

const buildId = "btest123";
const modules = new Map([
  ["entry", `
    import { shared } from "shared";
    export { shared };
    export const loadLazy = () => import("lazy");
  `],
  ["shared", `export const shared = "shared";`],
  ["lazy", `
    import { shared } from "shared";
    export const lazy = shared;
  `],
]);
const virtualModules = {
  name: "virtual-modules",
  resolveId(source) {
    return modules.has(source) ? source : null;
  },
  load(id) {
    return modules.get(id) ?? null;
  },
};

const build = await rollup({
  input: "entry",
  plugins: [virtualModules, versionChunkImports(buildId)],
});
const { output } = await build.generate({
  format: "esm",
  entryFileNames: "script.js",
  chunkFileNames: "chunks/[name].js",
  manualChunks(id) {
    if (id === "shared") return "shared";
  },
});
await build.close();

const chunks = Object.fromEntries(
  output
    .filter((item) => item.type === "chunk")
    .map((item) => [item.fileName, item]),
);
assert.deepEqual(Object.keys(chunks).sort(), [
  "chunks/lazy.js",
  "chunks/shared.js",
  "script.js",
]);

assert.match(chunks["script.js"].code, /\.\/chunks\/shared\.js\?v=btest123/);
assert.match(chunks["script.js"].code, /\.\/chunks\/lazy\.js\?v=btest123/);
assert.match(chunks["chunks/lazy.js"].code, /\.\/shared\.js\?v=btest123/);
assert.ok(!Object.keys(chunks).some((fileName) => fileName.includes("?")));

const precacheBundle = {
  ...chunks,
  "chunks/views/manual.js": {
    type: "chunk",
    fileName: "chunks/views/manual.js",
  },
};
assert.deepEqual(precacheUrls(precacheBundle, buildId), [
  "/chunks/lazy.js?v=btest123",
  "/chunks/shared.js?v=btest123",
  "/chunks/views/manual.js?v=btest123",
]);
""",
        module=True,
    )


# @features frontend-build
# @dimensions service-worker build-identity
def test_service_worker_records_the_build_identity(run_node):
    run_node(
        r"""
import assert from "node:assert/strict";
import {
  mkdirSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { updateServiceWorker } from "./build/utility.mjs";

const originalDirectory = process.cwd();
const outputDirectory = mkdtempSync(join(tmpdir(), "lagniappe-build-mode-"));
try {
  process.chdir(outputDirectory);
  mkdirSync("src/script", { recursive: true });
  mkdirSync("config", { recursive: true });
  mkdirSync("lagniappe/web/static", { recursive: true });
  writeFileSync(
    "src/script/sw.template.mjs",
    [
      'const BUILD_ID = "__BUILD_ID__";',
      "const PROTOCOL = /* __BROWSER_PROTOCOL__ */ null;",
      "const PRECACHE = /* __PRECACHE_URLS__ */ [];",
    ].join("\n"),
  );
  writeFileSync("config/browser_protocol.json", '{"version": 1}\n');

  updateServiceWorker("b1234567").writeBundle({}, {});

  assert.match(
    readFileSync("lagniappe/web/static/sw.js", "utf8"),
    /b1234567/,
  );
} finally {
  process.chdir(originalDirectory);
  rmSync(outputDirectory, { recursive: true });
}
""",
        module=True,
    )


# @features frontend-build
# @dimensions source-integrity artifact-inventory nested-chunks completion-marker
def test_frontend_publication_records_recursive_artifacts_and_source_identity(run_node):
    run_node(
        r"""
import assert from "node:assert/strict";
import {
  mkdirSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const originalDirectory = process.cwd();
const outputDirectory = mkdtempSync(join(tmpdir(), "lagniappe-publication-"));
const inventoryPath = join(outputDirectory, "inventory.json");
process.env.LAGNIAPPE_FRONTEND_ARTIFACT_INVENTORY = inventoryPath;
const publication = await import(`./build/publication.mjs?test=${Date.now()}`);

const write = (relative, content) => {
  const path = join(outputDirectory, relative);
  mkdirSync(join(path, ".."), { recursive: true });
  writeFileSync(path, content);
};

try {
  process.chdir(outputDirectory);
  const contract = {
    schema: 1,
    source_roots: ["build", "src/script"],
    source_files: ["package.json"],
    exclusive_artifact_roots: ["lagniappe/web/static/chunks"],
    required_artifacts: [
      "lagniappe/web/static/login.js",
      "lagniappe/web/static/script.js",
      "lagniappe/web/static/sw.js",
    ],
    required_artifact_prefixes: [
      "lagniappe/web/static/chunks/",
      "lagniappe/web/static/chunks/views/",
    ],
  };
  write("build/publication.json", `${JSON.stringify(contract)}\n`);
  write("src/script/main.mjs", "export const current = true;\n");
  write("package.json", '{"version":"1.2.3"}\n');
  write("lagniappe/web/static/login.js", "login\n");
  write("lagniappe/web/static/script.js", "script\n");
  write("lagniappe/web/static/chunks/shared.js", "shared\n");
  write("lagniappe/web/static/chunks/views/home.js", "home\n");
  write("lagniappe/web/static/sw.js", "b1234567\n");

  const sourceIdentity = publication.frontendSourceIdentity(outputDirectory);
  publication.recordBuildArtifacts().generateBundle(
    { file: "./lagniappe/web/static/login.js" },
    { "login.js": { fileName: "login.js" } },
  );
  const final = publication.recordBuildArtifacts({
    final: true,
    buildId: "b1234567",
    mode: "production",
    version: "1.2.3",
    extraArtifacts: ["lagniappe/web/static/sw.js"],
  });
  final.generateBundle(
    { dir: "./lagniappe/web/static" },
    {
      "script.js": { fileName: "script.js" },
      "chunks/shared.js": { fileName: "chunks/shared.js" },
      "chunks/views/home.js": { fileName: "chunks/views/home.js" },
      "script.js.map": { fileName: "script.js.map" },
    },
  );
  final.writeBundle();

  const inventory = JSON.parse(readFileSync(inventoryPath, "utf8"));
  assert.deepEqual(inventory.artifacts, [
    "lagniappe/web/static/chunks/shared.js",
    "lagniappe/web/static/chunks/views/home.js",
    "lagniappe/web/static/login.js",
    "lagniappe/web/static/script.js",
    "lagniappe/web/static/sw.js",
  ]);
  const metadata = publication.publishFrontendBuild({
    root: outputDirectory,
    buildId: inventory.build_id,
    mode: inventory.mode,
    version: inventory.version,
    artifacts: inventory.artifacts,
    sourceIdentity,
    beforePublish: () => write("published-last", "yes\n"),
  });
  assert.equal(metadata.schema, 1);
  assert.equal(metadata.source.sha256, sourceIdentity);
  assert.equal(metadata.artifacts.length, 5);
  assert.equal(readFileSync("published-last", "utf8"), "yes\n");
  assert.deepEqual(
    JSON.parse(readFileSync("lagniappe/web/static/build.json", "utf8")),
    metadata,
  );
} finally {
  process.chdir(originalDirectory);
  delete process.env.LAGNIAPPE_FRONTEND_ARTIFACT_INVENTORY;
  rmSync(outputDirectory, { recursive: true });
}
""",
        module=True,
    )


# @features frontend-build
# @dimensions source-integrity artifact-integrity safe-failure
def test_frontend_publication_rejects_missing_outputs_and_source_drift(run_node):
    run_node(
        r"""
import assert from "node:assert/strict";
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import {
  frontendSourceIdentity,
  publishFrontendBuild,
} from "./build/publication.mjs";

const outputDirectory = mkdtempSync(join(tmpdir(), "lagniappe-publication-failure-"));
const write = (relative, content) => {
  const path = join(outputDirectory, relative);
  mkdirSync(join(path, ".."), { recursive: true });
  writeFileSync(path, content);
};

try {
  write("build/publication.json", `${JSON.stringify({
    schema: 1,
    source_roots: ["build", "src/script"],
    source_files: ["package.json"],
    exclusive_artifact_roots: ["lagniappe/web/static/chunks"],
    required_artifacts: ["lagniappe/web/static/script.js"],
    required_artifact_prefixes: ["lagniappe/web/static/chunks/"],
  })}\n`);
  write("src/script/main.mjs", "export const current = true;\n");
  write("package.json", '{"version":"1.2.3"}\n');
  write("lagniappe/web/static/script.js", "script\n");
  const sourceIdentity = frontendSourceIdentity(outputDirectory);
  let published = false;

  assert.throws(
    () => publishFrontendBuild({
      root: outputDirectory,
      buildId: "b1234567",
      mode: "production",
      version: "1.2.3",
      artifacts: [],
      sourceIdentity,
      beforePublish: () => { published = true; },
    }),
    /required artifact/,
  );
  assert.equal(published, false);

  write("lagniappe/web/static/chunks/shared.js", "shared\n");
  write("lagniappe/web/static/chunks/stale.js", "stale\n");
  assert.throws(
    () => publishFrontendBuild({
      root: outputDirectory,
      buildId: "b1234567",
      mode: "production",
      version: "1.2.3",
      artifacts: [
        "lagniappe/web/static/chunks/shared.js",
        "lagniappe/web/static/script.js",
      ],
      sourceIdentity,
      beforePublish: () => { published = true; },
    }),
    /not in the artifact inventory/,
  );
  assert.equal(published, false);

  write("src/script/main.mjs", "export const current = false;\n");
  assert.throws(
    () => publishFrontendBuild({
      root: outputDirectory,
      buildId: "b1234567",
      mode: "production",
      version: "1.2.3",
      artifacts: ["lagniappe/web/static/script.js"],
      sourceIdentity,
      beforePublish: () => { published = true; },
    }),
    /sources changed/,
  );
  assert.equal(published, false);
} finally {
  rmSync(outputDirectory, { recursive: true });
}
""",
        module=True,
    )


# @features frontend-build icons
# @dimensions font-delivery subset cache stale-cleanup
def test_material_symbols_subset_font_is_emitted_with_content_hash(run_node):
    run_node(
        r"""
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import {
  mkdirSync,
  mkdtempSync,
  readFileSync,
  readdirSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { emitMaterialSymbols } from "./build/utility.mjs";

const source = readFileSync(
  "./src/fonts/material-symbols-rounded.woff2",
);
const hash = createHash("sha256").update(source).digest("hex").slice(0, 12);
const emitted = [];
emitMaterialSymbols().generateBundle.call({
  emitFile(asset) {
    emitted.push(asset);
  },
});

assert.equal(emitted.length, 1);
assert.equal(emitted[0].type, "asset");
assert.equal(
  emitted[0].fileName,
  `fonts/material-symbols-rounded.${hash}.woff2`,
);
assert.deepEqual(emitted[0].source, source);

const outputDirectory = mkdtempSync(join(tmpdir(), "lagniappe-icons-"));
const fontsDirectory = join(outputDirectory, "fonts");
mkdirSync(fontsDirectory);
const currentFont = `material-symbols-rounded.${hash}.woff2`;
writeFileSync(join(fontsDirectory, currentFont), source);
writeFileSync(
  join(fontsDirectory, "material-symbols-rounded.0123456789ab.woff2"),
  "stale",
);
writeFileSync(
  join(
    fontsDirectory,
    "material-symbols-rounded-home.abcdef012345.woff2",
  ),
  "legacy",
);
writeFileSync(
  join(fontsDirectory, "material-symbols-rounded.woff2"),
  "unhashed",
);
writeFileSync(join(fontsDirectory, "source-sans-latin.woff2"), "other");

emitMaterialSymbols().writeBundle({ dir: outputDirectory });

assert.deepEqual(readdirSync(fontsDirectory).sort(), [
  currentFont,
  "source-sans-latin.woff2",
].sort());
rmSync(outputDirectory, { recursive: true });
""",
        module=True,
    )


# @features frontend-build icons
# @dimensions font-delivery css-url-resolution
def test_material_symbols_css_points_to_the_content_hashed_font(run_node):
    run_node(
        r"""
import assert from "node:assert/strict";
import postcss from "postcss";
import { resolveMaterialSymbolsFont } from "./build/utility.mjs";

const result = await postcss([resolveMaterialSymbolsFont()]).process(`
  @font-face {
    font-family: "Material Symbols Rounded";
    src: url("/fonts/material-symbols-rounded.woff2") format("woff2");
  }
`, { from: undefined });

assert.match(
  result.css,
  /url\("\/fonts\/material-symbols-rounded\.[a-f0-9]{12}\.woff2"\) format\("woff2"\)/,
);
assert.doesNotMatch(
  result.css,
  /url\("\/fonts\/material-symbols-rounded\.woff2"\)/,
);
""",
        module=True,
    )


# @features frontend-build licensing
# @dimensions browser-notice-delivery
def test_third_party_notices_are_emitted_with_browser_assets(run_node):
    run_node(
        r"""
import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import { emitThirdPartyLicenses } from "./build/utility.mjs";

const emitted = [];
emitThirdPartyLicenses().generateBundle.call({
  emitFile(asset) {
    emitted.push(asset);
  },
});

assert.equal(emitted.length, 1);
assert.equal(emitted[0].type, "asset");
assert.equal(emitted[0].fileName, "third-party-licenses.txt");

for (const fileName of readdirSync("./THIRD_PARTY_LICENSES")) {
  const expected = readFileSync(
    join("./THIRD_PARTY_LICENSES", fileName),
    "utf8",
  ).trimEnd();
  assert.ok(emitted[0].source.includes(`===== ${fileName} =====`));
  assert.ok(emitted[0].source.includes(expected));
}
""",
        module=True,
    )
