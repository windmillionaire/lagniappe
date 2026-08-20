import { Decoration, Extension } from "@tiptap/core";

const FLASH_FADE_DURATION_MS = 1000;

/**
 * @testable false
 * @covered-by src/script/elements/editor/extensions/remote.mjs::FlashRemoteChanges
 * @reason text-position mapping is private remote-flash extension plumbing
 */
const buildTextPosMap = (doc) => {
	const map = [];
	let currentTextPos = 0;

	doc.descendants((node, pos) => {
		if (node.isText) {
			for (let i = 0; i < node.text.length; i++) {
				map[currentTextPos++] = pos + i;
			}
		} else if (node.isBlock && currentTextPos > 0) {
			// Account for newline in textBetween for block boundaries.
			map[currentTextPos++] = pos;
		}
	});

	return map;
};

/**
 * @testable false
 * @covered-by src/script/elements/editor/extensions/remote.mjs::FlashRemoteChanges
 * @reason transaction mapping is exercised through the remote-flash lifecycle
 */
const mapFlashes = (flashes, transaction) => {
	if (!transaction.docChanged || flashes.length === 0) return flashes;

	return flashes.flatMap((flash) => {
		const from = transaction.mapping.map(flash.from, 1);
		const to = transaction.mapping.map(flash.to, -1);
		return from < to ? [{ ...flash, from, to }] : [];
	});
};

/**
 * @testable false
 * @covered-by src/script/elements/editor/extensions/remote.mjs::FlashRemoteChanges
 * @reason remote step diffing is exercised through the public extension lifecycle
 */
const remoteTransactionFlashes = (transaction, userColor, author) => {
	const flashes = [];
	let docBeforeStep = transaction.before;
	let prevText = docBeforeStep.textBetween(
		0,
		docBeforeStep.content.size,
		"\n",
		"\n",
	);

	for (let i = 0; i < transaction.steps.length; i++) {
		const step = transaction.steps[i];
		const map = transaction.mapping.maps[i];
		const applyResult = step?.apply?.(docBeforeStep);
		const docAfterStep = applyResult?.doc || docBeforeStep;

		if (!map) {
			docBeforeStep = docAfterStep;
			continue;
		}

		const newText = docAfterStep.textBetween(
			0,
			docAfterStep.content.size,
			"\n",
			"\n",
		);

		if (prevText === newText) {
			docBeforeStep = docAfterStep;
			continue;
		}

		let prefix = 0;
		const minLen = Math.min(prevText.length, newText.length);
		while (
			prefix < minLen &&
			prevText.charCodeAt(prefix) === newText.charCodeAt(prefix)
		) {
			prefix++;
		}

		let suffix = 0;
		const maxSuffix = Math.min(
			prevText.length - prefix,
			newText.length - prefix,
		);
		while (
			suffix < maxSuffix &&
			prevText.charCodeAt(prevText.length - 1 - suffix) ===
				newText.charCodeAt(newText.length - 1 - suffix)
		) {
			suffix++;
		}

		const changeStartText = prefix;
		const changeEndText = newText.length - suffix;

		if (changeEndText > changeStartText) {
			const afterMap = transaction.mapping.slice(i + 1);
			const stepTextPosMap = buildTextPosMap(docAfterStep);
			const changeStart = stepTextPosMap[changeStartText] ?? 0;
			const finalTextPos = stepTextPosMap[changeEndText - 1];
			const changeEnd =
				finalTextPos === undefined
					? docAfterStep.content.size
					: finalTextPos + 1;

			const highlightFrom = afterMap.map(changeStart, 1);
			const highlightTo = afterMap.map(changeEnd, -1);

			if (highlightTo > highlightFrom) {
				const decorationId = `flash-${Date.now()}-${Math.random()}`;
				let authorLabelAssigned = false;

				transaction.doc.nodesBetween(
					highlightFrom,
					highlightTo,
					(node, pos) => {
						if (!node.isText) return true;
						const from = Math.max(highlightFrom, pos);
						const to = Math.min(highlightTo, pos + node.nodeSize);
						if (to > from) {
							const attributes = {
								style: `color: ${userColor}; --remote-change-color: ${userColor};`,
								class: "remote-change-flash",
								"data-decoration-id": decorationId,
							};
							if (author) {
								attributes.title = `Edited by ${author}`;
								if (!authorLabelAssigned) {
									attributes["data-editor-author"] = author;
									authorLabelAssigned = true;
								}
							}
							flashes.push({
								id: decorationId,
								from,
								to,
								attributes,
							});
						}
						return true;
					},
				);
			}
		}

		prevText = newText;
		docBeforeStep = docAfterStep;
	}

	return flashes;
};

/**
 * @testable true
 * @tests tests_js/test_041_editor_decorations.py::test_remote_change_flash_decorations_map_and_expire
 * @tests tests_e2e/010_sync/test_010a_document_sync.py::test_two_users_see_document_edits_without_reload
 * @pair editor:remote-highlight
 */
export const FlashRemoteChanges = Extension.create({
	name: "flashRemoteChanges",

	addStorage() {
		return {
			color: "",
			author: "",
			flashes: [],
			timeouts: new Map(),
		};
	},

	addDecorations() {
		const storage = this.storage;

		return {
			update: "manual",
			create: () =>
				storage.flashes.map(({ from, to, attributes }) =>
					Decoration.Inline(from, to, attributes),
				),
		};
	},

	onTransaction({ editor, transaction, appendedTransactions }) {
		const storage = this.storage;
		const transactions = [transaction, ...appendedTransactions];
		let addedFlashes = false;

		for (const tr of transactions) {
			storage.flashes = mapFlashes(storage.flashes, tr);
			if (!tr.getMeta("y-sync$") || !storage.color) continue;

			const newFlashes = remoteTransactionFlashes(
				tr,
				storage.color,
				storage.author,
			);
			if (newFlashes.length === 0) continue;

			storage.flashes.push(...newFlashes);
			addedFlashes = true;
			for (const decorationId of new Set(newFlashes.map(({ id }) => id))) {
				const timeout = setTimeout(() => {
					storage.timeouts.delete(decorationId);
					const remaining = storage.flashes.filter(
						({ id }) => id !== decorationId,
					);
					if (remaining.length === storage.flashes.length) return;

					storage.flashes = remaining;
					if (!editor.isDestroyed) {
						editor.commands.updateDecorations("flashRemoteChanges");
					}
				}, FLASH_FADE_DURATION_MS + 50);
				storage.timeouts.set(decorationId, timeout);
			}
		}

		if (addedFlashes) {
			editor.commands.updateDecorations("flashRemoteChanges");
		}
	},

	onDestroy() {
		for (const timeout of this.storage.timeouts.values()) {
			clearTimeout(timeout);
		}
		this.storage.timeouts.clear();
	},
});
