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
