"""Node-backed checks for frontend view transition behavior."""

import textwrap

def run_transition_check(run_node, assertion: str):
    script = f"""
const fs = require("node:fs");
const vm = require("node:vm");

const capturedErrors = [];
const events = [];
let transitionStarts = 0;
let finishTransition = null;

const context = {{
  capturedErrors,
  clearTimeout,
  console,
  crypto,
  document: {{
    startViewTransition(callback) {{
      transitionStarts += 1;
      const updateCallbackDone = Promise.resolve().then(callback);
      const finished = new Promise((resolve) => {{
        finishTransition = resolve;
      }});
      return {{
        finished,
        ready: Promise.resolve(),
        updateCallbackDone,
      }};
    }},
  }},
  events,
  get transitionStarts() {{
    return transitionStarts;
  }},
  finishTransition() {{
    finishTransition?.();
  }},
  MutationObserver: class {{
    disconnect() {{}}
    observe() {{}}
  }},
  queueMicrotask,
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
const result = await withTransition(() => {
  events.push("outer-start");
  void withTransition(() => {
    events.push("inner");
  });
  events.push("outer-end");
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
if (events.join(",") !== "outer-start,inner,outer-end") {
  throw new Error(`Unexpected event order: ${events.join(",")}`);
}
""",
    )


# @features view-transition
# @dimensions update-completion animation-lifecycle queueing
def test_transition_resolves_after_update_without_waiting_for_animation(run_node):
    run_transition_check(
        run_node,
        """
let resolved = false;
const pending = withTransition(() => events.push("commit")).then(() => {
  resolved = true;
  events.push("resolved");
});
await pending;

if (!resolved || events.join(",") !== "commit,resolved") {
  throw new Error(`Transition waited for animation: ${events.join(",")}`);
}
context.finishTransition();
""",
    )


# @features view-transition
# @dimensions coalescing exact-once
def test_same_turn_commits_share_one_transition_and_run_once(run_node):
    run_transition_check(
        run_node,
        """
const first = withTransition(() => events.push("first"));
const second = withTransition(() => events.push("second"));
const results = await Promise.all([first, second]);

if (context.transitionStarts !== 1) {
  throw new Error(`Expected one coalesced transition, got ${context.transitionStarts}`);
}
if (events.join(",") !== "first,second") {
  throw new Error(`Unexpected commits: ${events.join(",")}`);
}
if (results.some((result) => result !== true)) {
  throw new Error(`Unexpected results: ${results.join(",")}`);
}
context.finishTransition();
""",
    )


# @features view-transition
# @dimensions ready-rejection exact-once
def test_ready_rejection_does_not_replay_commit(run_node):
    script = r'''
const fs = require("node:fs");
const vm = require("node:vm");
const capturedErrors = [];
let commits = 0;
const skipped = new Error("Transition was skipped");
const context = {
  capturedErrors,
  clearTimeout,
  console,
  crypto,
  document: {
    startViewTransition(callback) {
      const updateCallbackDone = Promise.resolve().then(callback);
      return {
        updateCallbackDone,
        ready: Promise.reject(skipped),
        finished: Promise.resolve(),
      };
    },
  },
  MutationObserver: class { disconnect() {} observe() {} },
  queueMicrotask,
  setTimeout,
};
vm.createContext(context);
let source = fs.readFileSync("src/script/shared/utilities.mjs", "utf8");
source = source.replace(
  'import { captureError, isSkippedViewTransitionError } from "./errors";',
  `
const captureError = (...args) => capturedErrors.push(args);
const isSkippedViewTransitionError = (error) => /skipped/i.test(error?.message || "");
`,
);
source = source.replaceAll("export const ", "const ");
source = source.replace("export function waitForAttribute", "function waitForAttribute");
source += "\nglobalThis.withTransition = withTransition;";
vm.runInContext(source, context);

(async () => {
  const result = await context.withTransition(() => { commits += 1; });
  await Promise.resolve();
  if (!result || commits !== 1) throw new Error(`Commit count: ${commits}`);
  if (capturedErrors.length !== 0) {
    throw new Error(`Skipped transition reported ${capturedErrors.length} errors`);
  }
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
'''
    run_node(script)
