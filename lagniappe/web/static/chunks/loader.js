/*! Third-party licenses: /third-party-licenses.txt */
/**
 * @testable true
 * @tests tests_js/test_031_form_element_loader.py::test_unknown_form_element_reports_schema_type
 * @features forms
 * @dimensions invalid-schema
 */
async function getFormElement(renderer, schema, submission) {
	let module;
	switch (schema.type) {
		case "checkbox":
			module = await import('./checkbox.js?v=bc116afe');
			return new module.CheckboxElement(renderer, schema, submission);
		case "radio":
			module = await import('./radio.js?v=bc116afe');
			return new module.RadioElement(renderer, schema, submission);
		case "textarea":
			module = await import('./textarea.js?v=bc116afe');
			return new module.TextareaElement(renderer, schema, submission);
		case "input":
			module = await import('./input.js?v=bc116afe');
			return new module.InputElement(renderer, schema, submission);
		case "select":
			module = await import('./select.js?v=bc116afe');
			return new module.SelectElement(renderer, schema, submission);
		case "html":
			module = await import('./html2.js?v=bc116afe');
			return new module.HtmlElement(renderer, schema, submission);
		case "signature":
			module = await import('./signature.js?v=bc116afe');
			return new module.SignatureElement(renderer, schema, submission);
		case "table":
			module = await import('./table.js?v=bc116afe');
			return new module.TableElement(renderer, schema, submission);
		case "todo":
			module = await import('./todo.js?v=bc116afe');
			return new module.TodoElement(renderer, schema, submission);
		case "link":
			module = await import('./link.js?v=bc116afe');
			return new module.LinkElement(renderer, schema, submission);
		case "bookmark":
			module = await import('./bookmark.js?v=bc116afe');
			return new module.BookmarkElement(renderer, schema, submission);
		case "location":
			module = await import('./location.js?v=bc116afe');
			return new module.LocationElement(renderer, schema, submission);
		case "status":
			module = await import('./status2.js?v=bc116afe');
			return new module.StatusElement(renderer, schema, submission);
		default:
			throw new Error(`Unknown form element type: ${schema.type}`);
	}
}

export { getFormElement as g };
