import * as Sentry from "@sentry/browser";
import { configureSentry } from "./shared/errors.mjs";

if (typeof window !== "undefined") {
	window.Sentry = Sentry;
	configureSentry();
}
