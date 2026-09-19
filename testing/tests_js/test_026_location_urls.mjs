import assert from "node:assert/strict";
import { test } from "node:test";
import { createBrowser } from "../utility/js/environment.mjs";

async function setup(t) {
	createBrowser(t);
	const [{ LocationElement }, { STYLES }] = await Promise.all([
		import("../../src/script/elements/location.mjs"),
		import("../../src/script/generated/styles.mjs"),
	]);
	const render = (submission) => new LocationElement({}, {}, submission).read;
	return { render, STYLES };
}

/** @matrix location : encoding maps-url place-id */
test("test_location_maps_url_uses_search_contract_and_place_id", async (t) => {
	const { render } = await setup(t);
	const resolved = new URL(
		render({
			id: "place/id+1",
			name: "Cafe & Bar",
			address: "123 Main St, New Orleans, LA",
		}).querySelector("a").href,
	);
	assert.equal(resolved.origin, "https://www.google.com", "wrong Maps origin");
	assert.equal(resolved.pathname, "/maps/search/", "wrong Maps action");
	assert.equal(resolved.searchParams.get("api"), "1", "missing API contract");
	assert.equal(
		resolved.searchParams.get("query"),
		"Cafe & Bar, 123 Main St, New Orleans, LA",
		"query was not preserved and encoded",
	);
	assert.equal(
		resolved.searchParams.get("query_place_id"),
		"place/id+1",
		"Place ID was not preserved and encoded",
	);

	const freeText = new URL(
		render({ address: "10 Rue de l'Église #2" }).querySelector("a").href,
	);
	assert.equal(
		freeText.searchParams.get("query"),
		"10 Rue de l'Église #2",
		"free-text query was not preserved and encoded",
	);
	assert.equal(
		freeText.searchParams.has("query_place_id"),
		false,
		"free-text URL unexpectedly included a Place ID",
	);
});

/**
 * @source src/script/elements/location.mjs::LocationElement.read
 * @pair location:read-layout
 */
test("test_location_read_layout_only_grows_for_visible_details", async (t) => {
	const { render, STYLES } = await setup(t);
	const textContainer = (read) => read.children[0].children[1];

	const addressOnly = render({
		address: "1320 S Dixie Hwy, Coral Gables, FL",
	});
	assert.ok(
		addressOnly.className.startsWith(STYLES.form.submission.default),
		`Address-only location used ${addressOnly.className}`,
	);
	assert.equal(
		textContainer(addressOnly).children.length,
		1,
		"Address-only location rendered an empty detail row",
	);

	const duplicateName = render({
		name: "1320 S DIXIE HWY, CORAL GABLES, FL",
		address: "1320 S Dixie Hwy, Coral Gables, FL",
	});
	assert.ok(
		duplicateName.className.startsWith(STYLES.form.submission.default),
		`Duplicate address name used ${duplicateName.className}`,
	);
	assert.equal(
		textContainer(duplicateName).children.length,
		1,
		"Duplicate address name rendered a redundant detail row",
	);

	const namedPlace = render({
		name: "Campus",
		address: "1320 S Dixie Hwy, Coral Gables, FL",
	});
	assert.ok(
		namedPlace.className.startsWith(STYLES.form.submission.grows),
		`Named location used ${namedPlace.className}`,
	);
	assert.equal(
		textContainer(namedPlace).children.length,
		2,
		"Named location did not render its address detail row",
	);
});
