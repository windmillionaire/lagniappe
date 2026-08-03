import { createHash, randomBytes } from "node:crypto";
import {
	existsSync,
	readdirSync,
	readFileSync,
	unlinkSync,
	writeFileSync,
} from "node:fs";
import { posix as path } from "node:path";
import * as yaml from "js-yaml";
import MagicString from "magic-string";

const STYLE_PIPELINE = JSON.parse(
	readFileSync("./src/style/pipeline.json", "utf8"),
);
const STYLE_REGISTRY_SCHEMA = JSON.parse(
	readFileSync(`./${STYLE_PIPELINE.registry.schema}`, "utf8"),
);
const rawIconsYaml = yaml.load(
	readFileSync(`./${STYLE_PIPELINE.registry.icons}`, "utf8"),
);
const ICON_REGISTRY_SCHEMA = JSON.parse(
	readFileSync(`./${STYLE_PIPELINE.registry.icons_schema}`, "utf8"),
);
const rawStylesYaml = yaml.load(
	readFileSync(`./${STYLE_PIPELINE.registry.styles}`, "utf8"),
);
const constantsPath = "./config/constants.py";
const browserProtocolPath = "./config/browser_protocol.json";
const buildMetadataPath = "./lagniappe/web/static/build.json";
const BOOT_CONNECTIVITY_MODULE = "shared/connectivity.mjs";
const INTERACTION_FOUNDATION_MODULES = new Set([
	"shared/endpoints.mjs",
	"shared/errors.mjs",
	"shared/request.mjs",
	"shared/utilities.mjs",
	"views/base/shell.mjs",
]);
const CORE_FOUNDATION_MODULES = new Set([
	"elements/nav.mjs",
	"views/base/component.mjs",
	"views/base/core.mjs",
	"views/base/reconciliation.mjs",
	"views/base/services.mjs",
	"views/base/task.mjs",
	"widgets/loader.mjs",
]);
const INDEX_FOUNDATION_MODULES = new Set([
	"views/base/index.mjs",
	"widgets/tableVisibilityState.mjs",
]);

/**
 * Keep the interaction-critical view graph in stable chunks so templates can
 * preload it without depending on Rollup's incidental shared-chunk split.
 * Connectivity stays separate because the main boot entry imports it too.
 *
 * @testable true
 * @tests tests_js/test_032_build_configuration.py::test_interaction_preloads_have_stable_manual_chunks
 * @tests tests_js/test_032_build_configuration.py::test_templates_preload_registered_view_and_interaction_foundations
 * @pairs frontend-build:chunking frontend-build:modulepreload frontend-build:interaction-foundation
 */
const interactionFoundationChunk = (id) => {
	const normalized = id.replaceAll("\\", "/");
	if (normalized.endsWith("/config/browser_protocol.json")) {
		return "connectivity";
	}
	const marker = "/src/script/";
	const sourceIndex = normalized.lastIndexOf(marker);
	if (sourceIndex === -1) return undefined;
	const relative = normalized.slice(sourceIndex + marker.length);
	if (relative === BOOT_CONNECTIVITY_MODULE) return "connectivity";
	if (relative === "views/base/entity.mjs") return "entity-foundation";
	if (INDEX_FOUNDATION_MODULES.has(relative)) return "index-foundation";
	if (CORE_FOUNDATION_MODULES.has(relative)) return "core-foundation";
	return INTERACTION_FOUNDATION_MODULES.has(relative)
		? "foundation"
		: undefined;
};

/**
 * @testable false
 * @covered-by build/utility.mjs::virtualStyleModuleSource
 * @reason private serializer exercised through emitted module sources
 */
const stringify = (yaml) => {
	return JSON.stringify(yaml, null, 2);
};

const STYLE_RECORD_FIELDS = new Set(STYLE_REGISTRY_SCHEMA.record_fields);
const STYLE_REQUIRED_METADATA = new Set(
	STYLE_REGISTRY_SCHEMA.required_metadata,
);
const STYLE_SURFACES = new Set(STYLE_REGISTRY_SCHEMA.surfaces);
const STYLE_EXCEPTION_FIELDS = new Set(STYLE_REGISTRY_SCHEMA.exception_fields);
const STYLE_EXCEPTION_DIAGNOSTICS = new Set(
	STYLE_REGISTRY_SCHEMA.exception_diagnostics,
);
const STYLE_ID_SEGMENT = new RegExp(STYLE_REGISTRY_SCHEMA.id_segment_pattern);
const ICON_ID_SEGMENT = new RegExp(ICON_REGISTRY_SCHEMA.id_segment_pattern);
const ICON_GLYPH = new RegExp(ICON_REGISTRY_SCHEMA.glyph_pattern);
const ICON_RECORD_FIELDS = new Set(ICON_REGISTRY_SCHEMA.record_fields);
const ICON_WEIGHTS = new Set(ICON_REGISTRY_SCHEMA.weights);

/**
 * @testable true
 * @tests tests_js/test_018_style_pipeline.py::test_icon_registry_rejects_invalid_ids_and_material_symbol_records
 * @pair style-build:icon-schema-validation
 */
const normalizeIconRegistry = (value, path = "icons") => {
	if (
		!value ||
		typeof value !== "object" ||
		Array.isArray(value) ||
		Object.keys(value).length === 0
	) {
		throw new TypeError(`${path} must be a non-empty mapping`);
	}

	if (Object.hasOwn(value, "glyph")) {
		const unknown = Object.keys(value).filter(
			(key) => !ICON_RECORD_FIELDS.has(key),
		);
		if (unknown.length) {
			throw new TypeError(
				`${path} has unknown icon fields: ${unknown.join(", ")}`,
			);
		}
		if (typeof value.glyph !== "string" || !ICON_GLYPH.test(value.glyph)) {
			throw new TypeError(`${path}.glyph must be a Material Symbol name`);
		}
		if (value.fill !== 0 && value.fill !== 1) {
			throw new TypeError(`${path}.fill must be 0 or 1`);
		}
		if (Object.hasOwn(value, "weight") && !ICON_WEIGHTS.has(value.weight)) {
			throw new TypeError(
				`${path}.weight must be one of ${[...ICON_WEIGHTS].join(", ")}`,
			);
		}
		if (Object.hasOwn(value, "spin") && typeof value.spin !== "boolean") {
			throw new TypeError(`${path}.spin must be a boolean`);
		}
		return { ...value };
	}
	if (Object.keys(value).some((key) => ICON_RECORD_FIELDS.has(key))) {
		throw new TypeError(`${path} must define glyph and fill together`);
	}

	return Object.fromEntries(
		Object.entries(value).map(([key, child]) => {
			if (!ICON_ID_SEGMENT.test(key)) {
				throw new TypeError(`${path} has invalid icon ID segment ${key}`);
			}
			const childPath = `${path}.${key}`;
			return [key, normalizeIconRegistry(child, childPath)];
		}),
	);
};

const iconsYaml = normalizeIconRegistry(rawIconsYaml);

/**
 * @testable true
 * @tests tests_js/test_018_style_pipeline.py::test_virtual_and_python_style_payloads_share_one_runtime_value
 * @tests tests_js/test_018_style_pipeline.py::test_style_registry_rejects_untyped_and_unknown_leaves
 * @pair style-build:runtime-parity
 * @pair style-build:schema-validation
 */
const normalizeStyleRegistry = (value, path = "styles") => {
	const records = new Map();
	/**
	 * @testable false
	 * @covered-by build/utility.mjs::normalizeStyleRegistry
	 * @reason private traversal step
	 */
	const collect = (node, nodePath) => {
		if (!node || typeof node !== "object" || Array.isArray(node)) {
			throw new TypeError(
				`${nodePath} must be a mapping or typed style record`,
			);
		}
		const isRecord =
			Object.hasOwn(node, "classes") || Object.hasOwn(node, "alias");
		if (!isRecord) {
			for (const [key, child] of Object.entries(node)) {
				if (!STYLE_ID_SEGMENT.test(key)) {
					throw new TypeError(
						`${nodePath} has invalid style ID segment ${key}`,
					);
				}
				collect(child, `${nodePath}.${key}`);
			}
			return;
		}
		const unknown = Object.keys(node).filter(
			(key) => !STYLE_RECORD_FIELDS.has(key),
		);
		if (unknown.length) {
			throw new TypeError(
				`${nodePath} has unknown style fields: ${unknown.join(", ")}`,
			);
		}
		if (Object.hasOwn(node, "classes") === Object.hasOwn(node, "alias")) {
			throw new TypeError(
				`${nodePath} must define exactly one of classes or alias`,
			);
		}
		if (Object.hasOwn(node, "classes") && typeof node.classes !== "string") {
			throw new TypeError(`${nodePath}.classes must be a string`);
		}
		if (Object.hasOwn(node, "alias") && typeof node.alias !== "string") {
			throw new TypeError(`${nodePath}.alias must be a semantic style ID`);
		}
		if (Object.hasOwn(node, "alias") && !node.alias.trim()) {
			throw new TypeError(`${nodePath}.alias must be a semantic style ID`);
		}
		if (Object.hasOwn(node, "intent") && typeof node.intent !== "string") {
			throw new TypeError(`${nodePath}.intent must be a string`);
		}
		for (const field of STYLE_REQUIRED_METADATA) {
			if (!Object.hasOwn(node, field)) {
				throw new TypeError(`${nodePath} must define ${field}`);
			}
		}
		if (STYLE_REQUIRED_METADATA.has("intent") && !node.intent.trim()) {
			throw new TypeError(`${nodePath}.intent must not be blank`);
		}
		if (
			Object.hasOwn(node, "surfaces") &&
			(!Array.isArray(node.surfaces) ||
				node.surfaces.some((surface) => !STYLE_SURFACES.has(surface)) ||
				new Set(node.surfaces).size !== node.surfaces.length)
		) {
			throw new TypeError(
				`${nodePath}.surfaces must contain only server/frontend`,
			);
		}
		if (STYLE_REQUIRED_METADATA.has("surfaces") && node.surfaces.length === 0) {
			throw new TypeError(`${nodePath}.surfaces must not be empty`);
		}
		for (const field of ["markers", "hooks", "css"]) {
			if (
				Object.hasOwn(node, field) &&
				(!Array.isArray(node[field]) ||
					node[field].some((item) => typeof item !== "string"))
			) {
				throw new TypeError(`${nodePath}.${field} must be a list of strings`);
			}
			if (
				Array.isArray(node[field]) &&
				new Set(node[field]).size !== node[field].length
			) {
				throw new TypeError(`${nodePath}.${field} must not contain duplicates`);
			}
		}
		if (node.css?.some((path) => path.includes("::"))) {
			throw new TypeError(
				`${nodePath}.css must contain stylesheet paths, not path::hook`,
			);
		}
		if (
			Object.hasOwn(node, "exceptions") &&
			(!Array.isArray(node.exceptions) ||
				node.exceptions.some(
					(item) =>
						!item ||
						typeof item !== "object" ||
						Object.keys(item).length !== STYLE_EXCEPTION_FIELDS.size ||
						Object.keys(item).some(
							(field) => !STYLE_EXCEPTION_FIELDS.has(field),
						) ||
						[...STYLE_EXCEPTION_FIELDS].some(
							(field) => typeof item[field] !== "string",
						) ||
						!item.target.trim() ||
						!item.reason.trim() ||
						!STYLE_EXCEPTION_DIAGNOSTICS.has(item.diagnostic),
				))
		) {
			throw new TypeError(
				`${nodePath}.exceptions must contain valid diagnostic/target/reason records`,
			);
		}
		records.set(nodePath, node);
	};
	collect(value, path);

	const resolved = new Map();
	/**
	 * @testable false
	 * @covered-by build/utility.mjs::normalizeStyleRegistry
	 * @reason private alias-resolution step
	 */
	const resolve = (name, stack = []) => {
		if (resolved.has(name)) return resolved.get(name);
		if (stack.includes(name)) {
			throw new TypeError(
				`style alias cycle: ${[...stack, name].join(" -> ")}`,
			);
		}
		const record = records.get(name);
		if (!record) throw new TypeError(`unknown style alias target: ${name}`);
		const classes = Object.hasOwn(record, "classes")
			? record.classes
			: resolve(`${path}.${record.alias}`, [...stack, name]);
		resolved.set(name, classes);
		return classes;
	};
	for (const [name, record] of records) {
		const classes = resolve(name);
		for (const exception of record.exceptions ?? []) {
			const targetName = `${path}.${exception.target}`;
			if (!records.has(targetName)) {
				throw new TypeError(
					`${name}.exceptions has unknown target ${exception.target}`,
				);
			}
			if (targetName === name) {
				throw new TypeError(`${name}.exceptions cannot target the same style`);
			}
			if (
				exception.diagnostic === "duplicate-style-value" &&
				resolve(targetName) !== classes
			) {
				throw new TypeError(
					`${name}.exceptions targets ${exception.target} with different classes`,
				);
			}
		}
	}
	/**
	 * @testable false
	 * @covered-by build/utility.mjs::normalizeStyleRegistry
	 * @reason private runtime-tree construction step
	 */
	const build = (node, nodePath) => {
		if (records.has(nodePath)) return resolve(nodePath);
		return Object.fromEntries(
			Object.entries(node).map(([key, child]) => [
				key,
				build(child, `${nodePath}.${key}`),
			]),
		);
	};
	return build(value, path);
};

const stylesYaml = normalizeStyleRegistry(rawStylesYaml);

/**
 * @testable true
 * @tests tests_js/test_018_style_pipeline.py::test_virtual_and_python_style_payloads_share_one_runtime_value
 * @pair style-build:runtime-parity
 */
const virtualStyleModuleSource = (styles) => {
	return `const STYLES = ${stringify(styles)};\nexport { STYLES };`;
};

/**
 * @testable true
 * @tests tests_js/test_018_style_pipeline.py::test_virtual_and_python_style_payloads_share_one_runtime_value
 * @pair style-build:runtime-parity
 */
const virtualIconModuleSource = (icons) => {
	return `const ICONS = ${stringify(icons)};\nexport { ICONS };`;
};

/**
 * @testable false
 * @covered-by build/utility.mjs::pythonStyleModuleSource
 * @reason private serializer exercised through generated Python payload parity
 */
const pythonStringify = (value, depth = 0) => {
	if (value === null) return "None";
	if (value === true) return "True";
	if (value === false) return "False";
	if (typeof value === "string") return JSON.stringify(value);
	if (typeof value === "number") return String(value);
	if (Array.isArray(value)) {
		if (value.length === 0) return "[]";
		const indent = "\t".repeat(depth + 1);
		const closingIndent = "\t".repeat(depth);
		return `[\n${value.map((item) => `${indent}${pythonStringify(item, depth + 1)}`).join(",\n")}\n${closingIndent}]`;
	}
	const entries = Object.entries(value);
	if (entries.length === 0) return "{}";
	const indent = "\t".repeat(depth + 1);
	const closingIndent = "\t".repeat(depth);
	return `{\n${entries
		.map(
			([key, child]) =>
				`${indent}${JSON.stringify(key)}: ${pythonStringify(child, depth + 1)}`,
		)
		.join(",\n")}\n${closingIndent}}`;
};

/**
 * @testable true
 * @tests tests_js/test_018_style_pipeline.py::test_virtual_and_python_style_payloads_share_one_runtime_value
 * @pair style-build:runtime-parity
 */
const pythonStyleModuleSource = (name, registry) => {
	const warning = "# This file is auto-generated. Do not edit manually.\n";
	return `${warning}${name} = ${pythonStringify(registry)}\n`;
};

/**
 * @testable true
 * @tests tests_js/test_018_style_pipeline.py::test_style_pipeline_contract_names_authored_inputs_and_outputs
 * @pair style-build:pipeline-contract
 */
const buildStyles = () => {
	const virtualModules = new Map([
		[
			STYLE_PIPELINE.registry.virtual_module,
			virtualStyleModuleSource(stylesYaml),
		],
		[
			STYLE_PIPELINE.registry.icons_virtual_module,
			virtualIconModuleSource(iconsYaml),
		],
	]);
	return {
		name: "build-styles",
		resolveId(source) {
			return virtualModules.has(source) ? source : null;
		},
		load(id) {
			return virtualModules.get(id) ?? null;
		},
		generateBundle() {
			writeFileSync(
				`./${STYLE_PIPELINE.registry.python_icons}`,
				pythonStyleModuleSource("ICONS", iconsYaml),
			);
			writeFileSync(
				`./${STYLE_PIPELINE.registry.python_styles}`,
				pythonStyleModuleSource("STYLES", stylesYaml),
			);
		},
	};
};

/**
 * @testable false
 * @covered-by build/utility.mjs::versionChunkImports
 * @reason private URL mutation is exercised through generated import and precache URLs
 */
const withBuildVersion = (url, buildId) => {
	const hashIndex = url.indexOf("#");
	const base = hashIndex === -1 ? url : url.slice(0, hashIndex);
	const hash = hashIndex === -1 ? "" : url.slice(hashIndex);
	const separator = base.includes("?") ? "&" : "?";
	return `${base}${separator}v=${encodeURIComponent(buildId)}${hash}`;
};

/**
 * @testable false
 * @covered-by build/utility.mjs::versionChunkImports
 * @reason private AST traversal only locates generated module specifier literals
 */
const moduleSourceNodes = (node, sources = []) => {
	if (!node || typeof node !== "object") return sources;
	if (Array.isArray(node)) {
		for (const child of node) moduleSourceNodes(child, sources);
		return sources;
	}

	if (
		(node.type === "ImportDeclaration" ||
			node.type === "ExportNamedDeclaration" ||
			node.type === "ExportAllDeclaration" ||
			node.type === "ImportExpression") &&
		node.source?.type === "Literal" &&
		typeof node.source.value === "string"
	) {
		sources.push(node.source);
	}

	for (const child of Object.values(node)) {
		moduleSourceNodes(child, sources);
	}
	return sources;
};

/**
 * @testable false
 * @covered-by build/utility.mjs::versionChunkImports
 * @reason private path normalization is exercised through Rollup output at multiple directory depths
 */
const resolvedChunkFileName = (importerFileName, specifier) => {
	const bareSpecifier = specifier.split(/[?#]/, 1)[0];
	if (bareSpecifier.startsWith("/")) return bareSpecifier.slice(1);
	if (!bareSpecifier.startsWith(".")) return null;
	return path.normalize(
		path.join(path.dirname(importerFileName), bareSpecifier),
	);
};

/**
 * Adds the build ID to generated inter-chunk imports while leaving emitted
 * filenames stable on disk. Running before minification lets Rollup compose
 * the mutation into production source maps.
 *
 * @testable true
 * @tests tests_js/test_022_build_chunk_versioning.py::test_rollup_versions_generated_chunk_imports_and_precache_urls
 * @tests tests_tooling/test_003_config.py::test_app_engine_chunk_handler_uses_immutable_cache_before_general_js
 * @features frontend-build cache
 * @dimensions chunk-versioning bundle-consistency
 */
const versionChunkImports = (buildId) => ({
	name: "version-chunk-imports",
	renderChunk(code, chunk) {
		const chunkFileNames = new Set([
			...(chunk.imports || []),
			...(chunk.dynamicImports || []),
		]);
		if (chunkFileNames.size === 0) return null;

		const source = new MagicString(code);
		let changed = false;
		for (const node of moduleSourceNodes(this.parse(code))) {
			const importedFileName = resolvedChunkFileName(
				chunk.fileName,
				node.value,
			);
			if (!chunkFileNames.has(importedFileName)) continue;

			const raw = code.slice(node.start, node.end);
			if (!['"', "'"].includes(raw[0]) || raw.at(-1) !== raw[0]) continue;
			source.overwrite(
				node.start + 1,
				node.end - 1,
				withBuildVersion(node.value, buildId),
			);
			changed = true;
		}

		if (!changed) return null;
		return {
			code: source.toString(),
			map: source.generateMap({ hires: true }),
		};
	},
});

/**
 * @testable false
 * @covered-by build/utility.mjs::versionChunkImports
 * @reason precache URLs share the tested chunk-versioning contract
 */
const precacheUrls = (bundle, buildId) => {
	return Object.values(bundle)
		.filter(
			(item) =>
				item.type === "chunk" &&
				item.fileName.startsWith("chunks/") &&
				item.fileName.endsWith(".js"),
		)
		.map((item) => withBuildVersion(`/${item.fileName}`, buildId))
		.sort();
};

/** @testable infrastructure */
const generateBuildId = () => `b${randomBytes(4).toString("hex").slice(1)}`;

/** @testable infrastructure */
const updateConstantsBuildId = (buildId) => {
	let content = readFileSync(constantsPath, "utf8");
	const line = `BUILD_ID = "${buildId}"`;
	if (/^BUILD_ID\s*=.*$/m.test(content)) {
		content = content.replace(/^BUILD_ID\s*=.*$/m, line);
	} else if (/^SENTRY_DSN = .*$/m.test(content)) {
		content = content.replace(/^SENTRY_DSN = .*$/m, (match) => {
			return `${match}\n${line}`;
		});
	} else {
		content = `${content.replace(/\s*$/, "\n")}${line}\n`;
	}
	writeFileSync(constantsPath, content);
};

/**
 * @testable false
 * @covered-by build/utility.mjs::updateServiceWorker
 * @reason private metadata serializer exercised through service-worker output
 */
const writeBuildMetadata = (buildId, version, mode) => {
	writeFileSync(
		buildMetadataPath,
		`${JSON.stringify({ build_id: buildId, mode, version }, null, 2)}\n`,
	);
};

/**
 * @testable true
 * @tests tests_js/test_022_build_chunk_versioning.py::test_build_metadata_records_release_mode
 * @features frontend-build
 * @dimensions build-metadata
 */
const updateServiceWorker = (buildId, version, mode) => {
	return {
		name: "update-service-worker",
		writeBundle(_options, bundle) {
			let swContent = readFileSync("./src/script/sw.template.mjs", "utf8");
			const browserProtocol = JSON.parse(
				readFileSync(browserProtocolPath, "utf8"),
			);

			swContent = swContent.replaceAll("__BUILD_ID__", buildId);
			swContent = swContent.replace(
				"/* __BROWSER_PROTOCOL__ */ null",
				JSON.stringify(browserProtocol, null, "\t"),
			);
			swContent = swContent.replace(
				"/* __PRECACHE_URLS__ */ []",
				JSON.stringify(precacheUrls(bundle, buildId), null, "\t"),
			);

			writeBuildMetadata(buildId, version, mode);
			writeFileSync("./lagniappe/web/static/sw.js", swContent);
		},
	};
};

/** @testable infrastructure */
const emitPdfWorker = () => {
	return {
		name: "emit-pdf-worker",
		generateBundle() {
			this.emitFile({
				type: "asset",
				fileName: "pdf.worker.min.mjs",
				source: readFileSync(
					"./node_modules/pdfjs-dist/build/pdf.worker.min.mjs",
				),
			});
			for (const fileName of readdirSync("./node_modules/pdfjs-dist/wasm")) {
				if (!fileName.endsWith(".js") && !fileName.endsWith(".wasm")) continue;
				this.emitFile({
					type: "asset",
					fileName: `pdfjs/wasm/${fileName}`,
					source: readFileSync(`./node_modules/pdfjs-dist/wasm/${fileName}`),
				});
			}
		},
	};
};

/**
 * Emits the repository's third-party notices beside the browser bundles so
 * downloaded minified code and copied assets have an accompanying license
 * document.
 *
 * @testable true
 * @tests tests_js/test_022_build_chunk_versioning.py::test_third_party_notices_are_emitted_with_browser_assets
 * @features frontend-build licensing
 * @dimensions browser-notice-delivery
 */
const emitThirdPartyLicenses = () => {
	return {
		name: "emit-third-party-licenses",
		generateBundle() {
			const directory = "./THIRD_PARTY_LICENSES";
			const source = readdirSync(directory)
				.sort()
				.map((fileName) => {
					const content = readFileSync(path.join(directory, fileName), "utf8");
					return `===== ${fileName} =====\n\n${content.trimEnd()}`;
				})
				.join("\n\n");
			this.emitFile({
				type: "asset",
				fileName: "third-party-licenses.txt",
				source: `${source}\n`,
			});
		},
	};
};

const materialSymbolsFontPath = "./src/fonts/material-symbols-rounded.woff2";
const materialSymbolsFontSource = readFileSync(materialSymbolsFontPath);
const materialSymbolsFontHash = createHash("sha256")
	.update(materialSymbolsFontSource)
	.digest("hex")
	.slice(0, 12);
const materialSymbolsFontFileName = `fonts/material-symbols-rounded.${materialSymbolsFontHash}.woff2`;

/**
 * Rewrites the authored stable Material Symbols font URL to the content-hashed
 * asset emitted by Rollup.
 *
 * @testable true
 * @tests tests_js/test_022_build_chunk_versioning.py::test_material_symbols_css_points_to_the_content_hashed_font
 * @features frontend-build icons
 * @dimensions font-delivery css-url-resolution
 */
const resolveMaterialSymbolsFont = () => ({
	postcssPlugin: "resolve-material-symbols-font",
	Declaration(declaration) {
		if (!declaration.value.includes("material-symbols-rounded.woff2")) return;
		declaration.value = declaration.value.replace(
			"/fonts/material-symbols-rounded.woff2",
			`/${materialSymbolsFontFileName}`,
		);
	},
});

/**
 * Emits the vendored, officially subsetted Material Symbols font with a
 * content-derived filename so adding glyphs cannot reuse an older cached font,
 * then removes stale generated variants from the output font directory.
 *
 * @testable true
 * @tests tests_js/test_022_build_chunk_versioning.py::test_material_symbols_subset_font_is_emitted_with_content_hash
 * @features frontend-build icons
 * @dimensions font-delivery subset cache stale-cleanup
 */
const emitMaterialSymbols = () => {
	return {
		name: "emit-material-symbols",
		generateBundle() {
			this.emitFile({
				type: "asset",
				fileName: materialSymbolsFontFileName,
				source: materialSymbolsFontSource,
			});
		},
		writeBundle(outputOptions) {
			if (!outputOptions.dir) return;
			const fontsDirectory = path.join(outputOptions.dir, "fonts");
			if (!existsSync(fontsDirectory)) return;

			for (const fileName of readdirSync(fontsDirectory)) {
				if (
					/^material-symbols-rounded(?:-[a-z0-9-]+)?(?:\.[a-f0-9]{12})?\.woff2$/.test(
						fileName,
					) &&
					fileName !== path.basename(materialSymbolsFontFileName)
				) {
					unlinkSync(path.join(fontsDirectory, fileName));
				}
			}
		},
	};
};

export {
	buildStyles,
	emitMaterialSymbols,
	emitPdfWorker,
	emitThirdPartyLicenses,
	generateBuildId,
	interactionFoundationChunk,
	normalizeIconRegistry,
	normalizeStyleRegistry,
	precacheUrls,
	pythonStyleModuleSource,
	resolveMaterialSymbolsFont,
	STYLE_PIPELINE,
	updateConstantsBuildId,
	updateServiceWorker,
	versionChunkImports,
	virtualIconModuleSource,
	virtualStyleModuleSource,
};
