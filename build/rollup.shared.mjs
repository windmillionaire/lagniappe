import json from "@rollup/plugin-json";
import resolve from "@rollup/plugin-node-resolve";
import { VIEW_ENTRIES } from "../src/script/viewRegistry.mjs";
import { recordBuildArtifacts } from "./publication.mjs";
import {
	buildStyles,
	interactionFoundationChunk,
	versionChunkImports,
} from "./utility.mjs";

const thirdPartyLicenseBanner =
	"/*! Third-party licenses: /third-party-licenses.txt */";

/**
 * @testable false
 * @covered-by build/rollup.shared.mjs::createRollupConfig
 */
const browserPlugins = () => [
	json(),
	resolve({
		browser: true,
		extensions: ["js", ".mjs", ".json"],
		preferBuiltins: false,
	}),
];

/**
 * @testable false
 * @covered-by build/rollup.shared.mjs::createRollupConfig
 */
const onwarn = (warning, warn) => {
	if (warning.code === "EVAL" && warning.id.includes("node_modules")) return;
	warn(warning);
};

/**
 * @testable false
 * @covered-by build/rollup.shared.mjs::createRollupConfig
 */
const onMainWarning = (warning, warn) => {
	if (
		warning.code === "CIRCULAR_DEPENDENCY" &&
		warning.ids?.some((id) => id.includes("y-prosemirror"))
	)
		return;
	onwarn(warning, warn);
};

/**
 * Build the shared entry/output contract with fresh plugins for each bundle.
 * Mode-specific transforms stay ordered in the calling configuration.
 *
 * @testable true
 * @tests tests_js/test_032_build_configuration.py::test_rollup_modes_preserve_bundle_and_publication_contracts
 * @matrix frontend-build : artifact-inventory chunking view-registry warnings build-modes
 */
export const createRollupConfig = ({
	buildId,
	mode,
	version,
	output = {},
	entryPlugins,
	mainPlugins,
}) => [
	// Standalone login and optional browser error-monitoring bundles.
	...["login", "sentry"].map((name) => ({
		input: `./src/script/${name}.mjs`,
		output: {
			file: `./lagniappe/web/static/${name}.js`,
			format: "esm",
			name,
			banner: thirdPartyLicenseBanner,
			...output,
		},
		plugins: [
			...(name === "login" ? [buildStyles()] : []),
			...browserPlugins(),
			...entryPlugins(),
			recordBuildArtifacts(),
		],
		onwarn,
	})),
	{
		input: {
			main: "./src/script/main.mjs",
			public: "./src/script/public.mjs",
			...Object.fromEntries(
				Object.entries(VIEW_ENTRIES).map(([entry, source]) => [
					entry,
					`./src/script/${source.replace(/^\.\//, "")}`,
				]),
			),
		},
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
			...output,
		},
		plugins: [
			...browserPlugins(),
			versionChunkImports(buildId),
			...mainPlugins,
			recordBuildArtifacts({
				final: true,
				buildId,
				mode,
				version,
				extraArtifacts: [
					"lagniappe/web/start/styles/icons.py",
					"lagniappe/web/start/styles/fonts.py",
					"lagniappe/web/start/styles/styles.py",
					"lagniappe/web/static/sw.js",
				],
			}),
		],
		onwarn: onMainWarning,
	},
];
