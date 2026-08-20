"""Node-backed checks for the frontend submission manager."""

import textwrap

def run_submission_manager_check(run_node, assertion: str):
    script = f"""
const fs = require("node:fs");
const vm = require("node:vm");

const capturedErrors = [];
const events = [];

class FakeFormData {{
  constructor() {{
    this.fields = [];
  }}

  append(name, value) {{
    this.fields.push([name, value]);
  }}
}}

const context = {{
	capturedErrors,
	console,
	events,
	FormData: FakeFormData,
	window: {{
		location: {{ reload() {{}} }},
	}},
}};

vm.createContext(context);
let source = fs.readFileSync("src/script/views/base/submission.mjs", "utf8");
source = source.replace(
	/^import [\\s\\S]*?(?=\\/\\*\\*)/,
	`
const captureError = (...args) => capturedErrors.push(args);
const request = {{}};
const withTransition = async (callback) => {{ await callback(); return true; }};
`,
);
source = source.replace("export class SubmissionManager", "class SubmissionManager");
source += "\\nglobalThis.SubmissionManager = SubmissionManager;";
vm.runInContext(source, context);
const SubmissionManager = context.SubmissionManager;

(async () => {{
{textwrap.indent(assertion, "  ")}
}})().catch((error) => {{
  console.error(error);
  process.exit(1);
}});
"""

    run_node(script)


# @features submit
# @dimensions stale-widget direct-upload-navigation
def test_submit_abandons_stale_widget_after_async_prepare(run_node):
    run_submission_manager_check(
        run_node,
        """
const componentElt = {
  _lp_component: null,
  closest(selector) {
    return selector === "[lp-component]" ? this : null;
  },
  dataset: {},
  hasAttribute(name) {
    return name === "lp-component";
  },
  id: "tools",
  matches() {
    return false;
  },
  setAttribute() {},
};

const submitForm = {
  isConnected: true,
  closest(selector) {
    return selector === "[lp-component]" ? componentElt : null;
  },
};

const submitter = {
  dataset: { role: "organize" },
  disabled: false,
};

let createCalls = 0;
let formDataReads = 0;
let updateCalls = 0;

const component = {
  active: null,
  get route() {
    return this.active?.route || "/component-route";
  },
  showError(message) {
    events.push(`error:${message}`);
  },
  widgets: {},
};

const widget = {
  form: {
    syncOfflineState() {
      return false;
    },
  },
  get formData() {
    formDataReads += 1;
    throw new Error("stale widget formData was read");
  },
  async prepareSubmit() {
    if (!submitter.disabled) {
      throw new Error("submitter was not disabled during async preparation");
    }
    events.push("prepare");
    component.active = null;
    submitForm.isConnected = false;
    widget.target.isConnected = false;
    return true;
  },
  route: "/tools/organize",
  target: {
    isConnected: true,
    hasAttribute(name) {
      return name === "lp-create";
    },
  },
};

component.active = widget;
componentElt._lp_component = component;

const view = {
	components: {},
	getComponent() { return component; },
	online: true,
	operationId() { return "operation-1"; },
};
const manager = new SubmissionManager(view);
manager.create = () => {
	createCalls += 1;
};
manager.update = () => {
	updateCalls += 1;
};

await manager.submit({
  detail: {},
  preventDefault() {
    events.push("prevent");
  },
  stopPropagation() {
    events.push("stop");
  },
  submitter,
  target: submitForm,
});

if (events.join(",") !== "prevent,stop,prepare") {
  throw new Error(`Unexpected event sequence: ${events.join(",")}`);
}
if (formDataReads !== 0) {
  throw new Error(`Expected no stale formData reads, got ${formDataReads}`);
}
if (createCalls !== 0 || updateCalls !== 0) {
  throw new Error(`Stale submit still sent request: ${createCalls}/${updateCalls}`);
}
if (submitter.disabled) {
  throw new Error("submitter was not re-enabled after stale submit");
}
if (capturedErrors.length !== 0) {
  throw new Error(`Stale submit reported ${capturedErrors.length} errors`);
}
""",
    )


# @features submit
# @dimensions stale-widget direct-upload-error
def test_submit_does_not_show_upload_error_after_stale_prepare(run_node):
    run_submission_manager_check(
        run_node,
        """
const componentElt = {
  _lp_component: null,
  closest(selector) {
    return selector === "[lp-component]" ? this : null;
  },
  dataset: {},
  hasAttribute(name) {
    return name === "lp-component";
  },
  id: "tools",
  matches() {
    return false;
  },
  setAttribute() {},
};

const submitForm = {
  isConnected: true,
  closest(selector) {
    return selector === "[lp-component]" ? componentElt : null;
  },
};

const submitter = {
  dataset: { role: "organize" },
  disabled: false,
};

const component = {
  active: null,
  get route() {
    return this.active?.route || "/component-route";
  },
  showError(message) {
    events.push(`error:${message}`);
  },
  widgets: {},
};

const widget = {
  form: {
    syncOfflineState() {
      return false;
    },
  },
  async prepareSubmit() {
    events.push("prepare");
    component.active = null;
    submitForm.isConnected = false;
    widget.target.isConnected = false;
    throw new Error("upload failed");
  },
  route: "/tools/organize",
  target: {
    isConnected: true,
    hasAttribute(name) {
      return name === "lp-create";
    },
  },
};

component.active = widget;
componentElt._lp_component = component;

const view = {
	components: {},
	getComponent() { return component; },
	online: true,
	operationId() { return "operation-1"; },
};
const manager = new SubmissionManager(view);

await manager.submit({
  detail: {},
  preventDefault() {
    events.push("prevent");
  },
  stopPropagation() {
    events.push("stop");
  },
  submitter,
  target: submitForm,
});

if (events.join(",") !== "prevent,stop,prepare") {
  throw new Error(`Unexpected event sequence: ${events.join(",")}`);
}
if (submitter.disabled) {
  throw new Error("submitter was not re-enabled after stale upload error");
}
if (capturedErrors.length !== 0) {
  throw new Error(`Stale upload error reported ${capturedErrors.length} errors`);
}
""",
    )


# @features submit
# @dimensions missing-form-data
def test_submit_stops_before_appending_when_form_data_is_missing(run_node):
    run_submission_manager_check(
        run_node,
        """
const componentElt = {
  closest(selector) {
    return selector === "[lp-component]" ? this : null;
  },
};
const submitTarget = {
  isConnected: true,
  closest(selector) {
    return selector === "[lp-component]" ? componentElt : null;
  },
};
const submitter = {
  dataset: {},
  disabled: false,
};
const widget = {
  form: { syncOfflineState() { return false; } },
  target: {
    isConnected: true,
    hasAttribute() { return false; },
  },
};
const component = {
  active: widget,
  formData: undefined,
  widgets: {},
};
const view = {
  components: {},
  getComponent() { return component; },
  online: true,
};
const manager = new SubmissionManager(view);
let createCalls = 0;
let updateCalls = 0;
manager.create = () => {
  createCalls += 1;
};
manager.update = () => {
  updateCalls += 1;
};

await manager.submit({
  detail: { update: true },
  preventDefault() {},
  stopPropagation() {},
  submitter,
  target: submitTarget,
});

if (capturedErrors.length !== 1) {
  throw new Error(`Expected one diagnostic, got ${capturedErrors.length}`);
}
if (capturedErrors[0][0]?.message !== "No form data found") {
  throw new Error(`Unexpected diagnostic: ${capturedErrors[0][0]?.message}`);
}
if (createCalls !== 0 || updateCalls !== 0) {
  throw new Error(`Missing data still sent request: ${createCalls}/${updateCalls}`);
}
if (submitter.disabled) {
  throw new Error("submitter was not re-enabled after missing form data");
}
""",
    )


# @features submit
# @dimensions route-override active-widget
def test_submit_uses_explicit_action_route_over_active_widget_route(run_node):
    run_submission_manager_check(
        run_node,
        """
const componentElt = {
  closest(selector) {
    return selector === "[lp-component]" ? this : null;
  },
};
const submitTarget = {
  isConnected: true,
  closest(selector) {
    return selector === "[lp-component]" ? componentElt : null;
  },
};
const submitter = {
  dataset: { role: "complete-toggle" },
  disabled: false,
};
const widget = {
  form: { syncOfflineState() { return false; } },
  route: "/tasks/task/history",
  target: {
    isConnected: true,
    hasAttribute() { return false; },
  },
};
const component = {
  active: widget,
  formData: new FormData(),
  route: widget.route,
  widgets: {},
};
const view = {
  components: {},
  getComponent() { return component; },
  online: true,
};
const manager = new SubmissionManager(view);
let updateRoute = null;
manager.update = (_component, _data, route) => {
  updateRoute = route;
};

await manager.submit({
  detail: {
    update: true,
    role: "complete-toggle",
    route: "/tasks/task/update",
  },
  preventDefault() {},
  stopPropagation() {},
  submitter,
  target: submitTarget,
});

if (updateRoute !== "/tasks/task/update") {
  throw new Error(`Completion used the active widget route: ${updateRoute}`);
}
""",
    )


# @features submit deferred-jobs
# @dimensions deferred-create background destination-row
def test_deferred_background_create_does_not_decorate_source_form(run_node):
    run_submission_manager_check(
        run_node,
        """
const tracked = [];
const created = [];
const source = { dataset: {} };
const component = {
  active: { target: source },
  async created(response) { created.push(response.html); },
};
const view = {
  components: {},
  async ensureDeferredOperations() {
    return { track(key, options) { tracked.push([key, options.node]); } };
  },
  async ensureNotifications() {
    return { upsertNotification() {} };
  },
};
const manager = new SubmissionManager(view);
await manager._deferredCreated(
  {
    background: true,
    deferred: true,
    html: "<table><tr></tr></table>",
    notification: "<li></li>",
    operation: "operation-1",
  },
  component,
);

if (tracked.length !== 1 || tracked[0][0] !== "operation-1" || tracked[0][1] !== null) {
  throw new Error(`Background create decorated its source form: ${JSON.stringify(tracked)}`);
}
if (created.join("") !== "<table><tr></tr></table>") {
  throw new Error("Background create did not reconcile the destination row");
}
""",
    )
