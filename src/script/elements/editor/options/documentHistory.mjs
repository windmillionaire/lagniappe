import { STYLES } from "styles";
import { Modal, request } from "../../../shared";
import { setIcon } from "../../../shared/icons";
import { Dropdown } from "../../combobox/dropdown";

/**
 * @testable true
 * @tests tests_e2e/004_projects/test_004h_document_history.py::test_document_history_created_on_save
 * @tests tests_e2e/004_projects/test_004h_document_history.py::test_document_history_restore
 * @features editor
 * @dimensions history-list history-restore
 */
class DocumentHistoryButton {
	constructor(toolbar) {
		this.toolbar = toolbar;
		this.active = false;
		this.button = document.createElement("button");
		this._dropdown = null;
		this._restore = this._restore.bind(this);
		this._loadEntries = this._loadEntries.bind(this);
		this.refresh = this.refresh.bind(this);
	}

	init(settings) {
		Object.assign(this, settings);
		this.button.title = this.title;
		this.button.className = `${STYLES.editor.toolbar.tool}`;

		const iconElement = document.createElement("span");
		setIcon(iconElement, this.icon, STYLES.editor.toolbar.historyIcon);
		this.button.replaceChildren(iconElement);

		this._dropdown = new Dropdown(this.button);
		this._dropdown.init({
			loadOptions: this._loadEntries,
			placement: "bottom-end",
			styles: {
				panel: `${STYLES.dropdown.panel} ${STYLES.editor.toolbar.portalIconContext}`,
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
					onClick: () => this._restore(entry.key),
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

	async _restore(historyKey) {
		const endpoint = this.toolbar.endpoints.history;
		const response = await request.get(`${endpoint}/${historyKey}`);
		if (!response?.markup) return;

		const doc = this.toolbar.document;
		doc.editor.commands.setContent(response.markup, {
			emitUpdate: false,
		});
	}

	destroy() {
		if (this._dropdown) {
			this._dropdown.destroy();
			this._dropdown = null;
		}
	}
}

export { DocumentHistoryButton as documentHistory };
