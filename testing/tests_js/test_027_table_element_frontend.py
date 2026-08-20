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


# @features form-table
# @dimensions touch-gesture
def test_table_touch_movement_threshold_distinguishes_tap_from_swipe(run_node):
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

const activeDocumentListeners = new Map();
const document = {
  addEventListener(type, handler) {
    activeDocumentListeners.set(type, handler);
  },
  removeEventListener(type, handler) {
    if (activeDocumentListeners.get(type) === handler) {
      activeDocumentListeners.delete(type);
    }
  },
};
const context = {
  BaseElement,
  CheckboxElement: class {},
  document,
  ENDPOINTS: {
    renderer: {
      validateRow(key, tableId) {
        return `/forms/${key}/validate-row/${tableId}`;
      },
    },
  },
  InputElement: class {},
  LinkElement: class {},
  performance: { now: () => 1000 },
};
vm.createContext(context);
let source = fs.readFileSync("src/script/elements/table.mjs", "utf8");
source = source.replace(/^import .*$/gm, "");
source = source.replace("export class TableElement", "class TableElement");
source += "\nglobalThis.TableElement = TableElement;";
vm.runInContext(source, context);

const renderer = { form: { key: "page-key" }, readonly: false };
const table = new context.TableElement(renderer, { id: "contacts" }, null);
const row = { id: "row-one" };
const target = {
  closest(selector) {
    return selector === "tr[data-index]" ? row : null;
  },
};
const touch = (pointerId, clientX, clientY) => ({
  pointerType: "touch",
  pointerId,
  clientX,
  clientY,
  target,
});
const shown = [];
let hidden = 0;
table._showActions = (shownRow, options) => shown.push([shownRow, options]);
table._hideActions = () => {
  hidden += 1;
};

table._rowPointerDown(touch(1, 100, 100));
table._rowPointerMove(touch(1, 108, 100));
table._rowPointerUp(touch(1, 108, 100));

if (shown.length !== 1 || shown[0][0] !== row || !shown[0][1].pinned) {
  throw new Error("Movement at the tap tolerance must pin the row actions");
}
if (activeDocumentListeners.size !== 0 || table._pendingTouchAction !== null) {
  throw new Error("Completed taps must remove temporary document listeners");
}

table._rowPointerDown(touch(2, 100, 100));
table._rowPointerMove(touch(2, 109, 100));
table._rowPointerUp(touch(2, 109, 100));

if (shown.length !== 1) {
  throw new Error("Movement beyond the tap tolerance must not show row actions");
}
if (hidden !== 1) {
  throw new Error("A swipe must hide any active row actions exactly once");
}
if (activeDocumentListeners.size !== 0 || table._pendingTouchAction !== null) {
  throw new Error("Canceled gestures must remove temporary document listeners");
}
'''
    )
