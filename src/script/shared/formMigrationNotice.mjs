import { STYLES } from "styles";
import { Modal } from "./modal";

/**
 * @testable true
 * @tests tests_e2e/003_forms/test_003g_form_changes.py::test_saved_conversion_runs_after_save_and_preserves_originals
 * @matrix form-migration : informational-notice readonly-modal
 */
export function installMigrationNotice(widget) {
	widget._migrationNotice?.destroy();
	if (widget.target?.dataset.completed === "true") return;
	const values = JSON.parse(widget.target?.dataset.migrationNotice || "[]");
	if (!values.length) return;
	const banner = document.createElement("p");
	banner.dataset.role = "migration-notice";
	banner.className =
		"rounded-md px-3 py-2 text-sm bg-amber-50 text-amber-900 ring-1 ring-amber-400";
	banner.textContent = "This form was updated — ";
	const trigger = banner.appendChild(document.createElement("button"));
	trigger.type = "button";
	trigger.className =
		"font-semibold underline underline-offset-2 focus-visible:outline-2 focus-visible:outline-offset-2";
	trigger.textContent = "View changes";
	widget.target.prepend(banner);
	const modal = new Modal(widget.view, trigger);
	widget._migrationNotice = {
		destroy: () => {
			modal.destroy();
			banner.remove();
		},
	};
	trigger.addEventListener("click", async () => {
		const root = document.createElement("div");
		root.id = "modal";
		root.className = STYLES.modal.wrapper;
		root.dataset.kind =
			widget.kind || widget.component?.kind || widget.view.kind || "default";
		const content = root.appendChild(document.createElement("section"));
		content.id = "modal-content";
		content.className = `${STYLES.modal.content} w-full sm:max-w-3xl`;
		content.setAttribute("role", "dialog");
		content.setAttribute("aria-modal", "true");
		content.setAttribute("aria-label", "Form changes");
		const header = content.appendChild(document.createElement("header"));
		header.className = STYLES.modal.header;
		const heading = header.appendChild(document.createElement("h2"));
		heading.className = "text-lg font-bold text-base-dark";
		heading.textContent = "Form changes";
		const close = header.appendChild(document.createElement("button"));
		close.type = "button";
		close.setAttribute("lp-control", "close");
		close.className = STYLES.button.close;
		close.textContent = "Close";
		const body = content.appendChild(document.createElement("div"));
		body.className = "space-y-4 p-4 sm:p-6";
		const intro = body.appendChild(document.createElement("p"));
		intro.className = "text-sm text-base-medium";
		intro.textContent =
			"These values changed when the form was updated. The notice clears when this submission is next saved or completed.";
		const fields = body.appendChild(document.createElement("div"));
		fields.className = "space-y-4";
		for (const value of values) {
			const row = fields.appendChild(document.createElement("section"));
			row.className = "rounded-md border border-base-light/50 bg-base-bg p-3";
			const title = row.appendChild(document.createElement("h3"));
			title.className = "mb-2 font-semibold text-base-dark";
			title.textContent = value.label;
			const cells = row.appendChild(document.createElement("div"));
			cells.className = "grid gap-2 sm:grid-cols-2";
			for (const key of ["before", "after"]) {
				const cell = cells.appendChild(document.createElement("div"));
				cell.className =
					"min-w-0 rounded-md border border-base-light/50 bg-white p-3";
				const label = cell.appendChild(document.createElement("h4"));
				label.className = "mb-2 text-xs font-semibold text-base-medium";
				label.textContent = key === "before" ? "Before" : "After";
				const content = cell.appendChild(document.createElement("p"));
				content.className = "whitespace-pre-wrap break-words text-sm";
				if (key === "after" && value.reason === "invalid") {
					content.dataset.kind = "error";
					content.className += " italic text-kind-default";
					content.textContent = "Value not able to be converted";
				} else {
					content.textContent = value[key];
				}
			}
		}
		await modal.attach(root, widget.component);
		close.focus();
	});
}
