const ROUTE_LINK_CLASSES = new Set([
	"text-category",
	"text-file",
	"text-form",
	"text-page",
	"text-project",
	"text-task",
	"text-user",
]);

// @testable false
// @covered-by src/script/elements/editor/extensions/linkAttributes.mjs::normalizeLinkAttributes
// @reason helper-owned-by-link-normalizer
const currentLocation = () => globalThis.window?.location ?? null;

// @testable false
// @covered-by src/script/elements/editor/extensions/linkAttributes.mjs::normalizeLinkAttributes
// @reason helper-owned-by-link-normalizer
const cleanClassName = (className) => {
	const classes = String(className || "")
		.split(/\s+/)
		.filter(Boolean)
		.filter((value) => !ROUTE_LINK_CLASSES.has(value));

	return classes.length > 0 ? classes.join(" ") : null;
};

// @testable false
// @covered-by src/script/elements/editor/extensions/linkAttributes.mjs::normalizeLinkAttributes
// @reason helper-owned-by-link-normalizer
const internalLinkDetails = (href) => {
	const location = currentLocation();
	const value = String(href || "").trim();

	if (!location || !value) return null;

	if (value.startsWith("#") || value.startsWith("?")) {
		return { href: value };
	}

	try {
		const url = new URL(value, location.href);
		if (url.origin !== location.origin) return null;

		const absolute = /^[a-z][a-z0-9+.-]*:/i.test(value);
		const rootRelative = value.startsWith("/");
		const protocolRelative = value.startsWith("//");
		const nextHref =
			absolute || rootRelative || protocolRelative
				? `${url.pathname}${url.search}${url.hash}`
				: value;

		return {
			href: nextHref || "/",
		};
	} catch (_error) {
		return null;
	}
};

/**
 * @testable true
 * @tests tests_e2e/004_projects/test_004e_document_forms.py::test_internal_links_normalize_paste_and_popover_navigation
 * @features editor
 * @dimensions link internal-link
 */
export const normalizeLinkAttributes = (attributes = {}) => {
	const details = internalLinkDetails(attributes.href);

	if (!details) {
		return {
			...attributes,
			href: attributes.href ? String(attributes.href).trim() : attributes.href,
			class: cleanClassName(attributes.class),
		};
	}

	return {
		...attributes,
		href: details.href,
		target: null,
		rel: null,
		class: cleanClassName(attributes.class),
	};
};
