import { captureError } from "../shared/errors.ts";

export const captureLoginError = (error: unknown, operation = "unknown") => {
	captureError(error, null, {
		login: {
			operation,
			timestamp: new Date().toISOString(),
			userAgent: navigator.userAgent,
		},
	});
};
