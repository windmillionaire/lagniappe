export async function getFormElement(renderer, schema, submission) {
	let module;
	switch (schema.type) {
		case "checkbox":
			module = await import(`./checkbox.ts`);
			return new module.CheckboxElement(renderer, schema, submission);
		case "radio":
			module = await import(`./radio.ts`);
			return new module.RadioElement(renderer, schema, submission);
		case "textarea":
			module = await import(`./textarea.ts`);
			return new module.TextareaElement(renderer, schema, submission);
		case "input":
			module = await import(`./input.ts`);
			return new module.InputElement(renderer, schema, submission);
		case "select":
			module = await import(`./select.ts`);
			return new module.SelectElement(renderer, schema, submission);
		case "html":
			module = await import(`./html.ts`);
			return new module.HtmlElement(renderer, schema, submission);
		case "signature":
			module = await import(`./signature.ts`);
			return new module.SignatureElement(renderer, schema, submission);
		case "table":
			module = await import(`./table.ts`);
			return new module.TableElement(renderer, schema, submission);
		case "todo":
			module = await import(`./todo.ts`);
			return new module.TodoElement(renderer, schema, submission);
		case "link":
			module = await import(`./link.ts`);
			return new module.LinkElement(renderer, schema, submission);
		case "bookmark":
			module = await import(`./bookmark.ts`);
			return new module.BookmarkElement(renderer, schema, submission);
		case "location":
			module = await import(`./location.ts`);
			return new module.LocationElement(renderer, schema, submission);
		case "status":
			module = await import(`./status.ts`);
			return new module.StatusElement(renderer, schema, submission);
		default:
			throw new Error(`Unknown form element type: ${schema.type}`);
	}
}
