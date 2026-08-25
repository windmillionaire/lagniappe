"""Deterministic contracts for asynchronous query and portal ownership."""

import textwrap


# @matrix async-query : cancellation ordering repeated-key
def test_query_lifecycle_publishes_only_the_current_request(run_node):
    run_node(
        textwrap.dedent(
            r"""
            import assert from "node:assert/strict";
            import { QueryLifecycle } from "./src/script/shared/queryLifecycle.mjs";

            const deferred = () => {
              let resolve;
              const promise = new Promise((done) => { resolve = done; });
              return { promise, resolve };
            };
            const lifecycle = new QueryLifecycle();
            const published = [];
            let live = "A";

            const firstA = deferred();
            let firstSignal;
            const first = lifecycle.run(
              "A",
              (token) => { firstSignal = token.signal; return firstA.promise; },
              (value) => published.push(value),
              { getCurrentKey: () => live },
            );
            live = "B";
            const b = deferred();
            const second = lifecycle.run(
              "B",
              () => b.promise,
              (value) => published.push(value),
              { getCurrentKey: () => live },
            );
            assert.equal(firstSignal.aborted, true);

            b.resolve("new-B");
            assert.equal(await second, true);
            firstA.resolve("old-A");
            assert.equal(await first, false);
            assert.deepEqual(published, ["new-B"]);

            live = "A";
            const oldA = deferred();
            const third = lifecycle.run(
              "A",
              () => oldA.promise,
              (value) => published.push(value),
              { getCurrentKey: () => live },
            );
            live = "B";
            const middleB = deferred();
            const fourth = lifecycle.run(
              "B",
              () => middleB.promise,
              (value) => published.push(value),
              { getCurrentKey: () => live },
            );
            live = "A";
            const newA = deferred();
            const fifth = lifecycle.run(
              "A",
              () => newA.promise,
              (value) => published.push(value),
              { getCurrentKey: () => live },
            );

            oldA.resolve("repeated-old-A");
            middleB.resolve("middle-B");
            newA.resolve("repeated-new-A");
            assert.equal(await third, false);
            assert.equal(await fourth, false);
            assert.equal(await fifth, true);
            assert.deepEqual(published, ["new-B", "repeated-new-A"]);
            """
        ),
        module=True,
    )


# @matrix async-query : error-propagation teardown
def test_query_lifecycle_invalidates_repeated_keys_and_destroyed_owners(run_node):
    run_node(
        textwrap.dedent(
            r"""
            import assert from "node:assert/strict";
            import { QueryLifecycle } from "./src/script/shared/queryLifecycle.mjs";

            let rejectLoader;
            const lifecycle = new QueryLifecycle();
            const pending = lifecycle.run(
              "active",
              () => new Promise((resolve, reject) => { rejectLoader = reject; }),
              () => { throw new Error("stale publisher ran"); },
            );
            lifecycle.destroy();
            const abort = new Error("cancelled");
            abort.name = "AbortError";
            rejectLoader(abort);
            assert.equal(await pending, false);
            assert.equal(await lifecycle.run("later", async () => 1, () => {}), false);
            """
        ),
        module=True,
    )


# @pair async-query:error-propagation
def test_query_lifecycle_propagates_current_loader_errors(run_node):
    run_node(
        textwrap.dedent(
            r"""
            import assert from "node:assert/strict";
            import { QueryLifecycle } from "./src/script/shared/queryLifecycle.mjs";

            const lifecycle = new QueryLifecycle();
            const expected = new Error("loader failed");
            await assert.rejects(
              lifecycle.run("active", async () => { throw expected; }, () => {}),
              (error) => error === expected,
            );
            """
        ),
        module=True,
    )


# @matrix async-query combobox : debounce dismissal stale-publication teardown
def test_remote_combobox_invalidates_before_debounce_and_on_destroy(run_node):
    run_node(
        textwrap.dedent(
            r"""
            import assert from "node:assert/strict";
            import fs from "node:fs";
            import vm from "node:vm";
            import { QueryLifecycle } from "./src/script/shared/queryLifecycle.mjs";

            class Element {
              constructor() {
                this.listeners = new Map();
                this.value = "A";
              }
              addEventListener(type, callback) { this.listeners.set(type, callback); }
              removeEventListener(type, callback) {
                if (this.listeners.get(type) === callback) this.listeners.delete(type);
              }
              removeAttribute() {}
            }
            class Combobox {
              constructor(element) {
                this._destroyed = false;
                this.element = element;
                this.options = [];
                this.focusedIndex = -1;
                this.panelOpen = true;
                this.shows = 0;
                this.hides = 0;
              }
              init() {}
              hidePanel() {
                this.panelOpen = false;
                this.hides += 1;
                this.element.value = "";
              }
              showPanel() { this.shows += 1; return Promise.resolve(true); }
              destroy() { this._destroyed = true; }
            }
            const debounce = (callback) => {
              let pending = null;
              const delayed = (...args) => { pending = args; };
              delayed.fire = () => {
                const args = pending;
                pending = null;
                if (args) callback(...args);
              };
              delayed.cancel = () => { pending = null; };
              return delayed;
            };
            const context = { captureError: (error) => { throw error; }, debounce, QueryLifecycle, Combobox };
            vm.createContext(context);
            let source = fs.readFileSync("src/script/elements/combobox/remote.mjs", "utf8");
            source = source.replace(/^import[\s\S]*?;\r?\n/gm, "");
            source = source.replace("export class RemoteQueryCombobox", "class RemoteQueryCombobox");
            source += "\nglobalThis.RemoteQueryCombobox = RemoteQueryCombobox;";
            vm.runInContext(source, context);

            let inputs = 0;
            class TestBox extends context.RemoteQueryCombobox {
              _input() { inputs += 1; }
            }
            const element = new Element();
            const box = new TestBox(element);
            box.init();

            let resolveRequest;
            let requestSignal;
            let publications = 0;
            const request = box.runQuery(
              "A",
              (token) => {
                requestSignal = token.signal;
                return new Promise((resolve) => { resolveRequest = resolve; });
              },
              () => { publications += 1; },
            );
            assert.equal(await box.showPanel(), false);
            assert.equal(box.shows, 0);

            element.value = "B";
            element.listeners.get("input")({ target: element });
            assert.equal(requestSignal.aborted, true);
            assert.equal(box.panelOpen, false);
            assert.equal(element.value, "B");
            assert.equal(inputs, 0);

            box.destroy();
            box._debouncedInput.fire();
            assert.equal(inputs, 0);
            assert.equal(element.listeners.has("input"), false);
            resolveRequest("old-A");
            assert.equal(await request, false);
            assert.equal(publications, 0);
            """
        ),
        module=True,
    )


# @matrix search : recent-results stale-publication threshold
def test_search_threshold_settles_stale_work_and_restores_recent_results(run_node):
    run_node(
        textwrap.dedent(
            r"""
            import assert from "node:assert/strict";
            import fs from "node:fs";
            import vm from "node:vm";

            const calls = [];
            class RemoteQueryCombobox {
              constructor(element) {
                this.element = element;
                this.styles = {};
              }
              init() {}
              settleQueryInput(options = {}) { calls.push(["settle", options.clear === true]); }
              updatePanel(html) { calls.push(["update", html]); }
              showPanel() { calls.push(["show"]); }
            }
            class Results {
              create() { return "recent-results"; }
            }
            const context = {
              ENDPOINTS: { search: { bar: "/l/search-bar", page: "/l/search-page" } },
              RemoteQueryCombobox,
              request: {},
              Results,
              STYLES: { dropdown: { panel: "panel" } },
            };
            vm.createContext(context);
            let source = fs.readFileSync("src/script/elements/combobox/search.mjs", "utf8");
            source = source.replace(/^import .*;\r?\n/gm, "");
            source = source.replace("export class SearchBox", "class SearchBox");
            source += "\nglobalThis.SearchBox = SearchBox;";
            vm.runInContext(source, context);

            const box = new context.SearchBox({ value: "" });
            box._search = (query) => calls.push(["search", query]);
            box._input({ target: { value: "a" } });
            box._input({ target: { value: "" } });
            box._input({ target: { value: "ab" } });
            assert.deepEqual(calls, [
              ["settle", true],
              ["settle", false],
              ["update", "recent-results"],
              ["show"],
              ["search", "ab"],
            ]);
            """
        ),
        module=True,
    )


# @matrix modal : exact-owner late-publication listener-teardown reuse
def test_modal_owns_exact_node_and_rejects_late_attachment(run_node):
    run_node(
        textwrap.dedent(
            r"""
            import assert from "node:assert/strict";
            import fs from "node:fs";
            import vm from "node:vm";

            class Node {
              constructor(id = "modal") {
                this.id = id;
                this.removed = false;
                this.isConnected = false;
              }
              querySelector(selector) { return selector === "#modal" ? this : null; }
              remove() { this.removed = true; this.isConnected = false; }
            }
            const listeners = new Map();
            const body = {
              children: [],
              appendChild(node) {
                this.children.push(node);
                node.isConnected = true;
                return node;
              },
            };
            let resolveLoad;
            const context = {
              captureError: (error) => { throw error; },
              document: {
                activeElement: null,
                addEventListener(type, callback) { listeners.set(type, callback); },
                removeEventListener(type, callback) {
                  if (listeners.get(type) === callback) listeners.delete(type);
                },
                body,
                createElement: () => new Node("generated"),
              },
              ENDPOINTS: { delete: () => "", help: () => "" },
              request: {
                get: () => new Promise((resolve) => { resolveLoad = resolve; }),
              },
              STYLES: { modal: { wrapper: "", content: "", header: "" }, button: { close: "" } },
              withTransition: async (callback) => { callback(); return true; },
            };
            vm.createContext(context);
            let source = fs.readFileSync("src/script/shared/modal.mjs", "utf8");
            source = source.replace(/^import .*;\r?\n/gm, "");
            source = source.replaceAll("export class ", "class ");
            source += "\nglobalThis.Modal = Modal; globalThis.OfflineModal = OfflineModal;";
            vm.runInContext(source, context);

            const first = new Node("modal");
            const modal = new context.Modal({}, null);
            assert.equal(await modal.attach(first), first);
            assert.equal(modal.modal, first);
            assert.equal(listeners.size, 2);
            await modal.remove();
            assert.equal(first.removed, true);
            assert.equal(modal.modal, null);
            assert.equal(listeners.size, 0);

            const triggerListeners = new Set();
            const trigger = {
              addEventListener(type, callback) { if (type === "click") triggerListeners.add(callback); },
              removeEventListener(type, callback) { if (type === "click") triggerListeners.delete(callback); },
            };
            const offline = new context.OfflineModal({}, trigger);
            offline.enable();
            offline.enable();
            assert.equal(triggerListeners.size, 1);
            offline.disable();
            offline.disable();
            assert.equal(triggerListeners.size, 0);
            offline.enable();
            assert.equal(triggerListeners.size, 1);
            offline.destroy();
            offline.destroy();
            assert.equal(triggerListeners.size, 0);

            const late = new Node("modal");
            const owner = {};
            const pending = new context.Modal(owner, { disabled: false });
            const loading = pending.load("/late");
            pending.destroy();
            resolveLoad({ html: late });
            assert.equal(await loading, null);
            assert.equal(late.isConnected, false);
            assert.equal(pending.modal, null);
            """
        ),
        module=True,
    )


# @matrix forms : builder-lifecycle late-publication listener-teardown
def test_builder_destroys_owned_search_modal_and_panels_during_startup(run_node):
    run_node(
        textwrap.dedent(
            r"""
            import assert from "node:assert/strict";
            import fs from "node:fs";
            import vm from "node:vm";

            let resolveSearch;
            const searchReady = new Promise((resolve) => { resolveSearch = resolve; });
            const destroyed = [];
            const panelClass = (name) => class {
              constructor() { this.name = name; this.saveButton = { dataset: {} }; }
              init() {}
              destroy() { destroyed.push(name); }
            };
            class SearchBox {
              constructor() { SearchBox.instance = this; this.destroyed = 0; this._destroyed = false; }
              init() { return searchReady; }
              destroy() {
                if (this._destroyed) return;
                this._destroyed = true;
                this.destroyed += 1;
              }
            }
            class OfflineModal {
              constructor() { OfflineModal.instance = this; this.destroyed = 0; }
              enable() {}
              destroy() { this.destroyed += 1; }
            }
            class EntityMenu {
              destroy() { destroyed.push("entity-menu"); }
            }
            const schema = { value: "[]" };
            const search = { dataset: {} };
            const indicator = { dataset: {}, setAttribute() {} };
            const documentListeners = new Map();
            const context = {
              captureError: (error) => { throw error; },
              ComponentsPanel: panelClass("components"),
              ConditionPanel: panelClass("conditions"),
              connectivity: { online: true, hidden: false },
              DeleteModal: class {},
              document: {
                hidden: false,
                addEventListener(type, callback) { documentListeners.set(type, callback); },
                removeEventListener(type, callback) {
                  if (documentListeners.get(type) === callback) documentListeners.delete(type);
                },
                querySelector(selector) {
                  if (selector === 'input[name="schema"]') return schema;
                  if (selector === '[data-role="offline"]') return indicator;
                  if (selector === "[lp-search]") return search;
                  return null;
                },
              },
              ElementSettings: panelClass("settings"),
              ENDPOINTS: {},
              EntityMenu,
              FormSettings: panelClass("form-settings"),
              generateElementId: () => "generated",
              Header: panelClass("header"),
              HelpModal: class {},
              loadCondition: async () => null,
              ModelElement: {},
              ModelPanel: panelClass("model"),
              OfflineModal,
              request: {},
              SearchBox,
              withTransition: async (callback) => callback(),
              window: { location: {} },
            };
            vm.createContext(context);
            let source = fs.readFileSync("src/script/views/builder/builder.mjs", "utf8");
            source = source.replace(/^import(?:[\s\S]*?)from .*;\r?\n/gm, "");
            source = source.replace("export default FormBuilder;", "globalThis.FormBuilder = FormBuilder;");
            vm.runInContext(source, context);

            const node = {
              dataset: { key: "form-key", schema: "[]" },
              addEventListener() {},
              removeEventListener() {},
              setAttribute() {},
            };
            const builder = new context.FormBuilder(node);
            await builder.init();
            assert.equal(builder.SearchBox, SearchBox.instance);
            assert.equal(documentListeners.has("click"), true);
            builder.destroy();
            resolveSearch();
            await builder._searchPromise;

            assert.equal(SearchBox.instance.destroyed, 1);
            assert.equal(OfflineModal.instance.destroyed, 1);
            assert.deepEqual(
              destroyed.sort(),
              ["components", "conditions", "entity-menu", "form-settings", "header", "model", "settings"].sort(),
            );
            assert.equal(documentListeners.has("click"), false);
            assert.equal(builder.SearchBox, null);
            """
        ),
        module=True,
    )
