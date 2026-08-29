import { mkdirSync, readFileSync } from "node:fs";
import json from "@rollup/plugin-json";
import resolve from "@rollup/plugin-node-resolve";
import replace from "@rollup/plugin-replace";
import tailwindcss from "@tailwindcss/postcss";
import * as yaml from "js-yaml";
import postcss from "rollup-plugin-postcss";
import { visualizer } from "rollup-plugin-visualizer";
import { VIEW_ENTRIES } from "../src/script/viewRegistry.mjs";
import { recordBuildArtifacts } from "./publication.mjs";
import {
	buildStyles,
	emitMaterialSymbols,
	emitPdfWorker,
	emitThirdPartyLicenses,
	generateBuildId,
	interactionFoundationChunk,
	resolveMaterialSymbolsFont,
	STYLE_PIPELINE,
	updateServiceWorker,
	versionChunkImports,
} from "./utility.mjs";

const reportsDir = "./reports";
mkdirSync(reportsDir, { recursive: true });
const thirdPartyLicenseBanner =
	"/*! Third-party licenses: /third-party-licenses.txt */";
const mainInputs = {
	main: "./src/script/main.mjs",
	public: "./src/script/public.mjs",
	...Object.fromEntries(
		Object.entries(VIEW_ENTRIES).map(([entry, source]) => [
			entry,
			`./src/script/${source.replace(/^\.\//, "")}`,
		]),
	),
};
const devVersion = new Date().toISOString();
const settings = yaml.load(
	readFileSync("./config/files/lagniappe_settings.yaml", "utf8"),
);
const buildId = process.env.LAGNIAPPE_FRONTEND_BUILD_ID || generateBuildId();

export default [
	{
		input: "./src/script/login.mjs",
		output: {
			file: "./lagniappe/web/static/login.js",
			format: "esm",
			name: "login",
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
			replace({
				preventAssignment: true,
				values: {
					"process.env.NODE_ENV": JSON.stringify("development"),
					__VERSION__: JSON.stringify(devVersion),
				},
			}),
			recordBuildArtifacts(),
		],
		onwarn(warning, warn) {
			if (warning.code === "EVAL" && warning.id.includes("node_modules"))
				return;
			warn(warning);
		},
	},
	{
		input: "./src/script/sentry.mjs",
		output: {
			file: "./lagniappe/web/static/sentry.js",
			format: "esm",
			name: "sentry",
			banner: thirdPartyLicenseBanner,
		},
		plugins: [
			json(),
			resolve({
				browser: true,
				extensions: ["js", ".mjs", ".json"],
				preferBuiltins: false,
			}),
			replace({
				preventAssignment: true,
				values: {
					"process.env.NODE_ENV": JSON.stringify("development"),
					__VERSION__: JSON.stringify(devVersion),
				},
			}),
			recordBuildArtifacts(),
		],
		onwarn(warning, warn) {
			if (warning.code === "EVAL" && warning.id.includes("node_modules"))
				return;
			warn(warning);
		},
	},
	{
		input: mainInputs,
		output: {
			dir: "./lagniappe/web/static/",
			entryFileNames: ({ name }) =>
				name === "main" ? "script.js" : "chunks/views/[name].js",
			chunkFileNames: "chunks/[name].js",
			manualChunks: interactionFoundationChunk,
			onlyExplicitManualChunks: true,
			format: "esm",
			name: "lagniappe",
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
				plugins: [tailwindcss(), resolveMaterialSymbolsFont()],
				extensions: [".scss", ".css"],
				modules: false,
				inject: false,
			}),
			buildStyles(),
			emitMaterialSymbols(),
			emitPdfWorker(),
			emitThirdPartyLicenses(),
			updateServiceWorker(buildId),
			visualizer({
				filename: `${reportsDir}/bundle-stats-dev.html`,
				gzipSize: true,
				template: "treemap",
			}),
			recordBuildArtifacts({
				final: true,
				buildId,
				mode: "development",
				version: settings.VERSION,
				extraArtifacts: [
					"lagniappe/web/start/styles/icons.py",
					"lagniappe/web/start/styles/styles.py",
					"lagniappe/web/static/sw.js",
				],
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
