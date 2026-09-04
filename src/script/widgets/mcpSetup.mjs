const VERSION_PATTERN = /^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$/;
const DIGEST_PATTERN = /^[0-9a-f]{64}$/;
const MAX_WHEEL_BYTES = 16 * 1024 * 1024;
const PLATFORM_ID = "linux-x86_64-cpython-3.14";

/**
 * @testable true
 * @tests tests_js/test_045_mcp_setup.py::test_mcp_setup_uses_relative_credentialless_manifest_fetch_and_validated_origin
 * @matrix mcp-package user-settings : actor-gate build-marker compatibility content-addressing manifest-fetch origin-validation platform release-consistency setup-command
 */
export class McpSetup {
	constructor(target, { fetchManifest = globalThis.fetch } = {}) {
		this.target = target;
		this.fetchManifest = fetchManifest;
		this.controller = null;
	}

	init() {
		if (!this.target) return;
		this.controller = new AbortController();
		void this._load();
	}

	destroy() {
		this.controller?.abort();
		this.controller = null;
	}

	_allowedOrigin() {
		let allowed;
		try {
			allowed = JSON.parse(this.target.dataset.allowedOrigins || "[]");
		} catch {
			throw new Error("The MCP setup origin policy is invalid.");
		}
		if (!Array.isArray(allowed) || !allowed.length) {
			throw new Error("The MCP setup origin policy is unavailable.");
		}
		for (const value of allowed) {
			let parsed;
			try {
				parsed = new URL(value);
			} catch {
				throw new Error("The MCP setup origin policy is invalid.");
			}
			if (
				typeof value !== "string" ||
				parsed.protocol !== "https:" ||
				parsed.origin !== value ||
				parsed.pathname !== "/" ||
				parsed.search ||
				parsed.hash
			) {
				throw new Error("The MCP setup origin policy is invalid.");
			}
		}
		if (!allowed.includes(window.location.origin)) {
			throw new Error(
				"Open this page on its configured Lagniappe origin to install MCP.",
			);
		}
		return window.location.origin;
	}

	_validateManifest(manifest, responseBuildId) {
		const release = manifest?.current;
		const version = release?.version;
		const digest = release?.sha256;
		const buildId = manifest?.application?.build_id;
		const expectedBuildId = this.target.dataset.buildId;
		const compatibility = release?.compatibility;
		const platform = release?.platforms?.[0];
		const matchingReleases = Array.isArray(manifest?.releases)
			? manifest.releases.filter((candidate) => candidate?.version === version)
			: [];
		const filename = `lagniappe_mcp-${version}-py3-none-any.whl`;
		const path = `/mcp/releases/${version}/${digest}/${filename}`;
		if (
			manifest?.schema !== 1 ||
			manifest?.package?.name !== "lagniappe-mcp" ||
			manifest?.package?.entry_point !== "lagniappe-mcp" ||
			!VERSION_PATTERN.test(version || "") ||
			!DIGEST_PATTERN.test(digest || "") ||
			release?.filename !== filename ||
			release?.artifact_path !== path ||
			release?.supported !== true ||
			release?.python_requirement !== ">=3.14,<3.15" ||
			!Number.isSafeInteger(release?.size) ||
			release.size <= 0 ||
			release.size > MAX_WHEEL_BYTES ||
			!Array.isArray(release?.platforms) ||
			release.platforms.length !== 1 ||
			platform?.id !== PLATFORM_ID ||
			platform?.system !== "linux" ||
			platform?.architecture !== "x86_64" ||
			platform?.libc !== "glibc>=2.17" ||
			platform?.python !== "3.14" ||
			compatibility?.api_min !== "v1" ||
			compatibility?.api_max !== "v1" ||
			compatibility?.contract_min !== 6 ||
			compatibility?.contract_max !== 6 ||
			!DIGEST_PATTERN.test(compatibility?.openapi_sha256 || "") ||
			!DIGEST_PATTERN.test(compatibility?.contract_source_sha256 || "") ||
			matchingReleases.length !== 1 ||
			JSON.stringify(matchingReleases[0]) !== JSON.stringify(release) ||
			!/^b[0-9a-f]{7}$/.test(buildId || "") ||
			!/^b[0-9a-f]{7}$/.test(expectedBuildId || "") ||
			!/^b[0-9a-f]{7}$/.test(responseBuildId || "") ||
			buildId !== expectedBuildId ||
			responseBuildId !== expectedBuildId
		) {
			throw new Error("The MCP release manifest failed validation.");
		}
		return { digest, path, version };
	}

	async _load() {
		try {
			const origin = this._allowedOrigin();
			const response = await this.fetchManifest("/mcp/manifest.json", {
				method: "GET",
				credentials: "omit",
				cache: "no-store",
				redirect: "error",
				headers: { Accept: "application/json" },
				signal: this.controller?.signal,
			});
			if (!response?.ok)
				throw new Error("The MCP release manifest is unavailable.");
			const responseBuildId = response.headers?.get?.("X-Lagniappe-Build-ID");
			const release = this._validateManifest(
				await response.json(),
				responseBuildId,
			);
			this._render(origin, release);
		} catch (error) {
			if (error?.name !== "AbortError") this._error(error?.message);
		}
	}

	_render(origin, { digest, path, version }) {
		const artifactUrl = new URL(path, origin).href;
		const install =
			"pipx install --python python3.14 --backend pip " +
			"--pip-args='--only-binary=:all: --no-cache-dir' " +
			`"${artifactUrl}#sha256=${digest}"`;
		const configure =
			`lagniappe-mcp configure codex --url "${origin}" ` +
			"--profile personal";
		const diagnostic = "lagniappe-mcp check --profile personal";
		this.target.querySelector("[data-role='mcp-install-command']").textContent =
			install;
		this.target.querySelector(
			"[data-role='mcp-configure-command']",
		).textContent = configure;
		this.target.querySelector(
			"[data-role='mcp-diagnostic-command']",
		).textContent = diagnostic;
		this.target.querySelector("[data-role='mcp-setup-status']").textContent =
			`Verified adapter ${version} is available.`;
		this.target.querySelector(
			"[data-role='mcp-setup-commands']",
		).dataset.visible = "true";
		this._bindCopy("copy-mcp-install", install);
		this._bindCopy("copy-mcp-configure", configure);
		this._bindCopy("copy-mcp-diagnostic", diagnostic);
	}

	_bindCopy(action, value) {
		const button = this.target.querySelector(`[data-action='${action}']`);
		button?.addEventListener(
			"click",
			async () => {
				try {
					await navigator.clipboard.writeText(value);
					button.textContent = "Copied";
				} catch {
					button.textContent = "Copy failed";
				}
			},
			{ signal: this.controller?.signal },
		);
	}

	_error(message) {
		const status = this.target.querySelector("[data-role='mcp-setup-status']");
		const error = this.target.querySelector("[data-role='mcp-setup-error']");
		const commands = this.target.querySelector(
			"[data-role='mcp-setup-commands']",
		);
		if (status) status.textContent = "MCP setup is unavailable.";
		if (commands) commands.dataset.visible = "false";
		if (error) {
			error.textContent = message || "The MCP release could not be verified.";
			error.dataset.visible = "true";
		}
	}
}
