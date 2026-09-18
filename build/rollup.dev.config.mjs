import { mkdirSync, readFileSync } from "node:fs";
import replace from "@rollup/plugin-replace";
import tailwindcss from "@tailwindcss/postcss";
import postcss from "rollup-plugin-postcss";
import { visualizer } from "rollup-plugin-visualizer";
import { createRollupConfig } from "./rollup.shared.mjs";
import {
	buildStyles,
	emitFonts,
	emitPdfWorker,
	emitThirdPartyLicenses,
	generateBuildId,
	resolveFonts,
	STYLE_PIPELINE,
	updateServiceWorker,
} from "./utility.mjs";

const reportsDir = "./reports";
mkdirSync(reportsDir, { recursive: true });
const devVersion = new Date().toISOString();
const packageMetadata = JSON.parse(readFileSync("./package.json", "utf8"));
const buildId = process.env.LAGNIAPPE_FRONTEND_BUILD_ID || generateBuildId();

export default createRollupConfig({
	buildId,
	mode: "development",
	version: packageMetadata.version,
	entryPlugins: () => [
		replace({
			preventAssignment: true,
			values: {
				"process.env.NODE_ENV": JSON.stringify("development"),
				__VERSION__: JSON.stringify(devVersion),
			},
		}),
	],
	mainPlugins: [
		replace({
			preventAssignment: true,
			values: {
				"process.env.NODE_ENV": JSON.stringify("development"),
				__BUILD_ID__: JSON.stringify(buildId),
				__VERSION__: JSON.stringify(devVersion),
			},
		}),
		postcss({
			extract: STYLE_PIPELINE.css.output,
			plugins: [tailwindcss(), resolveFonts()],
			extensions: [".scss", ".css"],
			modules: false,
			inject: false,
		}),
		buildStyles(),
		emitFonts(),
		emitPdfWorker(),
		emitThirdPartyLicenses(),
		updateServiceWorker(buildId),
		visualizer({
			filename: `${reportsDir}/bundle-stats-dev.html`,
			gzipSize: true,
			template: "treemap",
		}),
	],
});
