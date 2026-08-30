/*! Third-party licenses: /third-party-licenses.txt */
/**
 * @testable true
 * @tests tests_js/test_031_form_element_loader.py::test_unknown_form_element_reports_schema_type
 * @pair forms:invalid-schema
 */
async function getFormElement(renderer, schema, submission) {
	let module;
	switch (schema.type) {
		case "checkbox":
			module = await import('./checkbox.js?v=bd163a0f');
			return new module.CheckboxElement(renderer, schema, submission);
		case "radio":
			module = await import('./radio.js?v=bd163a0f');
			return new module.RadioElement(renderer, schema, submission);
		case "textarea":
			module = await import('./textarea.js?v=bd163a0f');
			return new module.TextareaElement(renderer, schema, submission);
		case "input":
			module = await import('./input.js?v=bd163a0f');
			return new module.InputElement(renderer, schema, submission);
		case "select":
			module = await import('./select.js?v=bd163a0f');
			return new module.SelectElement(renderer, schema, submission);
		case "html":
			module = await import('./html2.js?v=bd163a0f');
			return new module.HtmlElement(renderer, schema, submission);
		case "signature":
			module = await import('./signature.js?v=bd163a0f');
			return new module.SignatureElement(renderer, schema, submission);
		case "table":
			module = await import('./table.js?v=bd163a0f');
			return new module.TableElement(renderer, schema, submission);
		case "todo":
			module = await import('./todo.js?v=bd163a0f');
			return new module.TodoElement(renderer, schema, submission);
		case "link":
			module = await import('./link.js?v=bd163a0f');
			return new module.LinkElement(renderer, schema, submission);
		case "bookmark":
			module = await import('./bookmark.js?v=bd163a0f');
			return new module.BookmarkElement(renderer, schema, submission);
		case "location":
			module = await import('./location.js?v=bd163a0f');
			return new module.LocationElement(renderer, schema, submission);
		case "status":
			module = await import('./status2.js?v=bd163a0f');
			return new module.StatusElement(renderer, schema, submission);
		default:
			throw new Error(`Unknown form element type: ${schema.type}`);
	}
}

export { getFormElement as g };
