import { captureError } from "../shared/errors.ts";

export const captureLoginError = (error, operation = "unknown") => {
	captureError(error, null, {
		login: {
			operation,
			timestamp: new Date().toISOString(),
			userAgent: navigator.userAgent,
		},
	});
};
