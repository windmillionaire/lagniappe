"""Node-backed checks for form-element module selection."""


# @features forms
# @dimensions invalid-schema
def test_unknown_form_element_reports_schema_type(run_node):
    run_node(
        r'''
import { getFormElement } from "./src/script/elements/loader.mjs";

try {
  await getFormElement(null, { type: "unsupported-field" }, null);
  throw new Error("Expected an unsupported form element to fail");
} catch (error) {
  if (error.message !== "Unknown form element type: unsupported-field") {
    throw error;
  }
}
''',
        module=True,
    )
