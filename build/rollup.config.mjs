import { mkdirSync, readFileSync } from "node:fs";
import json from "@rollup/plugin-json";
import resolve from "@rollup/plugin-node-resolve";
import replace from "@rollup/plugin-replace";
import { sentryRollupPlugin } from "@sentry/rollup-plugin";
import tailwindcss from "@tailwindcss/postcss";
import cssnano from "cssnano";
import * as yaml from "js-yaml";
import { minify } from "rollup-plugin-esbuild";
import postcss from "rollup-plugin-postcss";
import { visualizer } from "rollup-plugin-visualizer";
import { VIEW_ENTRIES } from "../src/script/viewRegistry.mjs";
import { resolveSentryBuild } from "./sentry.mjs";
import { startupBudget } from "./startupBudget.mjs";
import {
	buildStyles,
	emitMaterialSymbols,
	emitPdfWorker,
	emitThirdPartyLicenses,
	generateBuildId,
	resolveMaterialSymbolsFont,
	STYLE_PIPELINE,
	updateConstantsBuildId,
	updateServiceWorker,
	versionChunkImports,
} from "./utility.mjs";

const reportsDir = "./reports";
mkdirSync(reportsDir, { recursive: true });
const uploadedSourceMaps = "./lagniappe/web/static/**/*.map";
const thirdPartyLicenseBanner =
	"/*! Third-party licenses: /third-party-licenses.txt */";
const mainInputs = {
	main: "./src/script/main.mjs",
	...Object.fromEntries(
		Object.entries(VIEW_ENTRIES).map(([entry, source]) => [
			entry,
			`./src/script/${source.replace(/^\.\//, "")}`,
		]),
	),
};

const settings = yaml.load(
	readFileSync("./config/files/lagniappe_settings.yaml", "utf8"),
);
const sentry = resolveSentryBuild(settings);
const sentryPlugins = (project, sourcemaps) =>
	sentry.enabled
		? sentryRollupPlugin({
				org: "windmillionaire",
				project,
				authToken: sentry.authToken,
				release: {
					name: settings.VERSION,
				},
				sourcemaps,
				telemetry: false,
			})
		: [];
const buildId = generateBuildId();
updateConstantsBuildId(buildId);

export default [
	// Login bundle
	{
		input: "./src/script/login.mjs",
		output: {
			file: "./lagniappe/web/static/login.js",
			format: "esm",
			sourcemap: sentry.sourcemap,
			name: "login",
			minifyInternalExports: true,
			banner: thirdPartyLicenseBanner,
		},
		plugins: [
			buildStyles(),
			json(),
			resolve({
				browser: true,
				extensions: ["js", ".mjs", ".json"],
				preferBuiltins: false,
			}),
			minify({ legalComments: "eof" }),
			replace({
				preventAssignment: true,
				values: {
					"process.env.NODE_ENV": JSON.stringify("production"),
					__VERSION__: settings.VERSION,
				},
			}),
			...sentryPlugins("lagniappe-frontend", {}),
		],
		onwarn(warning, warn) {
			if (warning.code === "EVAL" && warning.id.includes("node_modules"))
				return;
			warn(warning);
		},
	},
	// Browser error-monitoring bundle (loaded only when monitoring is enabled)
	{
		input: "./src/script/sentry.mjs",
		output: {
			file: "./lagniappe/web/static/sentry.js",
			format: "esm",
			sourcemap: sentry.sourcemap,
			name: "sentry",
			minifyInternalExports: true,
			banner: thirdPartyLicenseBanner,
		},
		plugins: [
			json(),
			resolve({
				browser: true,
				extensions: ["js", ".mjs", ".json"],
				preferBuiltins: false,
			}),
			minify({ legalComments: "eof" }),
			replace({
				preventAssignment: true,
				values: {
					"process.env.NODE_ENV": JSON.stringify("production"),
					__VERSION__: settings.VERSION,
				},
			}),
			...sentryPlugins("lagniappe-frontend", {}),
		],
		onwarn(warning, warn) {
			if (warning.code === "EVAL" && warning.id.includes("node_modules"))
				return;
			warn(warning);
		},
	},
	// Main bundle
	{
		input: mainInputs,
		output: {
			dir: "./lagniappe/web/static/",
			entryFileNames: ({ name }) =>
				name === "main" ? "script.js" : "chunks/views/[name].js",
			chunkFileNames: "chunks/[name].js",
			format: "esm",
			sourcemap: sentry.sourcemap,
			name: "lagniappe",
			minifyInternalExports: true,
			banner: thirdPartyLicenseBanner,
		},
		plugins: [
			json(),
			resolve({
				browser: true,
				extensions: ["js", ".mjs", ".json"],
				preferBuiltins: false,
			}),
			versionChunkImports(buildId),
			minify({ legalComments: "eof" }),
			postcss({
				extract: STYLE_PIPELINE.css.output,
				plugins: [
					tailwindcss(),
					resolveMaterialSymbolsFont(),
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
					__VERSION__: settings.VERSION,
				},
			}),
			buildStyles(),
			emitMaterialSymbols(),
			emitPdfWorker(),
			emitThirdPartyLicenses(),
			startupBudget(),
			updateServiceWorker(buildId, settings.VERSION, "production"),
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
		onwarn(warning, warn) {
			if (warning.code === "EVAL" && warning.id.includes("node_modules"))
				return;
			if (
				warning.code === "CIRCULAR_DEPENDENCY" &&
				warning.ids?.some((id) => id.includes("y-prosemirror"))
			)
				return;
			warn(warning);
		},
	},
];
