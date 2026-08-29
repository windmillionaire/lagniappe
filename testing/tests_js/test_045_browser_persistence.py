"""Node-backed checks for browser persistence acknowledgement boundaries."""


_OFFLINE_HARNESS = r'''
const fs = require("node:fs");
const vm = require("node:vm");

const tick = () => new Promise((resolve) => setImmediate(resolve));

function createIndexedDB() {
  const state = {
    closeCount: 0,
    transactions: [],
  };
  const db = {
    close() { state.closeCount += 1; },
    transaction(storeNames, mode) {
      const tx = {
        abortCount: 0,
        error: null,
        mode,
        requests: [],
        storeNames,
        abort() { this.abortCount += 1; },
        objectStore(name) {
          return {
            delete(key) { return makeRequest("delete", { key, name }); },
            get(key) { return makeRequest("get", { key, name }); },
            getAll() { return makeRequest("getAll", { name }); },
            put(value) { return makeRequest("put", { name, value }); },
          };
        },
      };
      const makeRequest = (operation, details) => {
        const request = { operation, ...details };
        tx.requests.push(request);
        return request;
      };
      state.transactions.push(tx);
      return tx;
    },
  };
  const indexedDB = {
    open() {
      const request = { result: db };
      queueMicrotask(() => request.onsuccess?.());
      return request;
    },
  };
  return { db, indexedDB, state };
}

function loadOffline(indexedDB) {
  const context = { console, indexedDB, queueMicrotask };
  vm.createContext(context);
  let source = fs.readFileSync("src/script/shared/offline.mjs", "utf8");
  source = source.replace(/export function /g, "function ");
  source += `
globalThis.withTransaction = withTransaction;
globalThis.setOfflineMutation = setOfflineMutation;
globalThis.getOfflineMutations = getOfflineMutations;
globalThis.deleteOfflineMutations = deleteOfflineMutations;
`;
  vm.runInContext(source, context);
  return context;
}

async function waitForTransaction(state, index = 0) {
  for (let attempt = 0; attempt < 10; attempt += 1) {
    if (state.transactions[index]) return state.transactions[index];
    await tick();
  }
  throw new Error(`Transaction ${index} was not created`);
}

async function waitForRequests(tx, count) {
  for (let attempt = 0; attempt < 10; attempt += 1) {
    if (tx.requests.length >= count) return;
    await tick();
  }
  throw new Error(`Expected ${count} requests, received ${tx.requests.length}`);
}
'''


# @matrix offline sync : connection-lifecycle multi-delete readonly-result transaction-commit
def test_indexeddb_operations_resolve_only_after_transaction_commit(run_node):
    run_node(
        _OFFLINE_HARNESS
        + r'''
(async () => {
  const { db, indexedDB, state } = createIndexedDB();
  const offline = loadOffline(indexedDB);

  let writeSettled = false;
  const write = offline.setOfflineMutation({ id: "mutation-1" }).then(() => {
    writeSettled = true;
  });
  const writeTx = await waitForTransaction(state, 0);
  await waitForRequests(writeTx, 1);
  writeTx.requests[0].onsuccess?.();
  await tick();
  if (writeSettled) throw new Error("Write resolved on request success");
  db.onversionchange?.();
  if (state.closeCount !== 1 || writeSettled) {
    throw new Error("Version change did not close without settling the transaction");
  }
  writeTx.oncomplete?.();
  await write;
  if (!writeSettled || state.closeCount !== 1) {
    throw new Error("Committed write did not settle with one database close");
  }

  let readSettled = false;
  const read = offline.getOfflineMutations().then((value) => {
    readSettled = true;
    return value;
  });
  const readTx = await waitForTransaction(state, 1);
  await waitForRequests(readTx, 1);
  readTx.requests[0].result = [{ id: "mutation-1" }];
  readTx.requests[0].onsuccess?.();
  await tick();
  if (readSettled) throw new Error("Readonly result resolved before completion");
  readTx.oncomplete?.();
  const records = await read;
  if (records.length !== 1 || records[0].id !== "mutation-1") {
    throw new Error(`Unexpected readonly result: ${JSON.stringify(records)}`);
  }

  let deleteSettled = false;
  const deleted = offline.deleteOfflineMutations(["one", "two"]).then(() => {
    deleteSettled = true;
  });
  const deleteTx = await waitForTransaction(state, 2);
  await waitForRequests(deleteTx, 2);
  deleteTx.requests[0].onsuccess?.();
  await tick();
  if (deleteSettled) throw new Error("Multi-delete resolved after one request");
  deleteTx.requests[1].onsuccess?.();
  await tick();
  if (deleteSettled) throw new Error("Multi-delete resolved before commit");
  deleteTx.oncomplete?.();
  await deleted;
  if (!deleteSettled) throw new Error("Multi-delete did not resolve after commit");
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
'''
    )


# @matrix offline sync : connection-lifecycle error-ownership transaction-abort
def test_indexeddb_abort_and_errors_reject_once_and_close_the_database(run_node):
    run_node(
        _OFFLINE_HARNESS
        + r'''
(async () => {
  {
    const { indexedDB, state } = createIndexedDB();
    const offline = loadOffline(indexedDB);
    const aborted = new Error("commit aborted");
    const pending = offline.setOfflineMutation({ id: "mutation-1" });
    const tx = await waitForTransaction(state);
    await waitForRequests(tx, 1);
    tx.requests[0].onsuccess?.();
    await tick();
    tx.error = aborted;
    tx.onabort?.();
    let received = null;
    try { await pending; } catch (error) { received = error; }
    if (received !== aborted || state.closeCount !== 1) {
      throw new Error("Transaction abort did not preserve its error and close once");
    }
  }

  {
    const { indexedDB, state } = createIndexedDB();
    const offline = loadOffline(indexedDB);
    const requestError = new Error("request failed");
    const pending = offline.setOfflineMutation({ id: "mutation-2" });
    const tx = await waitForTransaction(state);
    await waitForRequests(tx, 1);
    tx.requests[0].error = requestError;
    tx.requests[0].onerror?.();
    tx.error = requestError;
    tx.onerror?.({ target: tx.requests[0] });
    tx.onabort?.();
    let received = null;
    try { await pending; } catch (error) { received = error; }
    if (received !== requestError || state.closeCount !== 1) {
      throw new Error("Request/transaction error obscured the first useful cause");
    }
  }

  {
    const { db, indexedDB, state } = createIndexedDB();
    const offline = loadOffline(indexedDB);
    const pending = offline.getOfflineMutations();
    await waitForTransaction(state);
    db.onclose?.();
    let received = null;
    try { await pending; } catch (error) { received = error; }
    if (
      received?.message !== "IndexedDB database closed unexpectedly" ||
      state.closeCount !== 1
    ) {
      throw new Error("Unexpected database close did not reject deterministically");
    }
  }
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
'''
    )


# @matrix offline sync : error-ownership executor-error transaction-abort
def test_indexeddb_executor_failures_abort_and_preserve_the_original_error(run_node):
    run_node(
        _OFFLINE_HARNESS
        + r'''
(async () => {
  for (const asynchronous of [false, true]) {
    const { indexedDB, state } = createIndexedDB();
    const offline = loadOffline(indexedDB);
    const original = new Error(asynchronous ? "async executor" : "sync executor");
    const pending = offline.withTransaction("mutations", "readwrite", () => {
      if (asynchronous) return Promise.reject(original);
      throw original;
    });
    const observed = pending.then(() => null, (error) => error);
    const tx = await waitForTransaction(state);
    const received = await observed;
    if (
      received !== original ||
      tx.abortCount !== 1 ||
      state.closeCount !== 1
    ) {
      throw new Error(`Executor failure lost ownership: ${asynchronous}`);
    }
  }
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
'''
    )


_EDITOR_HARNESS = r'''
const fs = require("node:fs");
const vm = require("node:vm");

const tick = () => new Promise((resolve) => setImmediate(resolve));
const requests = { get: [], put: [] };
const dependencies = {
  STYLES: {
    button: { submit: "submit" },
    editor: { container: "editor" },
    message: "message",
  },
  captureError(error) { throw new Error(`Unexpected capture: ${error.message}`); },
  independentEditor() { throw new Error("Editor factory was not stubbed"); },
  request: {
    get(...args) { requests.get.push(args); return Promise.resolve({ ok: true, markup: "" }); },
    put(...args) { requests.put.push(args); return Promise.resolve({ ok: true }); },
  },
  Toolbar: class {},
};
const context = { console, dependencies, TextEncoder };
vm.createContext(context);
let source = fs.readFileSync("src/script/elements/editor/independent.mjs", "utf8");
source = source.replace(
  /import \{ STYLES \} from "styles";/,
  "const { STYLES } = dependencies;",
);
source = source.replace(
  /import \{ captureError, request \} from "\.\.\/\.\.\/shared";/,
  "const { captureError, request } = dependencies;",
);
source = source.replace(
  /import \{ independentEditor \} from "\.\/editor";/,
  "const { independentEditor } = dependencies;",
);
source = source.replace(
  /import \{ Toolbar \} from "\.\/toolbar";/,
  "const { Toolbar } = dependencies;",
);
source = source.replace(
  "export class IndependentDocument",
  "globalThis.IndependentDocument = class IndependentDocument",
);
vm.runInContext(source, context);

function statusElement() {
  return {
    removeEventListener() {},
    dataset: {},
    disabled: false,
    hidden: false,
    textContent: "",
  };
}

function loadedContainer() {
  const attributes = new Set();
  return {
    attributes,
    classList: { add() {}, remove() {} },
    hasAttribute(name) { return attributes.has(name); },
    removeAttribute(name) { attributes.delete(name); },
    setAttribute(name) { attributes.add(name); },
  };
}

function makeDocument({ acknowledged = "<p>Saved</p>", current = acknowledged } = {}) {
  const document = new context.IndependentDocument({
    endpoints: { getContent: "/content", save: "/save" },
    target: {},
  });
  document.container = loadedContainer();
  document.container.setAttribute("loaded", "");
  document.status = statusElement();
  document.statusMessage = statusElement();
  document.retryButton = statusElement();
  document.acknowledgedContent = acknowledged;
  document.editor = {
    destroy() {},
    getHTML() { return current; },
  };
  return {
    document,
    setCurrent(value) { current = value; },
  };
}
'''


# @matrix editor html-field : authoritative-content error-reporting initial-load retry
def test_independent_editor_failed_load_stays_inert_and_retries(run_node):
    run_node(
        _EDITOR_HARNESS
        + r'''
(async () => {
  const document = new context.IndependentDocument({
    endpoints: { getContent: "/content", save: "/save" },
    target: {},
  });
  document.container = loadedContainer();
  document.status = statusElement();
  document.statusMessage = statusElement();
  document.retryButton = statusElement();
  document._publishLoadedContent = async (html) => {
    document.published = html;
    document.container.setAttribute("loaded", "");
  };

  const responses = [
    { ok: false, error: "Load failed" },
    { ok: true, markup: "  <p>Authoritative</p>  " },
  ];
  dependencies.request.get = (...args) => {
    requests.get.push(args);
    return Promise.resolve(responses.shift());
  };

  if (await document.load()) throw new Error("Failed load reported success");
  if (
    document.container.hasAttribute("loaded") ||
    document.acknowledgedContent !== null ||
    document._statusScope !== "load" ||
    document.retryButton.hidden
  ) {
    throw new Error("Failed load published blank authoritative state");
  }

  document._retryFailedOperation();
  await document.ready;
  if (
    document.published !== "<p>Authoritative</p>" ||
    document.acknowledgedContent !== "<p>Authoritative</p>" ||
    !document.container.hasAttribute("loaded") ||
    !document.status.hidden
  ) {
    throw new Error("Retry did not publish the acknowledged server value");
  }
  if (requests.get.some(([, , options]) => options?.replaceErrorPage !== false)) {
    throw new Error("Editor load allowed an error response to replace the page");
  }
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
'''
    )


# @matrix editor html-field : error-reporting retry server-acknowledgement
def test_independent_editor_failed_save_stays_dirty_and_retries(run_node):
    run_node(
        _EDITOR_HARNESS
        + r'''
(async () => {
  const { document, setCurrent } = makeDocument();
  setCurrent("<p>Changed</p>");
  const responses = [
    { ok: false, error: "Save failed" },
    { ok: true },
  ];
  dependencies.request.put = (...args) => {
    requests.put.push(args);
    return Promise.resolve(responses.shift());
  };

  if (await document.flush()) throw new Error("Failed save reported clean state");
  if (
    document.acknowledgedContent !== "<p>Saved</p>" ||
    document.dirtyContent !== "<p>Changed</p>" ||
    document._statusScope !== "save"
  ) {
    throw new Error("Failed save advanced the acknowledged baseline");
  }
  if (!(await document.flush())) throw new Error("Retry did not settle cleanly");
  if (
    document.acknowledgedContent !== "<p>Changed</p>" ||
    document.dirtyContent !== null ||
    requests.put.length !== 2
  ) {
    throw new Error("Successful retry did not acknowledge the dirty value");
  }
  if (requests.put.some(([, , options]) => options?.replaceErrorPage !== false)) {
    throw new Error("Editor save allowed an error response to replace the page");
  }
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
'''
    )


# @matrix editor html-field : concurrent-edit keepalive serialized-save server-acknowledgement
def test_independent_editor_serializes_inflight_edits_and_acknowledges_in_order(
    run_node,
):
    run_node(
        _EDITOR_HARNESS
        + r'''
(async () => {
  const { document, setCurrent } = makeDocument();
  const releases = [];
  dependencies.request.put = (...args) => {
    requests.put.push(args);
    return new Promise((resolve) => releases.push(resolve));
  };

  setCurrent("<p>A</p>");
  const saving = document.flush({ keepalive: true });
  await tick();
  if (requests.put.length !== 1 || requests.put[0][1].html !== "<p>A</p>") {
    throw new Error("First save was not started");
  }

  setCurrent("<p>B</p>");
  releases[0]({ ok: true });
  await tick();
  if (
    document.acknowledgedContent !== "<p>A</p>" ||
    requests.put.length !== 2 ||
    requests.put[1][1].html !== "<p>B</p>"
  ) {
    throw new Error("In-flight edit was not serialized after A acknowledgement");
  }
  if (requests.put.some(([, , options]) => options?.keepalive !== true)) {
    throw new Error("Keepalive ownership was not retained by the follow-up save");
  }

  releases[1]({ ok: true });
  if (!(await saving)) throw new Error("Serialized save did not finish cleanly");
  if (
    document.acknowledgedContent !== "<p>B</p>" ||
    document.dirtyContent !== null
  ) {
    throw new Error("Latest acknowledgement did not become the baseline");
  }

  setCurrent(`<p>${"x".repeat(70 * 1024)}</p>`);
  dependencies.request.put = (...args) => {
    requests.put.push(args);
    return Promise.resolve({ ok: true });
  };
  if (!(await document.flush({ keepalive: true }))) {
    throw new Error("Large ordinary save did not finish cleanly");
  }
  if (requests.put.at(-1)[2]?.keepalive !== false) {
    throw new Error("Oversized payload incorrectly retained keepalive mode");
  }
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
'''
    )


# @matrix editor html-field : intentional-clear server-acknowledgement
def test_independent_editor_saves_intentional_clear(run_node):
    run_node(
        _EDITOR_HARNESS
        + r'''
(async () => {
  const { document, setCurrent } = makeDocument();
  setCurrent("<p><br></p>");
  dependencies.request.put = (...args) => {
    requests.put.push(args);
    return Promise.resolve({ ok: true });
  };
  if (!(await document.flush())) throw new Error("Intentional clear did not save");
  if (
    requests.put.length !== 1 ||
    requests.put[0][1].html !== "" ||
    document.acknowledgedContent !== ""
  ) {
    throw new Error("TipTap empty content was not acknowledged as a clear");
  }

  document.destroy();
  await tick();
  if (requests.put.length !== 1) {
    throw new Error("Destroy started an unowned save request");
  }
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
'''
    )


# @matrix editor html-field : teardown
def test_builder_owns_independent_editor_lifecycle_flushes(run_node):
    run_node(
        r'''
const fs = require("node:fs");
const vm = require("node:vm");

(async () => {
const connectivity = { online: true };
const context = {
  connectivity,
  document: { hidden: false },
};
vm.createContext(context);
let source = fs.readFileSync("src/script/views/builder/builder.mjs", "utf8");
source = source.replace(/^import(?:[\s\S]*?)from .*;\n/gm, "");
source = source.replace(
  "export default FormBuilder;",
  "globalThis.FormBuilder = FormBuilder;",
);
vm.runInContext(source, context);

const calls = [];
const editor = {
  async flush(options) {
    calls.push(options);
    return true;
  },
};
const builder = {
  _independentDocuments: new Set(),
  hidden: false,
  online: true,
  offline() {},
};
builder.flushIndependentDocuments =
  context.FormBuilder.prototype.flushIndependentDocuments;
context.FormBuilder.prototype.registerIndependentDocument.call(builder, editor);

await context.FormBuilder.prototype.sync.call(builder, { hidden: true });
if (calls.length !== 1 || calls[0].keepalive !== true) {
  throw new Error("Hidden builder did not own a keepalive flush");
}

connectivity.online = false;
await context.FormBuilder.prototype.sync.call(builder, { hidden: true });
if (calls.length !== 1) throw new Error("Offline builder attempted a flush");

connectivity.online = true;
await context.FormBuilder.prototype.sync.call(builder, { hidden: false });
if (calls.length !== 2 || calls[1].keepalive !== false) {
  throw new Error("Recovered builder did not retry retained work");
}

context.FormBuilder.prototype.unregisterIndependentDocument.call(builder, editor);
await context.FormBuilder.prototype.sync.call(builder, { hidden: true });
if (calls.length !== 2) throw new Error("Unregistered editor was still flushed");
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
'''
    )
