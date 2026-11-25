import { PollingCoordinator } from "../../shared/polling.ts";
import { request } from "../../shared/request.ts";
import type { RequestResult } from "../../types/api.d.ts";
import type FormBuilder from "./builder.ts";
import type {
	DraftChangeResponse,
	DraftPublication,
	PendingChange,
} from "./types.ts";

export class FormChangeStatus {
	declare builder: FormBuilder;
	declare polling: PollingCoordinator;
	declare node: HTMLSpanElement;
	declare change?: PendingChange | null;
	declare unsubscribe?: () => void;

	constructor(builder: FormBuilder) {
		this.builder = builder;
		this.polling = new PollingCoordinator(builder).init();
		this.node = document.createElement("span");
		this.node.dataset.role = "form-change-status";
		this.node.hidden = true;
		if (builder.hidden && builder.blurred)
			this.polling.blur(builder.blurredAt ?? Date.now());
	}

	show(change: PendingChange | null) {
		this.change = change;
		this.unsubscribe?.();
		this.node.hidden = !change;
		for (const panel of [
			this.builder.settings.panel,
			this.builder.conditions.panel,
			this.builder.components.panel,
			this.builder.model.panel,
			this.builder.formSettings.column,
		])
			if (panel) panel.inert = Boolean(change);
		this.builder.pendingChange = change;
		const header = this.builder.header;
		header.saveButton?.setAttribute(
			"aria-disabled",
			String(
				Boolean(change || header._savePromise || !this.builder.draft?.dirty),
			),
		);
		if (!change) {
			header.clearMessage();
			return;
		}
		const message = document.createElement("span");
		const failed = ["failed", "expired", "cancelled", "superseded"].includes(
			change.status ?? "",
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
					const result = await request.post<DraftChangeResponse>(
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
						const result = await request.get<DraftChangeResponse>(
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

	async accept(result: RequestResult<DraftChangeResponse>) {
		if (result.pending_change) {
			// Keep the existing subscription while ordinary progress advances.
			if (JSON.stringify(result.pending_change) !== JSON.stringify(this.change))
				this.show(result.pending_change);
			return;
		}
		const draft = this.builder.draft;
		if (!draft || !result.draft || !result.baseline) return;
		this.show(null);
		if (result.rejected_change) {
			// The staged draft was rejected before any values changed. Preserve
			// local edits while restoring the real saved baseline for another Save.
			draft.saved = structuredClone(result.draft);
			draft.baseline = result.baseline;
			draft.formDirty = !draft.equalForm(draft.state, result.draft);
			this.builder.refreshDraftControls();
			this.builder.header.message(result.rejected_change.error, {
				persistent: true,
			});
			return;
		}
		draft.acknowledge(draft.saved, result as DraftPublication);
		await this.builder.restoreDraft();
		this.builder.header.message("Form update finished.");
	}

	destroy() {
		this.unsubscribe?.();
		this.polling.destroy();
		this.node.remove();
	}
}
