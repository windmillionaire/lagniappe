import { spawnSync } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import {
	BUILD_METADATA_PATH,
	exclusiveArtifactRoots,
	frontendSourceIdentity,
	publishFrontendBuild,
} from "./publication.mjs";
import { generateBuildId, updateConstantsBuildId } from "./utility.mjs";

const modes = {
	development: "rollup.dev.config.mjs",
	production: "rollup.config.mjs",
};
const mode = process.argv[2];
const configName = modes[mode];

if (!configName) {
	console.error("Usage: node build/run-rollup.mjs development|production");
	process.exitCode = 2;
} else {
	const repositoryRoot = fileURLToPath(new URL("../", import.meta.url));
	const rollupCli = fileURLToPath(
		new URL("../node_modules/rollup/dist/bin/rollup", import.meta.url),
	);
	const configPath = fileURLToPath(new URL(configName, import.meta.url));
	const metadataPath = fileURLToPath(
		new URL(`../${BUILD_METADATA_PATH}`, import.meta.url),
	);
	const temporaryDirectory = mkdtempSync(join(tmpdir(), "lagniappe-frontend-"));
	const artifactInventoryPath = join(temporaryDirectory, "artifacts.json");
	const buildId = generateBuildId();
	const sourceIdentity = frontendSourceIdentity(repositoryRoot);

	try {
		rmSync(metadataPath, { force: true });
		for (const artifactRoot of exclusiveArtifactRoots(repositoryRoot)) {
			rmSync(artifactRoot, { recursive: true, force: true });
		}
		const result = spawnSync(
			process.execPath,
			[rollupCli, "--config", configPath],
			{
				cwd: repositoryRoot,
				env: {
					...process.env,
					LAGNIAPPE_FRONTEND_ARTIFACT_INVENTORY: artifactInventoryPath,
					LAGNIAPPE_FRONTEND_BUILD_ID: buildId,
					NODE_ENV: mode,
				},
				stdio: "inherit",
			},
		);

		if (result.error) throw result.error;
		if (result.status !== 0) {
			process.exitCode = result.status ?? 1;
		} else {
			const inventory = JSON.parse(readFileSync(artifactInventoryPath, "utf8"));
			if (inventory.build_id !== buildId || inventory.mode !== mode) {
				throw new Error(
					"Rollup returned inconsistent frontend build metadata.",
				);
			}
			publishFrontendBuild({
				root: repositoryRoot,
				buildId,
				mode,
				version: inventory.version,
				artifacts: inventory.artifacts,
				sourceIdentity,
				beforePublish: () => updateConstantsBuildId(buildId),
			});
		}
	} finally {
		rmSync(temporaryDirectory, { recursive: true, force: true });
	}
}
