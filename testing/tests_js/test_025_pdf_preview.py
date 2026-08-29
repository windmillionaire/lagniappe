"""Node-backed checks for PDF preview lifecycle behavior."""


def run_pdf_preview_check(run_node, assertion: str):
    script = f"""
const fs = require("node:fs");
const vm = require("node:vm");

const context = {{
  console,
  document: {{
    querySelector() {{
      return null;
    }},
  }},
  pdfjs: {{
    PDFDataRangeTransport: class {{}},
  }},
  setIcon() {{}},
}};

vm.createContext(context);
let source = fs.readFileSync("src/script/widgets/filePdfPreview.mjs", "utf8");
source = source.replace(/^import .*;\\n/gm, "");
source = `
const STYLES = {{
  editor: {{
    toolbar: {{ section: "", tool: "", tools: "" }},
  }},
}};
const primitives = {{}};
${{source}}
`;
source = source.replace("export class PDFPreview", "class PDFPreview");
source += "\\nglobalThis.PDFPreview = PDFPreview;";
vm.runInContext(source, context);
const PDFPreview = context.PDFPreview;

(async () => {{
{assertion}
}})().catch((error) => {{
  console.error(error);
  process.exit(1);
}});
"""

    run_node(script)


# @matrix file : loading-state pdf-preview view-transition
def test_pdf_preview_loading_does_not_block_widget_reconciliation(run_node):
    run_pdf_preview_check(
        run_node,
        """
let status = null;
const preview = new PDFPreview({
  target: { dataset: {} },
  visible: true,
});
preview._setStatus = (value) => {
  status = value;
};
preview._loadDocument = () => new Promise(() => {});

const result = preview.postreconcile();

if (result?.then) {
  throw new Error("PDF loading must not extend the view-transition callback");
}
if (!preview._started) {
  throw new Error("PDF loading did not start");
}
if (status !== "Loading preview") {
  throw new Error(`Expected loading chrome before reconciliation returned, got ${status}`);
}
""",
    )


# @matrix file : pdf-preview revisit view-transition
def test_pdf_preview_revisit_does_not_await_pending_rasterization(run_node):
    run_pdf_preview_check(
        run_node,
        """
let renderCalls = 0;
const preview = new PDFPreview({
  target: { dataset: {} },
  visible: true,
});
preview._started = true;
preview._renderPage = () => {
  renderCalls += 1;
  return new Promise(() => {});
};

const result = preview.postreconcile();

if (result?.then) {
  throw new Error("Pending rasterization must not extend the view-transition callback");
}
if (renderCalls !== 1) {
  throw new Error(`Expected one current-page render, got ${renderCalls}`);
}
""",
    )
