import { createHash } from "node:crypto";
import {
	existsSync,
	mkdirSync,
	readdirSync,
	readFileSync,
	renameSync,
	rmSync,
	statSync,
	writeFileSync,
} from "node:fs";
import { dirname, isAbsolute, join, posix, relative, resolve } from "node:path";

const CONTRACT_PATH = "build/publication.json";
const BUILD_METADATA_PATH = "lagniappe/web/static/build.json";
const ARTIFACT_INVENTORY_PATH =
	process.env.LAGNIAPPE_FRONTEND_ARTIFACT_INVENTORY;
const recordedArtifacts = new Set();

/**
 * @testable false
 * @covered-by build/publication.mjs::publishFrontendBuild
 * @reason private repository path adapter exercised through publication
 */
const repositoryPath = (root, pathValue) => resolve(root, pathValue);

/**
 * @testable false
 * @covered-by build/publication.mjs::recordBuildArtifacts
 * @reason private path normalizer exercised through emitted inventories
 */
const repositoryRelativePath = (root, pathValue) =>
	relative(root, resolve(root, pathValue)).split("\\").join("/");

/**
 * @testable false
 * @covered-by build/publication.mjs::publishFrontendBuild
 * @reason private path guard exercised through publication failure tests
 */
const safeRelativePath = (pathValue) => {
	if (
		typeof pathValue !== "string" ||
		!pathValue ||
		isAbsolute(pathValue) ||
		pathValue.includes("\\")
	) {
		throw new Error(`Unsafe frontend publication path: ${pathValue}`);
	}
	const normalized = posix.normalize(pathValue);
	if (
		normalized !== pathValue ||
		normalized === ".." ||
		normalized.startsWith("../")
	) {
		throw new Error(`Unsafe frontend publication path: ${pathValue}`);
	}
	return normalized;
};

/**
 * @testable false
 * @covered-by build/publication.mjs::publishFrontendBuild
 * @reason private durability helper exercised through completion-marker tests
 */
const atomicWrite = (pathValue, content) => {
	mkdirSync(dirname(pathValue), { recursive: true });
	const temporary = `${pathValue}.tmp-${process.pid}`;
	try {
		writeFileSync(temporary, content);
		renameSync(temporary, pathValue);
	} finally {
		rmSync(temporary, { force: true });
	}
};

/**
 * @testable false
 * @covered-by build/publication.mjs::frontendSourceIdentity
 * @reason private contract loader exercised through source identity tests
 */
const publicationContract = (root = process.cwd()) => {
	const value = JSON.parse(
		readFileSync(repositoryPath(root, CONTRACT_PATH), "utf8"),
	);
	if (value.schema !== 1) {
		throw new Error("Unsupported frontend publication contract schema.");
	}
	return value;
};

/**
 * @testable false
 * @covered-by build/publication.mjs::publishFrontendBuild
 * @reason shared contract projection used by build cleanup and publication validation
 */
const exclusiveArtifactRoots = (root = process.cwd()) =>
	publicationContract(root).exclusive_artifact_roots.map((pathValue) =>
		repositoryPath(root, safeRelativePath(pathValue)),
	);

/**
 * @testable false
 * @covered-by build/publication.mjs::frontendSourceIdentity
 * @reason private recursive enumerator exercised through source identity tests
 */
const filesUnder = (root, relativeRoot) => {
	const directory = repositoryPath(root, relativeRoot);
	if (!existsSync(directory) || !statSync(directory).isDirectory()) return [];
	const files = [];
	/**
	 * @testable false
	 * @covered-by build/publication.mjs::filesUnder
	 * @reason private recursive step owned by the directory enumerator
	 */
	const visit = (current) => {
		for (const entry of readdirSync(current, { withFileTypes: true })) {
			const pathValue = join(current, entry.name);
			if (entry.isDirectory()) visit(pathValue);
			else if (entry.isFile())
				files.push(repositoryRelativePath(root, pathValue));
		}
	};
	visit(directory);
	return files;
};

/**
 * Hash the complete portable source surface used by frontend publication.
 *
 * @testable true
 * @tests tests_js/test_022_build_chunk_versioning.py::test_frontend_publication_records_recursive_artifacts_and_source_identity
 * @features frontend-build
 * @dimensions source-integrity
 */
const frontendSourceIdentity = (root = process.cwd()) => {
	const contract = publicationContract(root);
	const paths = new Set();
	for (const relativeRoot of contract.source_roots) {
		for (const pathValue of filesUnder(root, safeRelativePath(relativeRoot))) {
			paths.add(pathValue);
		}
	}
	for (const pathValue of contract.source_files) {
		const normalized = safeRelativePath(pathValue);
		if (!existsSync(repositoryPath(root, normalized))) {
			throw new Error(`Frontend source input is missing: ${normalized}`);
		}
		paths.add(normalized);
	}

	const digest = createHash("sha256");
	digest.update(`frontend-source-v${contract.schema}\0`);
	for (const pathValue of [...paths].sort()) {
		digest.update(pathValue);
		digest.update("\0");
		digest.update(readFileSync(repositoryPath(root, pathValue)));
		digest.update("\0");
	}
	return digest.digest("hex");
};

/**
 * @testable false
 * @covered-by build/publication.mjs::recordBuildArtifacts
 * @reason private Rollup output adapter exercised through inventory tests
 */
const outputArtifactPath = (outputOptions, fileName) => {
	if (outputOptions.dir) return join(outputOptions.dir, fileName);
	if (outputOptions.file) return join(dirname(outputOptions.file), fileName);
	throw new Error("Frontend Rollup output has no file or directory.");
};

/**
 * Collect every emitted Rollup output across the sequential bundle cohort.
 *
 * @testable true
 * @tests tests_js/test_022_build_chunk_versioning.py::test_frontend_publication_records_recursive_artifacts_and_source_identity
 * @features frontend-build
 * @dimensions artifact-inventory nested-chunks
 */
const recordBuildArtifacts = ({
	final = false,
	buildId = null,
	mode = null,
	version = null,
	extraArtifacts = [],
} = {}) => ({
	name: final ? "record-final-build-artifacts" : "record-build-artifacts",
	generateBundle(outputOptions, bundle) {
		for (const item of Object.values(bundle)) {
			if (item.fileName.endsWith(".map")) continue;
			recordedArtifacts.add(
				repositoryRelativePath(
					process.cwd(),
					outputArtifactPath(outputOptions, item.fileName),
				),
			);
		}
	},
	writeBundle() {
		if (!final || !ARTIFACT_INVENTORY_PATH) return;
		for (const pathValue of extraArtifacts) {
			recordedArtifacts.add(safeRelativePath(pathValue));
		}
		atomicWrite(
			ARTIFACT_INVENTORY_PATH,
			`${JSON.stringify(
				{
					artifacts: [...recordedArtifacts].sort(),
					build_id: buildId,
					mode,
					version,
				},
				null,
				2,
			)}\n`,
		);
	},
});

/**
 * @testable false
 * @covered-by build/publication.mjs::publishFrontendBuild
 * @reason private digest serializer exercised through completion-marker tests
 */
const artifactRecord = (root, pathValue) => {
	const content = readFileSync(repositoryPath(root, pathValue));
	return {
		path: pathValue,
		sha256: createHash("sha256").update(content).digest("hex"),
		size: content.length,
	};
};

/**
 * Commit build metadata only after Rollup and every external build hook pass.
 *
 * @testable true
 * @tests tests_js/test_022_build_chunk_versioning.py::test_frontend_publication_records_recursive_artifacts_and_source_identity
 * @tests tests_js/test_022_build_chunk_versioning.py::test_frontend_publication_rejects_missing_outputs_and_source_drift
 * @features frontend-build
 * @dimensions completion-marker artifact-integrity source-integrity safe-failure
 */
const publishFrontendBuild = ({
	root = process.cwd(),
	buildId,
	mode,
	version,
	artifacts,
	sourceIdentity,
	beforePublish = null,
}) => {
	if (frontendSourceIdentity(root) !== sourceIdentity) {
		throw new Error(
			"Frontend sources changed while the build was running; rebuild.",
		);
	}

	const contract = publicationContract(root);
	const artifactPaths = [...new Set(artifacts.map(safeRelativePath))].sort();
	for (const required of contract.required_artifacts) {
		if (!artifactPaths.includes(required)) {
			throw new Error(
				`Frontend build did not emit required artifact: ${required}`,
			);
		}
	}
	for (const prefix of contract.required_artifact_prefixes) {
		if (!artifactPaths.some((pathValue) => pathValue.startsWith(prefix))) {
			throw new Error(
				`Frontend build did not emit an artifact under: ${prefix}`,
			);
		}
	}
	for (const pathValue of artifactPaths) {
		if (pathValue.endsWith(".map") || pathValue === BUILD_METADATA_PATH) {
			throw new Error(
				`Unsupported frontend artifact inventory path: ${pathValue}`,
			);
		}
		if (!existsSync(repositoryPath(root, pathValue))) {
			throw new Error(`Frontend build artifact is missing: ${pathValue}`);
		}
	}
	const exclusivePaths = new Set();
	for (const exclusiveRoot of contract.exclusive_artifact_roots) {
		for (const pathValue of filesUnder(root, safeRelativePath(exclusiveRoot))) {
			exclusivePaths.add(pathValue);
		}
	}
	for (const pathValue of exclusivePaths) {
		if (!artifactPaths.includes(pathValue)) {
			throw new Error(
				`Frontend build output is not in the artifact inventory: ${pathValue}`,
			);
		}
	}

	const metadata = {
		schema: 1,
		build_id: buildId,
		mode,
		version,
		source: { sha256: sourceIdentity },
		artifacts: artifactPaths.map((pathValue) =>
			artifactRecord(root, pathValue),
		),
	};
	if (beforePublish) beforePublish();
	atomicWrite(
		repositoryPath(root, BUILD_METADATA_PATH),
		`${JSON.stringify(metadata, null, 2)}\n`,
	);
	return metadata;
};

export {
	BUILD_METADATA_PATH,
	exclusiveArtifactRoots,
	frontendSourceIdentity,
	publicationContract,
	publishFrontendBuild,
	recordBuildArtifacts,
};
