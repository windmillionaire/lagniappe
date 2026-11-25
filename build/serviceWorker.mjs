import { readFileSync } from "node:fs";
import { transformSync } from "esbuild";

export function renderServiceWorker(buildId, precacheUrls) {
	const sourcefile = "src/script/sw.template.ts";
	const protocol = JSON.parse(
		readFileSync("config/browser_protocol.json", "utf8"),
	);
	return transformSync(readFileSync(sourcefile, "utf8"), {
		loader: "ts",
		sourcefile,
		target: "es2024",
		define: {
			__BUILD_ID__: JSON.stringify(buildId),
			__BROWSER_PROTOCOL__: JSON.stringify(protocol),
			__PRECACHE_URLS__: JSON.stringify(precacheUrls),
		},
	}).code;
}
