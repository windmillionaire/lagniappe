import { spawnSync } from "node:child_process";
import { rmSync } from "node:fs";
import { fileURLToPath } from "node:url";

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
	const chunksDirectory = fileURLToPath(
		new URL("../lagniappe/web/static/chunks/", import.meta.url),
	);
	const rollupCli = fileURLToPath(
		new URL("../node_modules/rollup/dist/bin/rollup", import.meta.url),
	);
	const configPath = fileURLToPath(new URL(configName, import.meta.url));

	rmSync(chunksDirectory, { recursive: true, force: true });
	const result = spawnSync(
		process.execPath,
		[rollupCli, "--config", configPath],
		{
			cwd: repositoryRoot,
			env: {
				...process.env,
				NODE_ENV: mode,
			},
			stdio: "inherit",
		},
	);

	if (result.error) {
		throw result.error;
	}
	process.exitCode = result.status ?? 1;
}
