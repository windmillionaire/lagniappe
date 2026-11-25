import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import * as yaml from "js-yaml";

export const readBuildSettings = () => {
	const path = resolve(
		process.env.LAGNIAPPE_CONFIG_ROOT || ".",
		"config/files/lagniappe_settings.yaml",
	);
	try {
		return yaml.load(readFileSync(path, "utf8")) || {};
	} catch (error) {
		if (error.code === "ENOENT") return {};
		throw error;
	}
};

/**
 * Decide whether a production build can generate and upload hidden source maps.
 *
 */
export const resolveSentryBuild = (settings = {}, packageMetadata = {}) => {
	const authToken =
		typeof settings.SENTRY_AUTH_TOKEN === "string"
			? settings.SENTRY_AUTH_TOKEN.trim()
			: "";
	const release =
		typeof packageMetadata.version === "string"
			? packageMetadata.version.trim()
			: "";
	if (authToken && !release) {
		throw new Error("Sentry uploads require a package.json version");
	}
	return {
		enabled: authToken.length > 0,
		authToken: authToken || null,
		release: release || null,
		sourcemap: authToken ? "hidden" : false,
	};
};
