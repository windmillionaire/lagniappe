import { __unstable__loadDesignSystem } from "@tailwindcss/node";
import { readFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { pathToFileURL } from "node:url";

/**
 * Validate utility candidates against the same Tailwind design system loaded by
 * the authored CSS entry. Marker and custom-hook exclusions are supplied by the
 * registry inventory rather than being guessed here.
 */
export async function validateStyleCandidates({
	cssEntry,
	candidates,
	ignored = [],
	repoRoot = process.cwd(),
}) {
	const cssPath = resolve(repoRoot, cssEntry);
	const css = await readFile(cssPath, "utf8");
	const designSystem = await __unstable__loadDesignSystem(css, {
		base: dirname(cssPath),
	});
	const ignoredCandidates = new Set(ignored);
	const uniqueCandidates = [...new Set(candidates)].sort();
	return {
		checked: uniqueCandidates.length,
		ignored: uniqueCandidates.filter((candidate) =>
			ignoredCandidates.has(candidate),
		),
		invalid: uniqueCandidates.filter(
			(candidate) =>
				!ignoredCandidates.has(candidate) &&
				designSystem.parseCandidate(candidate).length === 0,
		),
	};
}

async function readStandardInput() {
	let value = "";
	for await (const chunk of process.stdin) value += chunk;
	return value;
}

if (
	process.argv[1] &&
	import.meta.url === pathToFileURL(resolve(process.argv[1])).href
) {
	const request = JSON.parse(await readStandardInput());
	process.stdout.write(
		`${JSON.stringify(await validateStyleCandidates(request))}\n`,
	);
}
