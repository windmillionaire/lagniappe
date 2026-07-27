"""Node-backed checks for table element behavior."""


# @features form-table
# @dimensions detached-revision-preview validation-route
def test_table_validation_uses_form_key_for_detached_preview(run_node):
    run_node(
        r'''
const fs = require("node:fs");
const vm = require("node:vm");

class BaseElement {
  constructor(renderer, schema, submission) {
    this.renderer = renderer;
    this.schema = schema;
    this.submission = submission;
  }

  destroy() {}
}

const context = {
  BaseElement,
  CheckboxElement: class {},
  ENDPOINTS: {
    renderer: {
      validateRow(key, tableId) {
        return `/forms/${key}/validate-row/${tableId}`;
      },
    },
  },
  InputElement: class {},
  LinkElement: class {},
};
vm.createContext(context);
let source = fs.readFileSync("src/script/elements/table.mjs", "utf8");
source = source.replace(/^import .*$/gm, "");
source = source.replace("export class TableElement", "class TableElement");
source += "\nglobalThis.TableElement = TableElement;";
vm.runInContext(source, context);

const renderer = {
  form: {
    key: "page-key",
    target: {
      closest() {
        throw new Error("Detached preview must not depend on DOM ancestry");
      },
    },
  },
  readonly: false,
};
const table = new context.TableElement(renderer, { id: "contacts" }, null);

if (table._validate !== "/forms/page-key/validate-row/contacts") {
  throw new Error(`Unexpected table validation route: ${table._validate}`);
}
'''
    )
