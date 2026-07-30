/*! Third-party licenses: /third-party-licenses.txt */
import { j as createIcon, S as STYLES, y as iconDefinition, s as setIcon } from './shared.js?v=bda9a134';

const ROUTES = {
	task: "pages",
	model: "projects",
	project: "projects",
	page: "pages",
	category: "categories",
	form: "forms",
};

/**
 * @testable infrastructure
 */
const date = (date) => {
	if (!date) return "";
	if (typeof date === "string") {
		// Append time to avoid UTC interpretation of date-only strings
		date = new Date(`${date}T00:00:00`);
	}
	return date.toLocaleDateString("en-US", {
		month: "short",
		day: "numeric",
		year: "numeric",
	});
};

/**
 * @testable infrastructure
 */
const time = (timeValue) => {
	if (!timeValue) return null;

	const [hours, minutes] = timeValue.split(":").map(Number);

	const period = hours >= 12 ? "PM" : "AM";
	const displayHours = hours === 0 ? 12 : hours > 12 ? hours - 12 : hours;

	return `${displayHours}:${minutes.toString().padStart(2, "0")} ${period}`;
};

/**
 * @testable infrastructure
 */
const tel = (telValue) => {
	if (!telValue) return null;
	return telValue.replace(/(\d{3})(\d{3})(\d{4})/, "($1) $2-$3");
};

/**
 * @testable infrastructure
 */
/**
 * @testable true
 * @tests tests_js/test_023_entity_name_formatting.py::test_group_name_uses_canonical_user_index_url
 * @features user-groups
 * @dimensions query-route
 */
const url = (data) => {
	let url = null;
	if (data.kind === "model" && data.parent) {
		url = new URL(
			`${ROUTES[data.parent.kind]}/${data.parent.id}`,
			window.location.origin,
		);
	} else if (data.kind === "task" && data.parent) {
		url = new URL(
			`${ROUTES[data.parent.kind]}/${data.parent.id}`,
			window.location.origin,
		);
		url.searchParams.set("task", data.id);
	} else if (data.kind === "user") {
		url = new URL(`pages/${data.id}`, window.location.origin);
	} else if (data.kind === "group") {
		url = new URL("users/index", window.location.origin);
		url.searchParams.set("group", data.id);
	} else {
		url = new URL(
			`${ROUTES[data.kind || data.index]}/${data.id}`,
			window.location.origin,
		);
	}

	return url;
};

/**
 * @testable infrastructure
 */
const email = (email) => {
	const emailElement = document.createElement("a");
	emailElement.href = `mailto:${email}`;
	emailElement.textContent = email;
	emailElement.className = `${STYLES.link.emphasized}`;
	return emailElement;
};

/**
 * @testable infrastructure
 */
const icon = (data) => {
	if (data.icon || data.kind) {
		const iconElement = document.createElement("span");
		iconElement.dataset.kind = data.kind || "default";
		setIcon(iconElement, data.icon || data.kind, "text-kind-default");
		return iconElement;
	}
	return null;
};

/**
 * Keep a decorative leading icon on the first line without reserving an
 * icon-sized column for every wrapped line of its label.
 *
 * @testable infrastructure
 */
const iconLabel = ({
	icon: iconName,
	kind = null,
	content,
	classes = "",
	iconClasses = "",
}) => {
	const container = document.createElement("span");
	container.className = `${STYLES.iconLabel.wrapper} ${classes}`.trim();

	if (iconName && iconDefinition(iconName)) {
		const iconElement = document.createElement("span");
		if (kind) iconElement.dataset.kind = kind;
		setIcon(
			iconElement,
			iconName,
			`${STYLES.iconLabel.icon} ${iconClasses}`.trim(),
		);
		container.appendChild(iconElement);
	}

	if (typeof content === "string") {
		container.appendChild(document.createTextNode(content));
	} else if (content) {
		container.appendChild(content);
	}

	return container;
};

/**
 * @testable true
 * @tests tests_js/test_023_entity_name_formatting.py::test_formatting_name_uses_a_text_separator_and_shared_wrapping_structure
 * @tests tests_js/test_023_entity_name_formatting.py::test_recent_combobox_results_reuse_shared_parent_name_formatting
 * @pair entity-name:accessibility
 * @pair entity-name:parent-separator
 * @pair entity-name:wrapping
 */
const name = (data) => {
	const kind = data.kind || data.index || data.type;
	const container = document.createElement("span");
	container.className = STYLES.entity.name.wrapper;
	const name = document.createElement(data.link ? "a" : "span");

	if (data.link) {
		name.href = url(data);
		name.dataset.kind = kind;
		name.className = `${STYLES.link.emphasized}`;
		name.textContent = data.name;
	} else {
		name.dataset.kind = kind;
		name.className = "text-kind-default font-semibold";
		name.textContent = data.name;
	}

	if (data.parent) {
		const parent = container.appendChild(document.createElement("span"));
		parent.dataset.kind = data.parent.kind;
		parent.className = `text-kind-default font-medium ${STYLES.entity.name.parent}`;

		const parentName = parent.appendChild(document.createElement("span"));
		parentName.textContent = data.parent.name;

		const separator = parent.appendChild(document.createElement("span"));
		separator.setAttribute("aria-hidden", "true");
		separator.className = STYLES.entity.name.separator;
		separator.textContent = "/";

		container.appendChild(document.createElement("wbr"));
	}

	container.appendChild(name);

	return container;
};

/**
 * @testable infrastructure
 */
const text = (data) => {
	const { kind = "default", text } = data;
	const textElement = document.createElement("span");
	textElement.dataset.kind = kind;
	textElement.className = "text-kind-default";
	textElement.textContent = text;
	return textElement;
};

/**
 * @testable infrastructure
 */
const working = (button, newText) => {
	const iconWrapper = document.createElement("span");
	iconWrapper.dataset.role = "icon";
	iconWrapper.dataset.visible = "true";
	iconWrapper.appendChild(createIcon("spinner"));

	const textElement = document.createElement("span");
	textElement.dataset.role = "text";
	textElement.textContent = newText;

	button.replaceChildren(iconWrapper, textElement);
};

const formatting = {
	date,
	time,
	tel,
	url,
	email,
	icon,
	iconLabel,
	name,
	text,
	working,
};

export { formatting as f };
