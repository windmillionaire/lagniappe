import { mkdirSync, readFileSync } from "node:fs";
import replace from "@rollup/plugin-replace";
import { sentryRollupPlugin } from "@sentry/rollup-plugin";
import tailwindcss from "@tailwindcss/postcss";
import cssnano from "cssnano";
import * as yaml from "js-yaml";
import { minify } from "rollup-plugin-esbuild";
import postcss from "rollup-plugin-postcss";
import { visualizer } from "rollup-plugin-visualizer";
import { createRollupConfig } from "./rollup.shared.mjs";
import { resolveSentryBuild } from "./sentry.mjs";
import { startupBudget } from "./startupBudget.mjs";
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
const uploadedSourceMaps = "./lagniappe/web/static/**/*.map";
const settings = yaml.load(
	readFileSync("./config/files/lagniappe_settings.yaml", "utf8"),
);
const packageMetadata = JSON.parse(readFileSync("./package.json", "utf8"));
const sentry = resolveSentryBuild(settings, packageMetadata);
const sentryPlugins = (project, sourcemaps) =>
	sentry.enabled
		? sentryRollupPlugin({
				org: "windmillionaire",
				project,
				authToken: sentry.authToken,
				release: {
					name: sentry.release,
				},
				sourcemaps,
				telemetry: false,
			})
		: [];
const buildId = process.env.LAGNIAPPE_FRONTEND_BUILD_ID || generateBuildId();

export default createRollupConfig({
	buildId,
	mode: "production",
	version: packageMetadata.version,
	output: { sourcemap: sentry.sourcemap, minifyInternalExports: true },
	entryPlugins: () => [
		minify({ legalComments: "eof" }),
		replace({
			preventAssignment: true,
			values: {
				"process.env.NODE_ENV": JSON.stringify("production"),
				__VERSION__: packageMetadata.version,
			},
		}),
		...sentryPlugins("lagniappe-frontend", {}),
	],
	mainPlugins: [
		minify({ legalComments: "eof" }),
		postcss({
			extract: STYLE_PIPELINE.css.output,
			plugins: [
				tailwindcss(),
				resolveFonts(),
				cssnano({
					preset: "default",
				}),
			],
			sourceMap: false,
			extensions: [".scss", ".css"],
			modules: false,
			inject: false,
		}),
		replace({
			preventAssignment: true,
			values: {
				"process.env.NODE_ENV": JSON.stringify("production"),
				__BUILD_ID__: JSON.stringify(buildId),
				__VERSION__: packageMetadata.version,
			},
		}),
		buildStyles(),
		emitFonts(),
		emitPdfWorker(),
		emitThirdPartyLicenses(),
		startupBudget(),
		updateServiceWorker(buildId),
		...sentryPlugins("lagniappe-frontend", {
			filesToDeleteAfterUpload: uploadedSourceMaps,
		}),
		visualizer({
			filename: `${reportsDir}/bundle-stats.html`,
			gzipSize: true,
			brotliSize: true,
			template: "treemap", // or "sunburst", "network"
		}),
	],
});
