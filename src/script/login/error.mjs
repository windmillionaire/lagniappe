import { captureError } from "../shared/errors.mjs";

// @testable true
// @tests tests_js/test_015_error_tracking_frontend.py::test_login_error_delegates_to_shared_capture
// @matrix error-tracking login : login-context shared-capture
export const captureLoginError = (error, operation = "unknown") => {
	captureError(error, null, {
		login: {
			operation,
			timestamp: new Date().toISOString(),
			userAgent: navigator.userAgent,
		},
	});
};
