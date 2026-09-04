"""Node-backed checks for the trial-gated MCP setup helper."""


# @matrix mcp-package user-settings : actor-gate build-marker compatibility content-addressing manifest-fetch origin-validation platform release-consistency setup-command
def test_mcp_setup_uses_relative_credentialless_manifest_fetch_and_validated_origin(
    run_node,
):
    run_node(
        r'''
const fs = require("node:fs");
const vm = require("node:vm");

const calls = [];
const copied = [];
const elements = new Map();
for (const selector of [
  "[data-role='mcp-install-command']",
  "[data-role='mcp-configure-command']",
  "[data-role='mcp-diagnostic-command']",
  "[data-role='mcp-setup-status']",
  "[data-role='mcp-setup-commands']",
  "[data-role='mcp-setup-error']",
]) {
  elements.set(selector, { dataset: {}, textContent: "" });
}
for (const action of [
  "copy-mcp-install",
  "copy-mcp-configure",
  "copy-mcp-diagnostic",
]) {
  elements.set(`[data-action='${action}']`, {
    addEventListener(type, callback) {
      if (type === "click") this.click = callback;
    },
    textContent: "Copy",
  });
}
const target = {
  dataset: {
    allowedOrigins: '["https://example.test"]',
    buildId: "b1234567",
  },
  querySelector(selector) { return elements.get(selector) || null; },
};
const digest = "a".repeat(64);
const current = {
  version: "0.1.0",
  sha256: digest,
  size: 4096,
  filename: "lagniappe_mcp-0.1.0-py3-none-any.whl",
  artifact_path:
    `/mcp/releases/0.1.0/${digest}/lagniappe_mcp-0.1.0-py3-none-any.whl`,
  supported: true,
  python_requirement: ">=3.14,<3.15",
  compatibility: {
    api_min: "v1",
    api_max: "v1",
    contract_min: 6,
    contract_max: 6,
    openapi_sha256: "b".repeat(64),
    contract_source_sha256: "c".repeat(64),
  },
  platforms: [{
    id: "linux-x86_64-cpython-3.14",
    system: "linux",
    architecture: "x86_64",
    libc: "glibc>=2.17",
    python: "3.14",
  }],
};
const manifest = {
  schema: 1,
  package: { name: "lagniappe-mcp", entry_point: "lagniappe-mcp" },
  application: { build_id: "b1234567" },
  current,
  releases: [current],
};
const fetchManifest = async (...args) => {
  calls.push(args);
  return {
    ok: true,
    headers: new Headers({ "X-Lagniappe-Build-ID": "b1234567" }),
    async json() { return manifest; },
  };
};
const context = {
  AbortController,
  console,
  fetch: fetchManifest,
  navigator: { clipboard: { async writeText(value) { copied.push(value); } } },
  URL,
  window: { location: { origin: "https://example.test" } },
};
context.globalThis = context;
vm.createContext(context);
let source = fs.readFileSync("src/script/widgets/mcpSetup.mjs", "utf8");
source = source.replace("export class McpSetup", "class McpSetup");
source += "\nglobalThis.McpSetup = McpSetup;";
vm.runInContext(source, context);

(async () => {
  const setup = new context.McpSetup(target, { fetchManifest });
  setup.controller = new AbortController();
  await setup._load();

  if (calls.length !== 1 || calls[0][0] !== "/mcp/manifest.json") {
    throw new Error("Manifest fetch was not literal, relative, and same-origin");
  }
  const options = calls[0][1];
  if (options.method !== "GET" || options.credentials !== "omit" ||
      options.cache !== "no-store" || options.redirect !== "error" ||
      options.headers.Accept !== "application/json") {
    throw new Error(`Unsafe manifest fetch options: ${JSON.stringify(options)}`);
  }
  const install = elements.get("[data-role='mcp-install-command']").textContent;
  if (!install.startsWith("pipx install --python python3.14 --backend pip ") ||
      !install.includes("--only-binary=:all:") ||
      !install.includes(`/0.1.0/${digest}/`) ||
      !install.endsWith(`#sha256=${digest}\"`) ||
      install.includes("uv tool")) {
    throw new Error(`Invalid MCP install command: ${install}`);
  }
  const configure = elements.get("[data-role='mcp-configure-command']").textContent;
  if (!configure.includes('--url "https://example.test"') ||
      !configure.includes("--profile personal") || configure.includes(digest)) {
    throw new Error(`Invalid MCP configuration command: ${configure}`);
  }
  const diagnostic = elements.get(
    "[data-role='mcp-diagnostic-command']",
  ).textContent;
  if (diagnostic !== "lagniappe-mcp check --profile personal") {
    throw new Error(`Invalid MCP diagnostic command: ${diagnostic}`);
  }
  await elements.get("[data-action='copy-mcp-diagnostic']").click();
  if (copied.length !== 1 || copied[0] !== diagnostic) {
    throw new Error(`MCP diagnostic command was not copied: ${copied}`);
  }
  if (elements.get("[data-role='mcp-setup-commands']").dataset.visible !== "true") {
    throw new Error("Validated MCP commands were not revealed");
  }

  const stalePage = {
    dataset: {
      allowedOrigins: '["https://example.test"]',
      buildId: "b7654321",
    },
    querySelector(selector) { return elements.get(selector) || null; },
  };
  const staleSetup = new context.McpSetup(stalePage, { fetchManifest });
  try {
    staleSetup._validateManifest(manifest, "b1234567");
    throw new Error("Manifest from a different application build was accepted");
  } catch (error) {
    if (!error.message.includes("failed validation")) throw error;
  }

  for (const responseBuildId of [undefined, "b7654321", "invalid"]) {
    try {
      setup._validateManifest(manifest, responseBuildId);
      throw new Error("Missing or mismatched response build marker was accepted");
    } catch (error) {
      if (!error.message.includes("failed validation")) throw error;
    }
  }

  for (const mutate of [
    (candidate) => { candidate.current.supported = false; },
    (candidate) => { candidate.current.compatibility.api_max = "v2"; },
    (candidate) => { candidate.current.compatibility.contract_max = 7; },
    (candidate) => { candidate.current.platforms[0].architecture = "aarch64"; },
    (candidate) => { candidate.releases[0].sha256 = "d".repeat(64); },
  ]) {
    const candidate = JSON.parse(JSON.stringify(manifest));
    mutate(candidate);
    try {
      setup._validateManifest(candidate, "b1234567");
      throw new Error("An incompatible or inconsistent manifest was accepted");
    } catch (error) {
      if (!error.message.includes("failed validation")) throw error;
    }
  }

  const denied = {
    dataset: {
      allowedOrigins: '["https://configured.example"]',
      buildId: "b1234567",
    },
    querySelector(selector) { return elements.get(selector) || null; },
  };
  const deniedSetup = new context.McpSetup(denied, { fetchManifest });
  deniedSetup.controller = new AbortController();
  await deniedSetup._load();
  if (calls.length !== 1) throw new Error("Denied origin fetched the manifest");
  if (elements.get("[data-role='mcp-setup-error']").dataset.visible !== "true") {
    throw new Error("Denied origin did not fail visibly");
  }
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
'''
    )
