import {
	addEventProcessor,
	captureException,
	captureMessage,
	getClient,
	init,
} from "@sentry/browser";
import { configureSentry } from "./shared/errors.ts";

if (typeof window !== "undefined") {
	window.Sentry = {
		addEventProcessor,
		captureException,
		captureMessage,
		getClient,
		init,
	};
	configureSentry();
}
