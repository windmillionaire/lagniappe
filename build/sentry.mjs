/**
 * Decide whether a production build can generate and upload hidden source maps.
 *
 * @testable true
 * @tests tests_js/test_032_build_configuration.py::test_sentry_build_requires_nonblank_upload_token
 * @features build
 * @dimensions sentry source-maps optional-credentials
 */
export const resolveSentryBuild = (settings = {}) => {
	const authToken =
		typeof settings.SENTRY_AUTH_TOKEN === "string"
			? settings.SENTRY_AUTH_TOKEN.trim()
			: "";
	return {
		enabled: authToken.length > 0,
		authToken: authToken || null,
		sourcemap: authToken ? "hidden" : false,
	};
};
