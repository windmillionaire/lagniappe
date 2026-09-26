import { STYLES } from "../../../generated/styles.mjs";
import { Modal } from "../../../shared/modal.mjs";
import { request } from "../../../shared/request.mjs";
import { Dropdown } from "../../combobox/dropdown.mjs";
import { createMenuButton } from "../dropdowns.mjs";

/**
 * @testable true
 * @tests tests_e2e/004_projects/test_004h_document_history.py::test_document_saves_do_not_create_automatic_history
 * @tests tests_e2e/004_projects/test_004h_document_history.py::test_document_history_restore
 * @tests tests_e2e/004_projects/test_004h_document_history.py::test_pin_and_clear_document_history
 * @matrix editor : history-list history-positioning history-restore
 */
class DocumentHistoryButton {
	constructor(toolbar) {
		this.toolbar = toolbar;
		this.active = false;
		this.button = null;
		this._dropdown = null;
		this._loadEntries = this._loadEntries.bind(this);
		this.refresh = this.refresh.bind(this);
	}

	init(settings) {
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
		this.button.hidden = false;
	}

	async _loadEntries() {
		const endpoint = this.toolbar.endpoints.history;
		if (!endpoint) return [];

		const response = await request.get(endpoint, { refresh: Date.now() });
		if (!response?.ok) return [];

		const entries = response.entries || [];
		const items = [
			{
				name: "Pin Version",
				icon: "pin",
				onClick: () => this.toolbar.openForm("pinVersion"),
			},
			{
				name: "Storage backups",
				closeOnClick: false,
				icon: "history",
				onClick: () => this._showBackups(),
			},
		];

		if (response.unpinned_count > 0) {
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
					onClick: () => this.toolbar.document.versions.preview(entry),
				};
			}),
		);

		return items;
	}

	async refresh() {
		const items = await this._loadEntries();
		this._dropdown?.updateOptions(items);
	}

	async _confirmClear(trigger) {
		const endpoint = this.toolbar.endpoints.history;
		if (!endpoint) return;

		const modal = new Modal(this.toolbar.document.view, trigger);
		await modal.load(`${endpoint}/unpinned?refresh=${Date.now()}`);
		const deleteButton = modal.modal?.querySelector("[data-role='delete']");
		if (!deleteButton) return;

		deleteButton.addEventListener("click", async () => {
			deleteButton.disabled = true;
			const spinner = deleteButton.querySelector("#spinner");
			if (spinner) spinner.dataset.visible = "true";

			const response = await request.delete(deleteButton.dataset.route);
			if (!response?.ok) {
				deleteButton.disabled = false;
				if (spinner) spinner.dataset.visible = "false";
				return;
			}

			await modal.remove();
			await this.refresh();
		});
		deleteButton.focus();
	}

	async _showBackups(cursor = null, entries = []) {
		const response = await request.get(
			`${this.toolbar.endpoints.history}/backups`,
			{ ...(cursor ? { cursor } : {}), refresh: Date.now() },
		);
		if (!response?.ok) {
			this.toolbar.document.versions.notice(
				response?.error || "Unable to list storage backups.",
			);
			return;
		}
		const loaded = [...entries, ...(response.entries || [])].sort((a, b) =>
			b.created.localeCompare(a.created),
		);
		const items = loaded.map((entry) => ({
			name: `Storage backup — ${new Date(entry.created).toLocaleString()}`,
			icon: "history",
			onClick: () => this.toolbar.document.versions.preview(entry),
		}));
		if (response.cursor)
			items.push({
				name: "Load more storage backups",
				closeOnClick: false,
				icon: "history",
				onClick: () => this._showBackups(response.cursor, loaded),
			});
		if (!items.length)
			this.toolbar.document.versions.notice(
				"No retained storage backups are available for this document.",
			);
		items.unshift({
			name: "Back to pinned versions",
			closeOnClick: false,
			icon: "pin",
			onClick: () => this._showPins(),
		});
		this._dropdown.updateOptions(items);
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
