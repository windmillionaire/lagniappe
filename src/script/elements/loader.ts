import type { FormFieldSchema } from "../types/forms.d.ts";
import type { ElementRenderer } from "./base/baseElement.ts";

export async function getFormElement(
	renderer: ElementRenderer,
	schema: FormFieldSchema,
	submission?: unknown,
) {
	switch (schema.type) {
		case "checkbox": {
			const { CheckboxElement } = await import("./checkbox.ts");
			return new CheckboxElement(renderer, schema, submission);
		}
		case "radio": {
			const { RadioElement } = await import("./radio.ts");
			return new RadioElement(renderer, schema, submission);
		}
		case "textarea": {
			const { TextareaElement } = await import("./textarea.ts");
			return new TextareaElement(renderer, schema, submission);
		}
		case "input": {
			const { InputElement } = await import("./input.ts");
			return new InputElement(renderer, schema, submission);
		}
		case "select": {
			const { SelectElement } = await import("./select.ts");
			return new SelectElement(renderer, schema, submission);
		}
		case "html": {
			const { HtmlElement } = await import("./html.ts");
			return new HtmlElement(renderer, schema, submission);
		}
		case "signature": {
			const { SignatureElement } = await import("./signature.ts");
			return new SignatureElement(renderer, schema, submission);
		}
		case "table": {
			const { TableElement } = await import("./table.ts");
			return new TableElement(renderer, schema, submission);
		}
		case "todo": {
			const { TodoElement } = await import("./todo.ts");
			return new TodoElement(renderer, schema, submission);
		}
		case "link": {
			const { LinkElement } = await import("./link.ts");
			return new LinkElement(renderer, schema, submission);
		}
		case "bookmark": {
			const { BookmarkElement } = await import("./bookmark.ts");
			return new BookmarkElement(renderer, schema, submission);
		}
		case "location": {
			const { LocationElement } = await import("./location.ts");
			return new LocationElement(renderer, schema, submission);
		}
		case "status": {
			const { StatusElement } = await import("./status.ts");
			return new StatusElement(renderer, schema, submission);
		}
		default:
			throw new Error(`Unknown form element type: ${schema.type}`);
	}
}
