"""Node-backed checks for targeted Home foreground reconciliation."""


# @features home polling
# @dimensions foreground mounted-scope targeted-refresh lazy-widget
def test_home_polling_subscribes_loaded_widgets_and_refreshes_only_owner(run_node):
    run_node(
        r"""
const fs = require("node:fs");
const vm = require("node:vm");

const descriptors = new Map();
const hooks = new Map();
const removed = [];
const refreshed = [];
const coordinator = {
  subscribe(descriptor, options) {
    descriptors.set(descriptor.id, descriptor);
    hooks.set(descriptor.id, options);
    return () => {
      removed.push(descriptor.id);
      descriptors.delete(descriptor.id);
      hooks.delete(descriptor.id);
    };
  },
};
class Core {
  constructor(elt) {
    this.elt = elt;
    this.components = {};
    this.PollingCoordinator = null;
  }
  async prefetch() {}
  async reconcilePollingSubscriptions() {}
  destroy() { this.coreDestroyed = true; }
}
const context = {
  console,
  Core,
  withTransition(callback) { return callback(); },
};
context.globalThis = context;
vm.createContext(context);
let source = fs.readFileSync("src/script/views/home.mjs", "utf8");
source = source.replace(/^import .*;\n/gm, "");
source = source.replace("export default class Home", "class Home");
source += "\nglobalThis.Home = Home;";
vm.runInContext(source, context);

const notes = {
  name: "HomeActivityList",
  loaded: true,
  route: "/l/get/notes",
  target: { dataset: { pollRevision: "notes-1" } },
  async refresh() { refreshed.push("notes"); },
};
const tasks = {
  name: "HomeTaskList",
  loaded: true,
  route: "/l/get/tasks",
  target: { dataset: { pollRevision: "tasks-1" } },
  async refresh() { refreshed.push("tasks"); },
};
const pages = {
  name: "HomePageList",
  loaded: false,
  route: "/l/get/pages",
  target: { dataset: { pollRevision: "pages-1" } },
  async refresh() { refreshed.push("pages"); },
};
const component = { widgets: { notes, tasks, pages } };
const home = new context.Home({});
home.PollingCoordinator = coordinator;
home.components = { dashboard: component };
home.load = async (_component, route) => ({
  updated: true,
  pollChannel: route.endsWith("notes") ? "home-notes" : "tasks",
  pollRevision: `${route}-next`,
});

(async () => {
  home._syncHomePollingSubscriptions();
  if (descriptors.size !== 2 || descriptors.has("home:channel:pages")) {
    throw new Error("Home subscribed an unloaded lazy widget");
  }
  const notesDescriptor = descriptors.get("home:channel:home-notes");
  const notesHook = hooks.get("home:channel:home-notes");
  if (notesDescriptor?.revision !== "notes-1" ||
      notesHook?.mode !== "foreground" ||
      notesHook?.initial !== "scheduled") {
    throw new Error("Home notes did not use its rendered foreground cursor");
  }
  await notesHook.onResult({ status: "changed" });
  if (refreshed.join(",") !== "notes") {
    throw new Error(`Changed notes refreshed unrelated widgets: ${refreshed}`);
  }

  pages.loaded = true;
  home._syncHomePollingSubscriptions();
  if (!descriptors.has("home:channel:pages")) {
    throw new Error("A loaded lazy widget did not acquire its foreground channel");
  }
  tasks.loaded = false;
  home._syncHomePollingSubscriptions();
  if (!removed.includes("home:channel:tasks")) {
    throw new Error("An unloaded Home widget kept its channel mounted");
  }

  home.destroy();
  if (!home.coreDestroyed || descriptors.size !== 0) {
    throw new Error("Home polling subscriptions survived view teardown");
  }
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
"""
    )
