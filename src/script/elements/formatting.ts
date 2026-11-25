import { STYLES } from "../generated/styles.mjs";
import { createIcon, iconDefinition, setIcon } from "../shared/icons.ts";

const ROUTES: Partial<Record<string, string>> = {
	task: "pages",
	model: "projects",
	project: "projects",
	page: "pages",
	category: "categories",
	form: "forms",
};

export interface EntityLabel {
	id?: string;
	kind?: string;
	index?: string;
	type?: string;
	name?: string;
	link?: boolean;
	parent?: unknown;
}

interface EntityParent {
	id?: string;
	kind?: string;
	name?: string;
}

function entityParent(value: unknown): EntityParent | null {
	if (!value || typeof value !== "object") return null;
	return {
		id: "id" in value && typeof value.id === "string" ? value.id : undefined,
		kind:
			"kind" in value && typeof value.kind === "string"
				? value.kind
				: undefined,
		name:
			"name" in value && typeof value.name === "string"
				? value.name
				: undefined,
	};
}

const date = (date: Date | string | null | undefined) => {
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

const time = (timeValue: string | null | undefined) => {
	if (!timeValue) return null;

	const [hours, minutes] = timeValue.split(":").map(Number);

	const period = hours >= 12 ? "PM" : "AM";
	const displayHours = hours === 0 ? 12 : hours > 12 ? hours - 12 : hours;

	return `${displayHours}:${minutes.toString().padStart(2, "0")} ${period}`;
};

const tel = (telValue: string | null | undefined) => {
	if (!telValue) return null;
	return telValue.replace(/(\d{3})(\d{3})(\d{4})/, "($1) $2-$3");
};

const url = (data: EntityLabel) => {
	let url = null;
	const parent = entityParent(data.parent);
	if (data.kind === "model" && parent) {
		url = new URL(
			`projects/${parent.id}/status/${data.id}`,
			window.location.origin,
		);
		url.searchParams.set("completed", "false");
	} else if (data.kind === "task" && parent) {
		url = new URL(
			`${ROUTES[parent.kind ?? ""]}/${parent.id}`,
			window.location.origin,
		);
		url.searchParams.set("task", String(data.id));
	} else if (data.kind === "user") {
		url = new URL(`pages/${data.id}`, window.location.origin);
	} else if (data.kind === "group") {
		url = new URL("users/index", window.location.origin);
		url.searchParams.set("group", String(data.id));
	} else {
		url = new URL(
			`${ROUTES[data.kind || data.index || ""]}/${data.id}`,
			window.location.origin,
		);
	}

	return url;
};

const email = (email: string) => {
	const emailElement = document.createElement("a");
	emailElement.href = `mailto:${email}`;
	emailElement.textContent = email;
	emailElement.className = `${STYLES.link.emphasized}`;
	return emailElement;
};

const icon = (data: { icon?: string | null; kind?: string | null }) => {
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
 */
const iconLabel = ({
	icon: iconName,
	kind = null,
	content,
	classes = "",
	iconClasses = "",
}: {
	icon?: string | null;
	kind?: string | null;
	content?: Node | string | null;
	classes?: string;
	iconClasses?: string;
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

const name = (data: EntityLabel) => {
	const kind = data.kind || data.index || data.type;
	const container = document.createElement("span");
	container.className = STYLES.entity.name.wrapper;
	const name = document.createElement(data.link ? "a" : "span");
	name.dataset.kind = String(kind);
	name.textContent = data.name ?? null;
	if (name.tagName === "A") {
		name.setAttribute("href", url(data).href);
		name.className = `${STYLES.link.emphasized}`;
	} else {
		name.className = "text-kind-default font-semibold";
	}

	const parentDetails = entityParent(data.parent);
	if (parentDetails) {
		const parent = container.appendChild(document.createElement("span"));
		parent.dataset.kind = String(parentDetails.kind);
		parent.className = `text-kind-default font-medium ${STYLES.entity.name.parent}`;

		const parentName = parent.appendChild(document.createElement("span"));
		parentName.textContent = parentDetails.name ?? null;

		const separator = parent.appendChild(document.createElement("span"));
		separator.setAttribute("aria-hidden", "true");
		separator.className = STYLES.entity.name.separator;
		separator.textContent = "/";

		container.appendChild(document.createElement("wbr"));
	}

	container.appendChild(name);

	return container;
};

const text = (data: { kind?: string; text?: string | null }) => {
	const { kind = "default", text } = data;
	const textElement = document.createElement("span");
	textElement.dataset.kind = kind;
	textElement.className = "text-kind-default";
	textElement.textContent = text ?? null;
	return textElement;
};

const working = (button: HTMLElement, newText: string) => {
	const iconWrapper = document.createElement("span");
	iconWrapper.dataset.role = "icon";
	iconWrapper.dataset.visible = "true";
	iconWrapper.appendChild(createIcon("spinner"));

	const textElement = document.createElement("span");
	textElement.dataset.role = "text";
	textElement.textContent = newText;

	button.replaceChildren(iconWrapper, textElement);
};

export const formatting = {
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
