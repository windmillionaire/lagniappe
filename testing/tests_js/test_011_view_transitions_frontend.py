"""Node-backed checks for frontend view transition behavior."""

import textwrap

def run_transition_check(run_node, assertion: str):
    script = f"""
const fs = require("node:fs");
const vm = require("node:vm");

const capturedErrors = [];
const events = [];
let transitionStarts = 0;

const context = {{
  capturedErrors,
  clearTimeout,
  console,
  crypto,
  document: {{
    startViewTransition(callback) {{
      transitionStarts += 1;
      const finished = Promise.resolve().then(callback);
      return {{
        finished,
        ready: Promise.resolve(),
      }};
    }},
  }},
  events,
  get transitionStarts() {{
    return transitionStarts;
  }},
  MutationObserver: class {{
    disconnect() {{}}
    observe() {{}}
  }},
  setTimeout,
}};

vm.createContext(context);
let source = fs.readFileSync("src/script/shared/utilities.mjs", "utf8");
source = source.replace(
  'import {{ captureError, isSkippedViewTransitionError }} from "./errors";',
  `
const captureError = (...args) => capturedErrors.push(args);
const isSkippedViewTransitionError = () => false;
`,
);
source = source.replaceAll("export const ", "const ");
source = source.replace("export function waitForAttribute", "function waitForAttribute");
source += "\\nglobalThis.withTransition = withTransition;";
vm.runInContext(source, context);
const withTransition = context.withTransition;

(async () => {{
{textwrap.indent(assertion, "  ")}
}})().catch((error) => {{
  console.error(error);
  process.exit(1);
}});
"""

    run_node(script)


# @features view-transition
# @dimensions nested-callback error-reporting
def test_nested_transition_joins_active_transition_without_error_report(run_node):
    run_transition_check(
        run_node,
        """
const result = await withTransition(async () => {
  events.push("outer-start");
  const nestedResult = await withTransition(() => {
    events.push("inner");
  });
  events.push(`nested:${nestedResult}`);
});

if (result !== true) {
  throw new Error(`Expected outer transition to complete, got ${result}`);
}
if (context.transitionStarts !== 1) {
  throw new Error(`Expected one browser transition, got ${context.transitionStarts}`);
}
if (capturedErrors.length !== 0) {
  throw new Error(`Nested transition reported ${capturedErrors.length} errors`);
}
if (events.join(",") !== "outer-start,inner,nested:true") {
  throw new Error(`Unexpected event order: ${events.join(",")}`);
}
""",
    )
