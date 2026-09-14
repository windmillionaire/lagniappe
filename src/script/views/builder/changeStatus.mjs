import { PollingCoordinator } from "../../shared/polling";
import { request } from "../../shared/request";

/**
 * @testable true
 * @tests tests_e2e/003_forms/test_003g_form_changes.py::test_saved_conversion_runs_after_save_and_preserves_originals
 * @tests tests_e2e/003_forms/test_003g_form_changes.py::test_failed_preflight_recovers_after_reload
 * @tests tests_e2e/003_forms/test_003g_form_changes.py::test_builder_observes_migration_completion_without_leaving
 * @tests tests_js/test_036c_form_migrations.py::test_migration_status_uses_notification_and_keeps_save_disabled
 * @tests tests_js/test_036c_form_migrations.py::test_builder_resumes_migration_polling_and_clears_completed_status
 * @matrix form-migration : saved-job progress reload recovery
 */
export class FormChangeStatus {
	constructor(builder) {
		this.builder = builder;
		this.polling = new PollingCoordinator(builder).init();
		this.node = document.createElement("span");
		this.node.dataset.role = "form-change-status";
		this.node.hidden = true;
		if (builder.hidden && builder.blurred)
			this.polling.blur(builder.blurredAt ?? Date.now());
	}

	show(change) {
		this.change = change;
		this.unsubscribe?.();
		this.node.hidden = !change;
		for (const panel of [
			this.builder.settings.panel,
			this.builder.conditions.panel,
			this.builder.components.panel,
			this.builder.model.panel,
			this.builder.formSettings.panel,
		])
			if (panel) panel.inert = Boolean(change);
		this.builder.pendingChange = change;
		const header = this.builder.header;
		header.saveButton?.setAttribute(
			"aria-disabled",
			String(
				Boolean(change || header._savePromise || !this.builder.draft.dirty),
			),
		);
		if (!change) {
			header.clearMessage();
			return;
		}
		const message = document.createElement("span");
		const failed = ["failed", "expired", "cancelled", "superseded"].includes(
			change.status,
		);
		message.textContent = failed
			? "Form update needs attention."
			: "Schema migration in progress, Save temporarily disabled";
		this.node.replaceChildren(message);
		if (failed && change.error) {
			message.textContent += ` ${change.error}`;
		}
		if (failed && change.failed_entity) {
			const affected = this.node.appendChild(document.createElement("span"));
			affected.textContent = ` Affected ${change.failed_entity.kind}: `;
			const link = affected.appendChild(document.createElement("a"));
			link.href = change.failed_entity.url;
			link.textContent = change.failed_entity.name;
		}
		header.message("", { persistent: true });
		header.notification.append(this.node);
		if (failed) {
			const help = this.node.appendChild(document.createElement("span"));
			help.textContent =
				" Retry continues unfinished work and keeps answers already updated. Save will be available when the update finishes.";
			const button = this.node.appendChild(document.createElement("button"));
			button.type = "button";
			button.className = "ml-2 font-semibold underline";
			button.textContent = "Retry";
			button.addEventListener("click", async () => {
				button.disabled = true;
				try {
					const data = new FormData();
					data.set("action", "retry");
					const result = await request.post(
						`/forms/${this.builder.key}/change`,
						data,
						{ replaceErrorPage: false },
					);
					if (result?.ok) await this.accept(result);
					else
						message.textContent =
							result?.error || "Could not update the job. Try again.";
				} finally {
					button.disabled = false;
				}
			});
		}
		if (!failed && change.operation)
			this.unsubscribe = this.polling.subscribe(
				{
					id: `builder-change:${change.operation}`,
					type: "operation",
					key: change.operation,
					revision: 0,
				},
				{
					whileBlurred: () =>
						this.node.isConnected &&
						!this.node.hidden &&
						this.node.checkVisibility({
							checkOpacity: true,
							checkVisibilityCSS: true,
						}),
					onResult: async () => {
						const result = await request.get(
							`/forms/${this.builder.key}/change`,
							null,
							{ replaceErrorPage: false },
						);
						if (!this.builder._destroyed && result?.ok)
							await this.accept(result);
					},
				},
			);
	}

	async accept(result) {
		if (result.pending_change) {
			// Keep the existing subscription while ordinary progress advances.
			if (JSON.stringify(result.pending_change) !== JSON.stringify(this.change))
				this.show(result.pending_change);
			return;
		}
		this.show(null);
		if (result.rejected_change) {
			// The staged draft was rejected before any values changed. Preserve
			// local edits while restoring the real saved baseline for another Save.
			this.builder.draft.saved = structuredClone(result.draft);
			this.builder.draft.baseline = result.baseline;
			this.builder.draft.formDirty = !this.builder.draft.equalForm(
				this.builder.draft.state,
				result.draft,
			);
			this.builder.refreshDraftControls();
			this.builder.header.message(result.rejected_change.error, {
				persistent: true,
			});
			return;
		}
		this.builder.draft.acknowledge(this.builder.draft.saved, result);
		await this.builder.restoreDraft();
		this.builder.header.message("Form update finished.");
	}

	destroy() {
		this.unsubscribe?.();
		this.polling.destroy();
		this.node.remove();
	}
}
