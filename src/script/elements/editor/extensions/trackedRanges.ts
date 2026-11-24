import {
	type Command,
	type CommandProps,
	Extension,
	type Range,
} from "@tiptap/core";
import type { Transaction } from "@tiptap/pm/state";

interface TrackedRangesStorage {
	ranges: Map<string, Range>;
}

type RangeOperation =
	| { type: "set"; key: string; range: Range }
	| { type: "clear"; key: string }
	| { type: "clearAll" };

// These read commands return their callback's value when invoked directly.
export type RangeCommand<Result> = Result extends Command
	? (props: CommandProps) => Range | null
	: Result extends boolean
		? Range | null
		: Result;

declare module "@tiptap/core" {
	interface Commands<ReturnType> {
		trackedRanges: {
			setTrackedRange: (key: string, range: Range) => ReturnType;
			getTrackedRange: (key: string) => RangeCommand<ReturnType>;
			clearTrackedRange: (key: string) => ReturnType;
			clearTrackedRanges: () => ReturnType;
		};
	}
	interface Storage {
		trackedRanges: TrackedRangesStorage;
	}
}

const TRACKED_RANGE_META = "trackedRanges";

const normalizedRange = (range: Range | null | undefined, docEnd: number) => {
	if (!range) return null;
	const from = Math.max(0, Math.min(Number(range.from), docEnd));
	const to = Math.max(0, Math.min(Number(range.to), docEnd));
	if (!Number.isInteger(from) || !Number.isInteger(to) || from >= to) {
		return null;
	}
	return { from, to };
};

const addOperation = (transaction: Transaction, operation: RangeOperation) => {
	const meta: { operations: RangeOperation[] } = transaction.getMeta(
		TRACKED_RANGE_META,
	) || { operations: [] };
	transaction.setMeta(TRACKED_RANGE_META, {
		operations: [...meta.operations, operation],
	});
	return transaction;
};

/**
 * Associate a named range with the document produced by a transaction.
 *
 */
export const setTrackedRangeInTransaction = (
	transaction: Transaction,
	key: string,
	range: Range,
) => addOperation(transaction, { type: "set", key, range });

/**
 * Keep independently named document ranges current across local, remote, and
 * appended ProseMirror transactions.
 *
 */
export const TrackedRanges = Extension.create<
	Record<never, never>,
	TrackedRangesStorage
>({
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

			const meta: { operations: RangeOperation[] } | undefined =
				tr.getMeta(TRACKED_RANGE_META);
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
