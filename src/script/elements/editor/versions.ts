import type { Editor } from "@tiptap/core";
import * as Y from "yjs";
import { STYLES } from "../../generated/styles.mjs";
import { request } from "../../shared/request.ts";
import { base64ToUint8Array } from "../../shared/utilities.ts";
import type { DocumentState, PersistedSyncRecord } from "../../types/sync.d.ts";
import type { CollaborativeDocument } from "./collaborative.ts";
import { previewEditor } from "./editor.ts";

export interface DocumentVersionEntry {
	key: string;
	name: string;
	created?: string;
	pinned?: boolean;
	backup?: boolean;
}

interface DocumentVersionMarkup {
	markup: string;
}

const isReplacement = (
	value: unknown,
): value is Pick<DocumentVersionEntry, "key" | "name"> =>
	Boolean(
		value &&
			typeof value === "object" &&
			"key" in value &&
			typeof value.key === "string" &&
			"name" in value &&
			typeof value.name === "string",
	);

export function incomingReplacements(
	ydoc: Y.Doc,
	remote: DocumentState | null,
	offline: PersistedSyncRecord | null = null,
) {
	const candidate = new Y.Doc();
	try {
		Y.applyUpdate(candidate, Y.encodeStateAsUpdate(ydoc));
		if (offline?.ydoc)
			Y.applyUpdate(candidate, base64ToUint8Array(offline.ydoc));
		if (offline?.update)
			Y.applyUpdate(candidate, base64ToUint8Array(offline.update));
		const known = new Set(candidate.getMap("lagniappeReplacements").keys());
		if (remote?.ydoc) Y.applyUpdate(candidate, base64ToUint8Array(remote.ydoc));
		for (const change of remote?.updates ?? []) {
			if (change.update)
				Y.applyUpdate(candidate, base64ToUint8Array(change.update));
		}
		return [...candidate.getMap("lagniappeReplacements")].filter(
			(entry): entry is [string, Pick<DocumentVersionEntry, "key" | "name">] =>
				!known.has(entry[0]) && isReplacement(entry[1]),
		);
	} finally {
		candidate.destroy();
	}
}

export class DocumentVersions {
	declare doc: CollaborativeDocument;
	declare selection: number;
	declare banner?: HTMLDivElement;
	declare previewPanel?: HTMLElement | null;
	declare previewInstance?: Editor | null;

	constructor(doc: CollaborativeDocument) {
		this.doc = doc;
		this.selection = 0;
	}

	get endpoint() {
		const key = this.doc.component?.key ?? this.doc.key;
		return (
			this.doc.endpoints?.history ??
			(key ? `/assets/${key}/document/history` : null)
		);
	}

	async pin(html: string, name: string, identity: string | string[]) {
		const digest = await crypto.subtle.digest(
			"SHA-256",
			new TextEncoder().encode(JSON.stringify([identity, html])),
		);
		const recovery_id = Array.from(new Uint8Array(digest), (byte) =>
			byte.toString(16).padStart(2, "0"),
		).join("");
		const response = await request.post<{ entry: DocumentVersionEntry }>(
			`${this.endpoint}/pin`,
			{
				html,
				name: name.slice(0, 100),
				recovery_id,
			},
		);
		if (!response?.ok || !response.entry)
			throw new Error(
				response?.error ||
					"Unable to save the recovery version. Your document has not been replaced.",
			);
		return response.entry;
	}

	async beforeSync(remote: DocumentState) {
		const doc = this.doc;
		if (doc._versionBusy) return false;
		const changes = incomingReplacements(doc.ydoc, remote, doc.offlineRecord);
		if (!changes.length) return true;
		const hasDraft = Boolean(
			doc._dirty || doc.offlineRecord?.ydoc || doc.offlineRecord?.update,
		);
		// New readers simply hydrate the current document, without historical notices.
		if (!doc.initialized && !hasDraft) return true;
		const editable = doc.editor.isEditable;
		doc._versionBusy = true;
		doc.editor.setEditable(false);
		try {
			let recovery: DocumentVersionEntry | undefined;
			if (hasDraft) {
				// A mounted editor may contain newer work than its persisted draft.
				// Preserve both when they differ, before applying any remote deletes.
				const drafts = new Set<string>();
				if (typeof doc.offlineRecord?.html === "string")
					drafts.add(doc.offlineRecord.html);
				if (doc._dirty || !drafts.size) drafts.add(doc.editor.getHTML());
				for (const html of drafts) {
					recovery = await this.pin(
						html,
						"Recovered local edits",
						changes.map(([id]) => id).sort(),
					);
				}
			}
			if (doc._destroyed) return false;
			const previous = changes[changes.length - 1][1];
			this.notice("Document replaced.", previous, recovery);
			return true;
		} catch (error) {
			this.notice(error instanceof Error ? error.message : String(error));
			return false;
		} finally {
			doc._versionBusy = false;
			if (!doc._destroyed) doc.editor.setEditable(editable);
		}
	}

	button(label: string, action: (event: MouseEvent) => unknown) {
		const button = document.createElement("button");
		button.type = "button";
		button.className = STYLES.link.default;
		button.textContent = label;
		button.addEventListener("click", action);
		return button;
	}

	notice(
		message: string,
		previous: DocumentVersionEntry | null = null,
		recovery: DocumentVersionEntry | null = null,
	) {
		if (this.doc.headless || this.doc._destroyed) return;
		this.banner?.remove();
		this.banner = document.createElement("div");
		this.banner.dataset.role = "document-version-notice";
		this.banner.className =
			"flex flex-wrap items-center gap-3 px-4 py-2 text-sm bg-base-bg";
		this.banner.setAttribute("role", "status");
		this.banner.hidden = Boolean(this.previewPanel && previous);
		const text = document.createElement("span");
		text.textContent = message;
		this.banner.append(text);
		if (previous)
			this.banner.append(
				this.button("View previous version", () => this.preview(previous)),
			);
		if (recovery)
			this.banner.append(
				this.button("View recovered local edits", () => this.preview(recovery)),
			);
		this.banner.append(this.button("Dismiss", () => this.banner?.remove()));
		this.doc.target.insertBefore(this.banner, this.doc.container);
	}

	async preview(entry: DocumentVersionEntry) {
		const selection = ++this.selection;
		const url = `${this.endpoint}/${entry.backup ? "backups/" : ""}${encodeURIComponent(entry.key)}`;
		const response = await request.get<DocumentVersionMarkup>(url, {
			refresh: Date.now(),
		});
		if (selection !== this.selection || this.doc._destroyed) return;
		if (typeof response?.markup !== "string") {
			this.notice(response?.error || "Unable to load this version.");
			return;
		}
		const markup = response.markup;
		this.closePreview(false);
		const doc = this.doc;
		this.previewPanel = document.createElement("section");
		this.previewPanel.dataset.role = "document-version-preview";
		const controls = document.createElement("div");
		controls.className =
			"flex flex-wrap items-center gap-3 px-4 py-2 text-sm bg-base-bg";
		const label = document.createElement("span");
		label.textContent = `Viewing ${entry.name || "saved version"}${entry.created ? ` — ${new Date(entry.created).toLocaleString()}` : ""}`;
		controls.append(
			label,
			this.button("Back to current", () => this.closePreview()),
		);
		if (!doc.readonly)
			controls.append(
				this.button("Restore this version", () => this.restore(markup)),
			);
		this.previewPanel.append(controls);
		const surface = document.createElement("div");
		surface.className = STYLES.editor.container;
		surface.dataset.role = "version-content";
		this.previewPanel.append(surface);
		this.previewInstance = previewEditor(surface, markup);
		doc.target.insertBefore(this.previewPanel, doc.container);
		if (this.banner) this.banner.hidden = true;
		doc.container.hidden = true;
		if (doc.toolbar?.element) doc.toolbar.element.hidden = true;
	}

	closePreview(cancelPending = true) {
		if (cancelPending) this.selection++;
		this.previewInstance?.destroy();
		this.previewInstance = null;
		this.previewPanel?.remove();
		this.previewPanel = null;
		if (this.banner) this.banner.hidden = false;
		this.doc.container.hidden = false;
		if (this.doc.toolbar?.element) this.doc.toolbar.element.hidden = false;
	}

	async restore(markup: string) {
		const doc = this.doc;
		if (
			doc._versionBusy ||
			doc._destroyed ||
			doc.readonly ||
			!this.previewPanel
		)
			return;
		if (!doc.view?.online) {
			this.notice(
				"Reconnect to preserve the current version before restoring.",
			);
			return;
		}
		doc._versionBusy = true;
		this.previewPanel.inert = true;
		const operation = crypto.randomUUID();
		try {
			const previous = await this.pin(
				doc.editor.getHTML(),
				"Before document restore",
				operation,
			);
			if (doc._destroyed) return;
			doc.ydoc.transact(() => {
				doc.editor.commands.setContent(markup);
				doc.ydoc
					.getMap("lagniappeReplacements")
					.set(operation, { key: previous.key, name: previous.name });
			});
			this.closePreview();
			this.notice("Version restored.", previous);
		} catch (error) {
			this.notice(error instanceof Error ? error.message : String(error));
		} finally {
			doc._versionBusy = false;
			if (this.previewPanel) this.previewPanel.inert = false;
		}
		if (!doc._destroyed) await doc.view.SyncManager?.sendUpdates(true);
	}

	destroy() {
		this.selection++;
		this.previewInstance?.destroy();
		this.previewPanel?.remove();
		this.banner?.remove();
	}
}
