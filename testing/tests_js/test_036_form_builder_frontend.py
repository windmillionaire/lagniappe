"""Node-backed checks for form-builder schema defaults."""


# @features forms form-table
# @dimensions builder-defaults unsaved-preview empty-columns
def test_table_creation_defaults_columns_for_unsaved_preview(run_node):
    run_node(
        r'''
const fs = require("node:fs");
const vm = require("node:vm");

const context = {
  generateElementId(type) {
    return `${type}-1`;
  },
  ModelElement: {
    table(schema) {
      return { id: schema.id };
    },
  },
};
vm.createContext(context);
let source = fs.readFileSync("src/script/views/builder/builder.mjs", "utf8");
source = source.replace(/^import(?:[\s\S]*?)from .*;\n/gm, "");
source = source.replace(
  "export default FormBuilder;",
  "globalThis.FormBuilder = FormBuilder;",
);
vm.runInContext(source, context);

const builder = {
  elements: new Map(),
  settings: {
    create() {
      return {};
    },
  },
};
const schema = { type: "table" };
const element = context.FormBuilder.prototype.createElement.call(builder, schema);

if (schema.id !== "table-1") {
  throw new Error(`Unexpected table ID: ${schema.id}`);
}
if (!Array.isArray(schema.columns) || schema.columns.length !== 0) {
  throw new Error("New table schema did not default columns to an empty list");
}
if (builder.elements.get(schema.id)?.schema !== schema) {
  throw new Error("Builder did not retain the normalized table schema");
}
if (element.id !== schema.id) {
  throw new Error("Builder model did not receive the normalized table schema");
}
'''
    )
