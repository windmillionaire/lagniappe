import { FacetsBox } from "../../elements/combobox/facets.ts";
import { withTransition } from "../../shared/transitions.ts";
import type { FacetsUpdatedEvent, FormControlOptions } from "./loader.ts";

/**
 * Enhances server-rendered permission fields without owning a form lifecycle.
 */
export default class PermissionSections {
	declare private root: HTMLElement;
	declare private readonly: boolean;
	declare private onChange: () => void;
	declare private selects: Map<HTMLElement, FacetsBox>;
	declare private _destroyed: boolean;

	constructor(
		root: HTMLElement,
		{ readonly = false, onChange = () => {} }: FormControlOptions = {},
	) {
		this.root = root;
		this.readonly = readonly;
		this.onChange = onChange;
		this.selects = new Map();
		this._destroyed = false;
		this._updated = this._updated.bind(this);
		this._change = this._change.bind(this);
	}

	async init() {
		this.setVisibility();
		if (this.readonly) return;
		for (const section of this.root.querySelectorAll<HTMLElement>(
			"[data-section]",
		)) {
			const input = section.querySelector<HTMLInputElement>(
				"[data-role='permission-picker']",
			);
			if (!input) continue;
			const select = new FacetsBox(
				input,
				section.dataset.section === "projects" ? { models: false } : {},
			);
			this.selects.set(section, select);
			await select.init();
			if (this._destroyed) return;
		}
		this.root.addEventListener("updated", this._updated);
		this.root.addEventListener("change", this._change);
	}

	_updated(event: Event) {
		const target = event.target;
		if (!(target instanceof Element)) return;
		const section = target.closest<HTMLElement>("[data-section]");
		if (!section) return;
		const select = this.selects.get(section);
		if (!select || target !== select.element) return;
		const entry = Object.values(
			(event as FacetsUpdatedEvent).detail.options,
		)[0];
		if (!entry?.id) return;
		void withTransition(
			() => {
				if (this._destroyed) return;
				const list = section.querySelector("[data-role='permission-list']");
				if (!list) throw new Error("Permission list is missing");
				const exists = Array.from(
					list.querySelectorAll<HTMLInputElement>("input[type='radio']"),
				).some((input) => input.name === entry.id);
				if (!exists) {
					const item = section
						.querySelector("template")
						?.content.firstElementChild?.cloneNode(true);
					if (!(item instanceof Element))
						throw new Error("Permission row template is missing");
					const name = item.querySelector("[data-role='permission-name']");
					if (!name) throw new Error("Permission name field is missing");
					name.textContent = entry.label || entry.name;
					for (const input of item.querySelectorAll<HTMLInputElement>(
						"input[type='radio']",
					))
						input.name = entry.id;
					list.append(item);
					this.onChange();
				}
				select.clear({ notify: false });
				this.setVisibility();
			},
			{ label: "permissions:add-entry" },
		);
	}

	_change(event: Event) {
		const target = event.target;
		if (!(target instanceof Element) || !target.closest("[data-section]"))
			return;
		void withTransition(
			() => {
				if (this._destroyed) return;
				if (
					target instanceof HTMLInputElement &&
					target.matches("[data-role='remove-permission']") &&
					!target.checked
				) {
					target.closest("li")?.remove();
					this.onChange();
				}
				this.setVisibility();
			},
			{ label: "permissions:change" },
		);
	}

	setVisibility() {
		const sections = new Map(
			Array.from(
				this.root.querySelectorAll<HTMLElement>("[data-section]"),
				(section) => [section.dataset.section ?? "", section],
			),
		);
		const level = (name: string) =>
			sections
				.get(name)
				?.querySelector<HTMLInputElement>("input[type='radio']:checked")?.value;
		const publicOff = level("public") === "FALSE";
		const modelLevel = level("models");
		const userLevel = level("users");
		const models = modelLevel && modelLevel !== "NONE";
		const users = userLevel && !["NONE", "VIEW"].includes(userLevel);
		const groups = !!sections
			.get("groups")
			?.querySelector("[data-role='permission-list'] li");
		for (const [name, section] of sections) {
			section.dataset.visible = String(
				!(
					(publicOff && name !== "public") ||
					(models && ["categories", "projects", "pages"].includes(name)) ||
					(name === "groups" && users) ||
					(name === "users" && groups)
				),
			);
		}
	}

	destroy() {
		if (this._destroyed) return;
		this._destroyed = true;
		this.root.removeEventListener("updated", this._updated);
		this.root.removeEventListener("change", this._change);
		for (const select of this.selects.values()) select.destroy();
		this.selects.clear();
	}
}
