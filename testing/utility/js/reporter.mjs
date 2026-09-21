import { inspect } from "node:util";

// Console messages are event payloads, never lines in the reporter protocol.
export default async function* reporter(events) {
	for await (const event of events) {
		const { type, data } = event;
		if (
			![
				"test:pass",
				"test:fail",
				"test:stdout",
				"test:stderr",
				"test:diagnostic",
			].includes(type)
		)
			continue;
		const error = data.details?.error;
		yield `${JSON.stringify({
			type,
			name: data.name,
			file: data.file,
			nesting: data.nesting,
			skip: data.skip,
			todo: data.todo,
			duration_ms: data.details?.duration_ms,
			message: data.message,
			error: error ? inspect(error, { depth: 8, colors: false }) : undefined,
		})}\n`;
	}
}
