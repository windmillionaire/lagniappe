"""Node-backed checks for static HTML element failures."""


# @pair form-html:error-reporting
def test_html_element_reports_request_failure_without_masking_original(run_node):
    run_node(
        r'''
const fs = require("node:fs");
const vm = require("node:vm");

(async () => {
class BaseElement {
  constructor(renderer, schema, submission) {
    this.renderer = renderer;
    this.schema = schema;
    this.submission = submission;
  }
}

const original = new Error("HTML request failed");
const captured = [];
const dependencies = {
  BaseElement,
  captureError(...args) {
    captured.push(args);
  },
  ENDPOINTS: {
    html(key, id) {
      return { getContent: `/assets/${key}/html/${id}` };
    },
  },
  request: {
    get() {
      return Promise.reject(original);
    },
  },
};
const context = { dependencies };
vm.createContext(context);

let source = fs.readFileSync("src/script/elements/html.mjs", "utf8");
source = source.replace(
  /import \{([^}]+)\} from "\.\.\/shared";/,
  "const {$1} = dependencies;",
);
source = source.replace(
  /import \{([^}]+)\} from "\.\/base\/baseElement";/,
  "const {$1} = dependencies;",
);
source = source.replace(
  "export class HtmlElement",
  "globalThis.HtmlElement = class HtmlElement",
);
vm.runInContext(source, context);

const target = {};
const element = new context.HtmlElement(
  { form: { key: "form-1", target } },
  { id: "instructions" },
  null,
);
const result = await element._getHtml();

if (result !== "") {
  throw new Error(`Failed HTML request unexpectedly returned ${result}`);
}
if (captured.length !== 1 || captured[0][0] !== original) {
  throw new Error("The original request failure was not reported");
}
if (captured[0][1] !== target) {
  throw new Error("The form target was not attached to the error report");
}
if (captured[0][2]?.schema !== element.schema) {
  throw new Error("The field schema was not attached to the error report");
}
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
''',
    )
