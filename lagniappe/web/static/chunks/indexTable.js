/*! Third-party licenses: /third-party-licenses.txt */
import { B as BaseTable } from './baseTable.js?v=b276e1c2';
import { c as captureError } from './foundation.js?v=b276e1c2';
import './styles.js?v=b276e1c2';
import './icons.js?v=b276e1c2';
import './primitives.js?v=b276e1c2';
import './table.js?v=b276e1c2';
import './baseElement.js?v=b276e1c2';
import './checkbox.js?v=b276e1c2';
import './input.js?v=b276e1c2';
import './formatting.js?v=b276e1c2';
import './link.js?v=b276e1c2';
import './facets.js?v=b276e1c2';
import './remote.js?v=b276e1c2';
import './queryLifecycle.js?v=b276e1c2';
import './combobox.js?v=b276e1c2';
import './results.js?v=b276e1c2';
import './storage.js?v=b276e1c2';
import './submitter.js?v=b276e1c2';
import './upstreamUnavailable.js?v=b276e1c2';
import './connectivity.js?v=b276e1c2';
import './loader.js?v=b276e1c2';

/**
 * @testable infrastructure
 */
class IndexTable extends BaseTable {
	constructor(attributes) {
		super(attributes);
		this.refreshScope = "collection";
		this.loading = false;
		this.loaded = !this.prefetched || this.target.hasAttribute("loaded");
		this._empty = false;
		this._updated = [];
		this._created = [];
	}

	async updated(response) {
		this._updated = response.html?.querySelectorAll("tr[lp-entity]") || [];
		const append = response.html?.querySelector("tr[lp-load]");
		this.loaded = !append;
		return append;
	}

	async created(response) {
		this._created = response.html.querySelectorAll("tr");
	}

	get selector() {
		return this.component.elt.querySelector(
			"th[data-column='selector'] button",
		);
	}

	setEmptyRowVisibility() {
		const emptyRow = this.target.querySelector("tr[data-role='empty']");
		const notEmpty = this.target.querySelector("tr[lp-entity]");
		if (emptyRow) {
			if (!this.view.mobile) {
				emptyRow.dataset.visible = notEmpty ? "false" : "true";
			} else {
				emptyRow.style.display = notEmpty ? "none" : "block";
			}
		}
		if (!notEmpty) {
			this.loaded = true;
			this.target.setAttribute("loaded", "");
		}
	}

	get prefetched() {
		return this.target.hasAttribute("lp-prefetch");
	}

	/**
	 * @testable true
	 * @tests tests_e2e/003_forms/test_003a_forms.py::test_forms_index_page
	 * @tests tests_js/test_022_refresh_frontend.mjs::test_core_refresh_batches_supported_widgets_and_falls_back_per_target
	 * @pairs indexes:fingerprint-gate reconnect-refresh:manifest
	 */
	refreshDescriptor() {
		if (
			this.component.name !== "table" ||
			!this.target.hasAttribute("loaded")
		) {
			return null;
		}
		const supported =
			Boolean(this.view.key) ||
			["forms", "tasks", "users"].includes(this.view.elt.dataset.index);
		if (!supported) return null;

		return {
			rows: Array.from(
				this.target.querySelectorAll("tr[lp-entity]"),
				(row) => ({
					key: row.dataset.key,
					hash: row.dataset.hash || "",
					fingerprint: row.dataset.fingerprint || "",
				}),
			),
		};
	}

	_parseRefreshRow(html) {
		if (!html) return null;
		const template = document.createElement("template");
		template.innerHTML = html.trim();
		return template.content.querySelector("tr[lp-entity]");
	}

	/**
	 * @testable true
	 * @matrix table-controls : quick-edit row-replacement teardown
	 */
	refreshDelta(delta) {
		const editor = this.component?.widgets?.TableEditor;
		const existing = new Map(
			Array.from(this.target.querySelectorAll("tr[lp-entity]"), (row) => [
				row.dataset.key,
				row,
			]),
		);
		editor?.releaseRows([
			...(delta.remove || []).map((key) => existing.get(key)),
			...(delta.upsert || []).map(({ key }) => existing.get(key)),
		]);
		for (const key of delta.remove || []) {
			existing.get(key)?.remove();
			existing.delete(key);
		}

		const added = [];
		for (const update of delta.upsert || []) {
			const row = this._parseRefreshRow(update.html);
			if (!row || row.dataset.key !== update.key) {
				throw new Error("Invalid table refresh row");
			}
			const current = existing.get(update.key);
			if (current) {
				current.replaceWith(row);
			} else added.push(row);
			existing.set(update.key, row);
		}

		const order = Array.isArray(delta.order) ? delta.order : [];
		for (const key of order) {
			const row = existing.get(key);
			if (!row) throw new Error("Table refresh order references a missing row");
			this.target.append(row);
		}
		if (added.length) this.view.addFlash(...added);

		let empty = this.target.querySelector("tr[data-role='empty']");
		if (!order.length && !empty && delta.empty) {
			const template = document.createElement("template");
			template.innerHTML = delta.empty.trim();
			empty = template.content.querySelector("tr[data-role='empty']");
			if (empty) this.target.append(empty);
		}

		this.setEmptyRowVisibility();
		this.sortingWidget?.refreshRows?.();
		void editor?.refreshCheckboxes().catch(captureError);
	}

	/**
	 * @testable true
	 * @tests tests_js/test_022_refresh_frontend.mjs::test_index_table_row_updates_rebuild_active_sort
	 * @matrix form-index : delete-target destination-refresh sorting
	 * @matrix table-controls : quick-edit row-replacement teardown
	 */
	refresh(response) {
		if (!response?.html) return;
		const editor = this.component?.widgets?.TableEditor;
		const newRows = [...response.html.querySelectorAll("tr[lp-entity]")];
		const newKeys = new Set(
			newRows.map((row) => row.dataset.key).filter(Boolean),
		);
		const prepend = [];
		editor?.releaseRows(
			Array.from(this.target.querySelectorAll("tr[lp-entity]")).filter(
				(row) => !this.prefetched || newKeys.has(row.dataset.key),
			),
		);

		for (const newRow of newRows) {
			const key = newRow.dataset.key;
			if (!key) continue;

			const existing = this.target.querySelector(`tr[data-key="${key}"]`);
			if (existing) {
				existing.replaceWith(newRow);
			} else prepend.push(newRow);
		}

		if (prepend.length) {
			const anchor = this.target.querySelector("tr[lp-entity]");
			if (anchor) anchor.before(...prepend);
			else this.target.append(...prepend);
			this.view.addFlash(...prepend);
		}

		if (!this.prefetched) {
			this.target.querySelectorAll("tr[lp-entity]").forEach((row) => {
				if (!newKeys.has(row.dataset.key)) {
					row.remove();
				}
			});
		}

		this.setEmptyRowVisibility();
		this.sortingWidget?.refreshRows?.();
		void editor?.refreshCheckboxes().catch(captureError);
	}

	/**
	 * @testable true
	 * @tests tests_js/test_022_refresh_frontend.mjs::test_index_table_row_updates_rebuild_active_sort
	 * @matrix form-index : created-row sorting
	 */
	async prereconcile() {
		const loaded = this.target.hasAttribute("loaded");
		if (!this.loaded || loaded) return;

		const sorting = await this.component.loadWidget("TableSorting");
		if (sorting) await sorting.init();
		this._finishLoading = true;
	}

	postreconcile() {
		const target = this.target;
		let rowsChanged = false;
		const sortingWasInitialized = this.sortingWidget?.initialized === true;

		if (this._created.length > 0) {
			target.prepend(...this._created);
			this.view.addFlash(...this._created);
			this._created = [];
			rowsChanged = true;

			if (this.view.mobile) {
				target.scrollIntoView({ behavior: "auto", block: "start" });
			}
		}

		if (this._updated.length > 0) {
			target.append(...this._updated);
			this._updated = [];
			rowsChanged = true;
		}

		if (this._finishLoading) {
			this._finishLoading = false;
			this.target.setAttribute("loaded", "");
			this.setEmptyRowVisibility();
			target.dataset.visible = true;
			this.loading = false;
		}

		if (rowsChanged) {
			this.setEmptyRowVisibility();
			if (sortingWasInitialized) this.sortingWidget.refreshRows();
			void this.component?.widgets?.TableEditor?.refreshCheckboxes().catch(
				captureError,
			);
		}
	}
}

export { IndexTable };
