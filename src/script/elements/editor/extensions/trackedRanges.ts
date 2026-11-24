import { Extension } from "@tiptap/core";

const TRACKED_RANGE_META = "trackedRanges";

const normalizedRange = (range, docEnd) => {
	if (!range) return null;
	const from = Math.max(0, Math.min(Number(range.from), docEnd));
	const to = Math.max(0, Math.min(Number(range.to), docEnd));
	if (!Number.isInteger(from) || !Number.isInteger(to) || from >= to) {
		return null;
	}
	return { from, to };
};

const addOperation = (transaction, operation) => {
	const meta = transaction.getMeta(TRACKED_RANGE_META) || { operations: [] };
	transaction.setMeta(TRACKED_RANGE_META, {
		operations: [...meta.operations, operation],
	});
	return transaction;
};

/**
 * Associate a named range with the document produced by a transaction.
 *
 */
export const setTrackedRangeInTransaction = (transaction, key, range) =>
	addOperation(transaction, { type: "set", key, range });

/**
 * Keep independently named document ranges current across local, remote, and
 * appended ProseMirror transactions.
 *
 */
export const TrackedRanges = Extension.create({
	name: "trackedRanges",

	addStorage() {
		return { ranges: new Map() };
	},

	addCommands() {
		return {
			setTrackedRange:
				(key, range) =>
				({ state, tr, dispatch }) => {
					const normalized = normalizedRange(range, state.doc.content.size);
					if (typeof key !== "string" || !key || !normalized) return false;
					if (dispatch)
						dispatch(addOperation(tr, { type: "set", key, range: normalized }));
					return true;
				},
			getTrackedRange:
				(key) =>
				({ editor }) => {
					const range = editor.storage.trackedRanges.ranges.get(key);
					return range ? { ...range } : null;
				},
			clearTrackedRange:
				(key) =>
				({ tr, dispatch }) => {
					if (typeof key !== "string" || !key) return false;
					if (dispatch) dispatch(addOperation(tr, { type: "clear", key }));
					return true;
				},
			clearTrackedRanges:
				() =>
				({ tr, dispatch }) => {
					if (dispatch) dispatch(addOperation(tr, { type: "clearAll" }));
					return true;
				},
		};
	},

	onTransaction({ transaction, appendedTransactions = [] }) {
		const ranges = this.storage.ranges;

		for (const tr of [transaction, ...appendedTransactions]) {
			if (tr.docChanged) {
				for (const [key, range] of ranges) {
					const mapped = normalizedRange(
						{
							from: tr.mapping.map(range.from, 1),
							to: tr.mapping.map(range.to, -1),
						},
						tr.doc.content.size,
					);
					if (mapped) ranges.set(key, mapped);
					else ranges.delete(key);
				}
			}

			const meta = tr.getMeta(TRACKED_RANGE_META);
			for (const operation of meta?.operations || []) {
				if (operation.type === "clearAll") {
					ranges.clear();
				} else if (operation.type === "clear") {
					ranges.delete(operation.key);
				} else if (operation.type === "set") {
					const range = normalizedRange(operation.range, tr.doc.content.size);
					if (typeof operation.key === "string" && operation.key && range) {
						ranges.set(operation.key, range);
					}
				}
			}
		}
	},
});
