import { captureError } from "../shared/errors.mjs";

export const captureLoginError = (error, operation = "unknown") => {
	captureError(error, null, {
		login: {
			operation,
			timestamp: new Date().toISOString(),
			userAgent: navigator.userAgent,
		},
	});
};
