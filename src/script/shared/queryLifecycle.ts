export type QueryToken<Key> = {
	epoch: number;
	key: Key;
	signal: AbortSignal | undefined;
};

type QueryOptions = { cancelTransport?: boolean };
type RunOptions = QueryOptions & { getCurrentKey?: () => unknown };

/**
 * Coordinate an asynchronous read with the UI state that requested it.
 * Epoch checks remain authoritative even when AbortController is unavailable
 * or a transport cannot be cancelled.
 */
export class QueryLifecycle {
	declare epoch: number;
	declare controller: AbortController | null;
	declare destroyed: boolean;

	constructor() {
		this.epoch = 0;
		this.controller = null;
		this.destroyed = false;
	}

	begin<Key>(
		key: Key,
		{ cancelTransport = true }: QueryOptions = {},
	): QueryToken<Key> | null {
		if (this.destroyed) return null;

		this.invalidate();
		if (this.destroyed) return null;

		if (cancelTransport && typeof AbortController !== "undefined") {
			this.controller = new AbortController();
		}
		return {
			epoch: this.epoch,
			key,
			signal: this.controller?.signal,
		};
	}

	isCurrent(
		token: QueryToken<unknown> | null | undefined,
		currentKey: unknown = token?.key,
	) {
		return Boolean(
			token &&
				!this.destroyed &&
				token.epoch === this.epoch &&
				token.key === currentKey,
		);
	}

	invalidate() {
		this.epoch += 1;
		this.controller?.abort();
		this.controller = null;
	}

	destroy() {
		if (this.destroyed) return;
		this.destroyed = true;
		this.invalidate();
	}

	async run<Key, Result>(
		key: Key,
		loader: (token: QueryToken<Key>) => Result | PromiseLike<Result>,
		publisher: (result: Result, token: QueryToken<Key>) => unknown,
		{ getCurrentKey = () => key, cancelTransport = true }: RunOptions = {},
	): Promise<boolean> {
		const token = this.begin(key, { cancelTransport });
		if (!token) return false;

		try {
			const result = await loader(token);
			if (!this.isCurrent(token, getCurrentKey())) return false;
			await publisher(result, token);
			return this.isCurrent(token, getCurrentKey());
		} catch (error) {
			const failure = error as { name?: unknown } | null | undefined;
			if (
				failure?.name === "AbortError" &&
				!this.isCurrent(token, getCurrentKey())
			) {
				return false;
			}
			throw error;
		}
	}
}
