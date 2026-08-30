/**
 * Decide whether a production build can generate and upload hidden source maps.
 *
 * @testable true
 * @tests tests_js/test_032_build_configuration.py::test_sentry_build_uses_package_release_and_requires_upload_token
 * @matrix build : optional-credentials release-version sentry source-maps
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
