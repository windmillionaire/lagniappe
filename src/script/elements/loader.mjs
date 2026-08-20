/**
 * @testable true
 * @tests tests_js/test_031_form_element_loader.py::test_unknown_form_element_reports_schema_type
 * @features forms
 * @dimensions invalid-schema
 */
export async function getFormElement(renderer, schema, submission) {
	let module;
	switch (schema.type) {
		case "checkbox":
			module = await import(`./checkbox`);
			return new module.CheckboxElement(renderer, schema, submission);
		case "radio":
			module = await import(`./radio`);
			return new module.RadioElement(renderer, schema, submission);
		case "textarea":
			module = await import(`./textarea`);
			return new module.TextareaElement(renderer, schema, submission);
		case "input":
			module = await import(`./input`);
			return new module.InputElement(renderer, schema, submission);
		case "select":
			module = await import(`./select`);
			return new module.SelectElement(renderer, schema, submission);
		case "html":
			module = await import(`./html`);
			return new module.HtmlElement(renderer, schema, submission);
		case "signature":
			module = await import(`./signature`);
			return new module.SignatureElement(renderer, schema, submission);
		case "table":
			module = await import(`./table`);
			return new module.TableElement(renderer, schema, submission);
		case "todo":
			module = await import(`./todo`);
			return new module.TodoElement(renderer, schema, submission);
		case "link":
			module = await import(`./link`);
			return new module.LinkElement(renderer, schema, submission);
		case "bookmark":
			module = await import(`./bookmark`);
			return new module.BookmarkElement(renderer, schema, submission);
		case "location":
			module = await import(`./location`);
			return new module.LocationElement(renderer, schema, submission);
		case "status":
			module = await import(`./status`);
			return new module.StatusElement(renderer, schema, submission);
		default:
			throw new Error(`Unknown form element type: ${schema.type}`);
	}
}
