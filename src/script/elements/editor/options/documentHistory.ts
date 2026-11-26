import { STYLES } from "../../../generated/styles.mjs";
import { Modal } from "../../../shared/modal.ts";
import { request } from "../../../shared/request.ts";
import { Dropdown, type DropdownItem } from "../../combobox/dropdown.ts";
import type { ToolSettings } from "../config.ts";
import { createMenuButton } from "../dropdowns.ts";
import type { Toolbar } from "../toolbar.ts";
import type { DocumentVersionEntry } from "../versions.ts";

interface VersionHistory {
	entries: DocumentVersionEntry[];
	unpinned_count: number;
}

interface StorageBackup extends DocumentVersionEntry {
	created: string;
}

interface DocumentBackups {
	entries: StorageBackup[];
	cursor?: string;
}

class DocumentHistoryButton {
	declare toolbar: Toolbar;
	declare active: boolean;
	declare button: HTMLButtonElement | null;
	declare _dropdown: Dropdown | null;

	constructor(toolbar: Toolbar) {
		this.toolbar = toolbar;
		this.active = false;
		this.button = null;
		this._dropdown = null;
		this._loadEntries = this._loadEntries.bind(this);
		this.refresh = this.refresh.bind(this);
	}

	init(settings: ToolSettings) {
		Object.assign(this, settings);
		this.button = createMenuButton(settings);

		this._dropdown = new Dropdown(this.button);
		this._dropdown.init({
			loadOptions: this._loadEntries,
			placement: "bottom-start",
			styles: {
				panel: `${STYLES.dropdown.panel} ${STYLES.editor.toolbar.portalIconContext} w-max max-w-[calc(100vw-0.625rem)]`,
			},
		});
	}

	show() {
		if (this.button) this.button.hidden = false;
	}

	async _loadEntries(): Promise<DropdownItem[]> {
		const endpoint = this.toolbar.endpoints?.history;
		if (!endpoint) return [];

		const response = await request.get<VersionHistory>(endpoint, {
			refresh: Date.now(),
		});
		if (!response?.ok) return [];

		const entries = response.entries || [];
		const items: DropdownItem[] = [
			{
				name: "Pin Version",
				icon: "pin",
				onClick: () => this.toolbar.openForm("pinVersion"),
			},
			{
				name: "Storage backups",
				closeOnClick: false,
				icon: "database",
				onClick: () => this._showBackups(),
			},
		];

		if ((response.unpinned_count ?? 0) > 0) {
			items.push({
				name: "Clear Unpinned Versions",
				icon: "delete",
				onClick: (option) => this._confirmClear(option),
			});
		}

		items.push(
			...entries.map((entry) => {
				const date = entry.created
					? new Date(entry.created).toLocaleString()
					: "";
				return {
					name: entry.pinned ? `${entry.name} — ${date}` : date,
					icon: entry.pinned ? "pin" : "history",
					onClick: () => this.toolbar.document.versions?.preview(entry),
				};
			}),
		);

		return items;
	}

	async refresh() {
		const items = await this._loadEntries();
		this._dropdown?.updateOptions(items);
	}

	async _confirmClear(trigger: HTMLElement) {
		const endpoint = this.toolbar.endpoints?.history;
		if (!endpoint) return;

		const modal = new Modal(this.toolbar.document.view, trigger);
		await modal.load(`${endpoint}/unpinned?refresh=${Date.now()}`);
		const deleteButton = modal.modal?.querySelector<HTMLButtonElement>(
			"[data-role='delete']",
		);
		const route = deleteButton?.dataset.route;
		if (!deleteButton || !route) return;

		deleteButton.addEventListener("click", async () => {
			deleteButton.disabled = true;
			const spinner = deleteButton.querySelector<HTMLElement>("#spinner");
			if (spinner) spinner.dataset.visible = "true";

			const response = await request.delete(route);
			if (!response?.ok) {
				deleteButton.disabled = false;
				if (spinner) spinner.dataset.visible = "false";
				return;
			}

			await modal.remove();
			await this.refresh();
		});
		(
			modal.modal?.querySelector<HTMLElement>("[lp-control='close']") ??
			deleteButton
		).focus();
	}

	async _showBackups(
		cursor: string | null = null,
		entries: StorageBackup[] = [],
	) {
		const response = await request.get<DocumentBackups>(
			`${this.toolbar.endpoints?.history}/backups`,
			{ ...(cursor ? { cursor } : {}), refresh: Date.now() },
		);
		if (!response?.ok) {
			this.toolbar.document.versions?.notice(
				response?.error || "Unable to list storage backups.",
			);
			return;
		}
		const loaded = [...entries, ...(response.entries || [])].sort((a, b) =>
			b.created.localeCompare(a.created),
		);
		const items: DropdownItem[] = loaded.map((entry) => ({
			name: `Storage backup — ${new Date(entry.created).toLocaleString()}`,
			icon: "database",
			onClick: () => this.toolbar.document.versions?.preview(entry),
		}));
		if (response.cursor)
			items.push({
				name: "Load more storage backups",
				closeOnClick: false,
				icon: "database",
				onClick: () => this._showBackups(response.cursor, loaded),
			});
		if (!items.length)
			this.toolbar.document.versions?.notice(
				"No retained storage backups are available for this document.",
			);
		items.unshift({
			name: "Back to pinned versions",
			closeOnClick: false,
			icon: "pin",
			onClick: () => this._showPins(),
		});
		this._dropdown?.updateOptions(items);
	}

	async _showPins() {
		await this.refresh();
	}

	destroy() {
		if (this._dropdown) {
			this._dropdown.destroy();
			this._dropdown = null;
		}
	}
}

export { DocumentHistoryButton as documentHistory };
