"""Node-backed checks for frontend direct upload retry behavior."""

import textwrap

def run_direct_upload_check(run_node, assertion: str):
    script = f"""
const fs = require("node:fs");
const vm = require("node:vm");

const fetchCalls = [];
const progress = [];

function cloneHeaders(headers) {{
  if (!headers) return {{}};
  if (headers instanceof Headers) return Object.fromEntries(headers.entries());
  return {{ ...headers }};
}}

const context = {{
  Blob,
  clearTimeout,
  console,
  fetchCalls,
  File,
  Headers,
  progress,
  Response,
  setTimeout,
  URL,
  window: {{ location: {{ origin: "https://app.example.test" }} }},
}};

context.fetch = async (_url, config = {{}}) => {{
  const headers = cloneHeaders(config.headers);
  fetchCalls.push({{
    body: config.body,
    headers,
    method: config.method || "GET",
  }});

  const contentRange = headers["Content-Range"];
  if (contentRange === "bytes 0-3/12") {{
    return new Response("", {{
      status: 308,
      headers: {{ Range: "bytes=0-3" }},
    }});
  }}
  if (contentRange === "bytes 4-7/12") {{
    throw new TypeError("connection termination");
  }}
  if (contentRange === "bytes */12") {{
    return new Response("", {{
      status: 308,
      headers: {{ Range: "bytes=0-7" }},
    }});
  }}
  if (contentRange === "bytes 8-11/12") {{
    return new Response(
      JSON.stringify({{ generation: "3", name: "tmp/uploads/file.txt" }}),
      {{
        status: 200,
        headers: {{ "Content-Type": "application/json" }},
      }},
    );
  }}

  throw new Error(`Unexpected upload request: ${{contentRange}}`);
}};

vm.createContext(context);
let source = fs.readFileSync("src/script/elements/upload.mjs", "utf8");
source = source.replace(/^import .*;\\n/gm, "");
source = source.replace("export class UploadMenu", "class UploadMenu");
source = source.replace("export const uploadElement = {{", "const uploadElement = {{");
source += "\\nglobalThis.uploadElement = uploadElement;";
vm.runInContext(source, context);
const uploadElement = context.uploadElement;
const fetchCallsRef = context.fetchCalls;
const progressRef = context.progress;

(async () => {{
{textwrap.indent(assertion, "  ")}
}})().catch((error) => {{
  console.error(error);
  process.exit(1);
}});
"""

    run_node(script)


def run_base_upload_check(run_node, assertion: str):
    script = f"""
const fs = require("node:fs");
const vm = require("node:vm");

const errors = [];
const context = {{
  Blob,
  console,
  errors,
  File,
  FormData,
  setTimeout,
  clearTimeout,
  window: {{
    addEventListener() {{}},
    location: {{ origin: "https://app.example.test" }},
    removeEventListener() {{}},
  }},
}};

context.BaseForm = class {{}};
context.uploadElement = {{ directUpload: {{}} }};

vm.createContext(context);
let source = fs.readFileSync("src/script/elements/base/baseUpload.mjs", "utf8");
source = source.replace(/^import .*;\\n/gm, "");
source = source.replace("export class BaseUpload", "class BaseUpload");
source += "\\nglobalThis.BaseUpload = BaseUpload;";
vm.runInContext(source, context);
const BaseUpload = context.BaseUpload;
const uploadElement = context.uploadElement;

(async () => {{
{textwrap.indent(assertion, "  ")}
}})().catch((error) => {{
  console.error(error);
  process.exit(1);
}});
"""

    run_node(script)


# @matrix direct-upload : resumable-range retry
def test_direct_upload_resumes_after_network_reset(run_node):
    run_direct_upload_check(
        run_node,
        """
const file = new File(["abcdefghijkl"], "file.txt", { type: "text/plain" });
const metadata = await uploadElement.directUpload.upload({
  file,
  sessionUrl: "https://storage.example.test/session",
  chunkSize: 4,
  retryDelay: 0,
  onProgress: (loaded, total) => {
    progressRef.push([loaded, total]);
  },
});

const ranges = fetchCallsRef.map((call) => call.headers["Content-Range"]);
const expected = [
  "bytes 0-3/12",
  "bytes 4-7/12",
  "bytes */12",
  "bytes 8-11/12",
];

if (ranges.join("|") !== expected.join("|")) {
  throw new Error(`Unexpected Content-Range sequence: ${ranges.join("|")}`);
}
if (metadata.generation !== "3" || metadata.name !== "tmp/uploads/file.txt") {
  throw new Error(`Final metadata was not returned: ${JSON.stringify(metadata)}`);
}

const progressValues = progressRef.map(([loaded]) => loaded);
if (progressValues.join(",") !== "4,8,12") {
  throw new Error(`Unexpected progress values: ${progressValues.join(",")}`);
}
""",
    )


# @matrix direct-upload : compatibility multipart-fallback single-file
def test_single_file_keeps_compatibility_multipart_fallback(run_node):
    run_base_upload_check(
        run_node,
        """
const file = new File(["one"], "one.txt", { type: "text/plain" });
const instance = new BaseUpload({});
instance.inputName = "upload";
instance.route = "/files/upload";
instance.fileInput = { element: { files: [file] } };
instance.showError = (message) => errors.push(message);

uploadElement.directUpload.createSession = async () => {
  throw new Error("session unavailable");
};

const prepared = await instance.prepareSubmit();
if (prepared !== true) {
  throw new Error("Single-file compatibility fallback was blocked");
}
if (errors.length !== 0 || instance.directUploads.length !== 0) {
  throw new Error("Single-file fallback exposed an error or stale metadata");
}
""",
    )


# @matrix upload : directory-rejection drag-drop
def test_directory_drop_is_rejected_before_file_processing(run_node):
    run_base_upload_check(
        run_node,
        """
let dropHandler;
const instance = new BaseUpload({});
instance.dropzone = {
  element: {
    addEventListener(name, handler) {
      if (name === "drop") dropHandler = handler;
    },
  },
};
instance.showError = (message) => errors.push(message);
let processed = false;
instance._processNewFiles = async () => { processed = true; };
instance._initDropZone();

await dropHandler({
  preventDefault() {},
  dataTransfer: {
    files: [{ name: "documents", size: 0, type: "" }],
    items: [{
      kind: "file",
      webkitGetAsEntry: () => ({ isDirectory: true }),
    }],
  },
});

if (processed) throw new Error("Directory drop reached file processing");
if (errors.length !== 1 || errors[0] !== "Only individual files are supported") {
  throw new Error(`Unexpected directory error: ${JSON.stringify(errors)}`);
}
""",
    )


# @matrix direct-upload : aggregate-limit multipart-fallback partial-resume
def test_large_multi_file_retry_preserves_completed_direct_uploads(run_node):
    run_base_upload_check(
        run_node,
        """
const files = Array.from({ length: 6 }, (_, index) =>
  new File([`file-${index}`], `file-${index}.txt`, {
    type: "text/plain",
    lastModified: index + 1,
  }),
);
const instance = new BaseUpload({});
instance.inputName = "tool-files";
instance.route = "/tools/organize";
instance.fileInput = { element: { files } };
instance.showError = (message) => errors.push(message);

let sessionCalls = 0;
let uploadCalls = 0;
let failThird = true;
uploadElement.directUpload.createSession = async ({ file }) => {
  sessionCalls += 1;
  return {
    chunk_size: 8,
    session_url: `https://storage.example.test/${file.name}`,
    token: `token:${file.name}`,
  };
};
uploadElement.directUpload.upload = async ({ file }) => {
  uploadCalls += 1;
  if (failThird && file.name === "file-2.txt") {
    throw new Error("temporary upload failure");
  }
  return { generation: `${uploadCalls}`, name: `tmp/uploads/${file.name}` };
};

const first = await instance.prepareSubmit();
if (first !== false || instance.directUploads.length !== 2) {
  throw new Error("Large selection did not retain its completed uploads");
}
if (!errors[0]?.includes("file-2.txt")) {
  throw new Error(`Missing failed filename in retry error: ${errors[0]}`);
}

failThird = false;
const second = await instance.prepareSubmit();
if (second !== true || instance.directUploads.length !== 6) {
  throw new Error("Large selection did not complete on retry");
}
if (sessionCalls !== 7) {
  throw new Error(`Expected completed files to be reused; got ${sessionCalls} sessions`);
}

const submitted = new Map([["tool-files", "multipart"]]);
const data = {
  delete(key) { submitted.delete(key); },
  set(key, value) { submitted.set(key, value); },
};
instance.applyDirectUploads(data);
const records = JSON.parse(submitted.get("direct_uploads"));
if (records.length !== 6 || records.some((record) => "_fileSignature" in record)) {
  throw new Error("Internal retry metadata leaked into the submitted manifest");
}
if (submitted.has("tool-files")) {
  throw new Error("Multipart files remained after successful direct upload");
}
""",
    )
