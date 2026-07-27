"""Node-backed checks for Location element Google Maps URLs."""


# @features location
# @dimensions maps-url place-id encoding
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
