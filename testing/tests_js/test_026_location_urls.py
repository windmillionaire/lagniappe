"""Node-backed checks for Location element read behavior."""


# @matrix location : encoding maps-url place-id
def test_location_maps_url_uses_search_contract_and_place_id(run_node):
    run_node(
        r"""
const fs = require("node:fs");
const vm = require("node:vm");

const context = {
  BaseElement: class {},
  console,
  ICONS: {},
  LocationBox: class {},
  primitives: {},
  STYLES: {},
  URL,
  URLSearchParams,
};
vm.createContext(context);

let source = fs.readFileSync("src/script/elements/location.mjs", "utf8");
source = source.replace(/^import .*;$/gm, "");
source = source.replace("export class LocationElement", "class LocationElement");
source += "\nglobalThis.mapsUrl = mapsUrl;";
vm.runInContext(source, context);

const resolved = new URL(context.mapsUrl({
  id: "place/id+1",
  name: "Cafe & Bar",
  address: "123 Main St, New Orleans, LA",
}));
if (resolved.origin !== "https://www.google.com") throw new Error("wrong Maps origin");
if (resolved.pathname !== "/maps/search/") throw new Error("wrong Maps action");
if (resolved.searchParams.get("api") !== "1") throw new Error("missing API contract");
if (resolved.searchParams.get("query") !== "Cafe & Bar, 123 Main St, New Orleans, LA") {
  throw new Error("query was not preserved and encoded");
}
if (resolved.searchParams.get("query_place_id") !== "place/id+1") {
  throw new Error("Place ID was not preserved and encoded");
}

const freeText = new URL(context.mapsUrl({ address: "10 Rue de l'Église #2" }));
if (freeText.searchParams.get("query") !== "10 Rue de l'Église #2") {
  throw new Error("free-text query was not preserved and encoded");
}
if (freeText.searchParams.has("query_place_id")) {
  throw new Error("free-text URL unexpectedly included a Place ID");
}
"""
    )


# @source src/script/elements/location.mjs::LocationElement.read
# @pair location:read-layout
def test_location_read_layout_only_grows_for_visible_details(run_node):
    run_node(
        r"""
const fs = require("node:fs");
const vm = require("node:vm");

class FakeElement {
  constructor(tagName) {
    this.tagName = tagName;
    this.children = [];
    this.dataset = {};
    this.className = "";
    this.classList = {
      add: (...classes) => {
        this.className = [this.className, ...classes].filter(Boolean).join(" ");
      },
    };
  }

  appendChild(child) {
    this.children.push(child);
    return child;
  }
}

const context = {
  BaseElement: class {
    constructor(renderer, schema, submission) {
      this.renderer = renderer;
      this.schema = schema;
      this.submission = submission;
      this._read = null;
    }
  },
  console,
  document: {
    createElement: (tagName) => new FakeElement(tagName),
  },
  LocationBox: class {},
  primitives: {},
  setIcon() {},
  STYLES: {
    form: { submission: { default: "single-line", grows: "multi-line" } },
    link: { default: "link" },
  },
  URL,
  URLSearchParams,
};
vm.createContext(context);

let source = fs.readFileSync("src/script/elements/location.mjs", "utf8");
source = source.replace(/^import .*;$/gm, "");
source = source.replace("export class LocationElement", "class LocationElement");
source += "\nglobalThis.LocationElement = LocationElement;";
vm.runInContext(source, context);

const render = (submission) =>
  new context.LocationElement({}, {}, submission).read;
const textContainer = (read) => read.children[0].children[1];

const addressOnly = render({ address: "1320 S Dixie Hwy, Coral Gables, FL" });
if (!addressOnly.className.startsWith("single-line")) {
  throw new Error(`Address-only location used ${addressOnly.className}`);
}
if (textContainer(addressOnly).children.length !== 1) {
  throw new Error("Address-only location rendered an empty detail row");
}

const duplicateName = render({
  name: "1320 S DIXIE HWY, CORAL GABLES, FL",
  address: "1320 S Dixie Hwy, Coral Gables, FL",
});
if (!duplicateName.className.startsWith("single-line")) {
  throw new Error(`Duplicate address name used ${duplicateName.className}`);
}
if (textContainer(duplicateName).children.length !== 1) {
  throw new Error("Duplicate address name rendered a redundant detail row");
}

const namedPlace = render({
  name: "Campus",
  address: "1320 S Dixie Hwy, Coral Gables, FL",
});
if (!namedPlace.className.startsWith("multi-line")) {
  throw new Error(`Named location used ${namedPlace.className}`);
}
if (textContainer(namedPlace).children.length !== 2) {
  throw new Error("Named location did not render its address detail row");
}
"""
    )
