import { STYLES } from "styles";
import * as Y from "yjs";
import {
	base64ToUint8Array,
	uint8ArrayToBase64,
	waitForAttribute,
} from "../../shared";
import { primitives } from "../primitives";
import { collaborativeEditor } from "./editor";
import { Toolbar } from "./toolbar";

/**
 * @testable true
 * @tests tests_e2e/004_projects/test_004d_document.py::test_editor_loads_and_saves_text
 * @tests tests_e2e/004_projects/test_004d_document.py::test_formatting_persists
 * @features editor
 * @dimensions text-save reload
 */
export class CollaborativeDocument {
	constructor(attributes) {
		Object.assign(this, attributes);
		this.ydoc = new Y.Doc();
		this.updateQueue = [];
		this.syncId = this.target.getAttribute("lp-sync");
		this.initialized = false;

		this._loader = null;
		this._applyingRemote = false;

		this.update = null;
		this.offlineRecord = null;
		this.remote = null;
		this.snapshot = null;
	}

	/**
	 * @testable true
	 * @tests tests_js/test_029_core_startup.py::test_collaborative_document_waits_for_sync_manager_before_state
	 * @pair sync:editor-readiness
	 * @pair sync:state-only
	 */
	async init() {
		this._initContainer();
		this._initEditor();
		if (!this.headless) this._initToolbar();

		if (!this.headless && this.syncId && !this.remote) {
			const syncManager = await (this.view?.syncReady ??
				this.view?.SyncManager);
			if (syncManager) this.remote = await syncManager.state(this);
		}

		this.container.setAttribute("loaded", "");
	}

	get fingerprint() {
		return this.target.getAttribute("lp-fingerprint");
	}

	set fingerprint(value) {
		if (!value) return;
		this.target.setAttribute("lp-fingerprint", value);
	}

	_initContainer() {
		this.container = document.createElement("div");
		this.container.dataset.role = "editor";
		this.container.className = `${STYLES.editor.container} opacity-50 pointer-events-none`;
		if (this.readonly)
			this.container.classList.add("border-base-light/50", "border-t");
		this._loader = this.container.appendChild(primitives.loading());
		this.target.replaceChildren(this.container);
	}

	_initEditor() {
		this.editor = collaborativeEditor(
			this.container,
			this.ydoc,
			!this.readonly,
		);

		this.editor.on("create", async () => {
			await waitForAttribute(this.container, "loaded");
			this._loader?.remove();

			if (!this.headless) {
				await this.sync();
				await this.waitForRender();
			}

			this.container.setAttribute("initialized", "");
			if (!this.headless) {
				this.container.classList.remove("opacity-50", "pointer-events-none");
			}
			this.initialized = true;
		});

		this.editor.on("blur", async ({ event }) => {
			await this.waitForRender();
			const activeElement = event.relatedTarget;
			if (activeElement?.closest("[data-role='toolbar'], [role='listbox']")) {
				return;
			}
			window.dispatchEvent(new CustomEvent("sync-save"));
		});

		this.ydoc.on("update", (update, origin) => {
			if (origin !== "remote" && !this._applyingRemote) {
				this.updateQueue.push(update);
			}
		});
	}

	_initToolbar() {
		if (this.readonly) return;

		this.toolbar = new Toolbar(this);
		this.toolbar.init();
		this.target.prepend(this.toolbar.element);
		this.toolbar.element.setAttribute("initialized", "");
	}

	waitForRender() {
		// After Y.applyUpdate / setContent, y-prosemirror dispatches a PM
		// transaction to render the snapshot, but the DOM mutations and layout
		// aren't guaranteed to be flushed in the same microtask. Waiting two
		// animation frames lets ProseMirror commit pending transactions (frame
		// one) and the browser paint the resulting DOM (frame two) so that
		// anything watching for the "initialized" signal (e.g. e2e tests) sees
		// the editor in its final, interactive state.
		return new Promise((resolve) => {
			requestAnimationFrame(() => requestAnimationFrame(resolve));
		});
	}

	_packageUpdates() {
		if (this.updateQueue.length === 0) return null;
		const merged = Y.mergeUpdates(this.updateQueue);
		this.updateQueue.length = 0;
		return uint8ArrayToBase64(merged);
	}

	_packageState() {
		return uint8ArrayToBase64(Y.encodeStateAsUpdate(this.ydoc));
	}

	/**
	 * @testable true
	 * @tests tests_e2e/010_sync/test_010a_document_sync.py::test_two_users_see_document_edits_without_reload
	 * @tests tests_e2e/010_sync/test_010a_document_sync.py::test_document_sync_response_contract_is_browser_visible
	 * @tests tests_e2e/010_sync/test_010c_offline_replay.py::test_offline_document_edits_replay_in_order
	 * @features sync
	 * @dimensions document collaboration response-contract offline-replay replay-order
	 */
	get syncData() {
		if (!this.initialized || this.updateQueue.length === 0) return null;

		return {
			update: this._packageUpdates(),
			ydoc: this._packageState(),
		};
	}

	/**
	 * @testable true
	 * @tests tests_e2e/010_sync/test_010a_document_sync.py::test_two_users_see_document_edits_without_reload
	 * @tests tests_e2e/010_sync/test_010c_offline_replay.py::test_offline_document_edits_replay_in_order
	 * @tests tests_e2e/010_sync/test_010c_offline_replay.py::test_offline_replay_does_not_duplicate_after_reload
	 * @features sync
	 * @dimensions document persistence queue-clear dedupe reload
	 */
	get saveData() {
		if (!this.initialized) return null;

		const ydoc = this._packageState();
		if (ydoc === this.snapshot) return null;

		let html = this.editor.getHTML();
		if (html.trim() === "<p></p>" || html.trim() === "<p><br></p>") html = "";

		const update = this._packageUpdates();
		this.snapshot = ydoc;

		if (html) {
			this.target.dataset.history = "true";
			this.toolbar?.toggles?.documentHistory?.show();
		}

		return { update, ydoc, html };
	}

	/**
	 * @testable true
	 * @tests tests_e2e/010_sync/test_010a_document_sync.py::test_two_users_see_document_edits_without_reload
	 * @tests tests_e2e/010_sync/test_010a_document_sync.py::test_document_presence_appears_and_clears
	 * @tests tests_e2e/010_sync/test_010c_offline_replay.py::test_offline_document_edits_replay_in_order
	 * @features sync
	 * @dimensions document collaboration presence offline-replay replay-order
	 */
	async sync() {
		if (this.toolbar && this.remote) {
			const others = this.remote.users.filter(
				(u) => u.hash !== this.remote.user.hash,
			);
			this.toolbar.userManager.setUsers(others);
		} else if (this.toolbar && this.update) {
			this.toolbar.userManager.remoteUpdate(this.update.user_hash);
		}

		if (this.update?.update) {
			Y.applyUpdate(
				this.ydoc,
				base64ToUint8Array(this.update.update),
				"remote",
			);
			this.fingerprint = this.update.fingerprint;
		}
		this.update = null;

		if (this.offlineRecord?.ydoc) {
			Y.applyUpdate(
				this.ydoc,
				base64ToUint8Array(this.offlineRecord.ydoc),
				"local",
			);
		}
		this.offlineRecord = null;

		if (!this.remote) return;

		if (
			this.remote.ydoc &&
			(!this.snapshot || this.remote.fingerprint !== this.fingerprint)
		) {
			Y.applyUpdate(this.ydoc, base64ToUint8Array(this.remote.ydoc), "remote");
			this.snapshot = this.remote.ydoc;
			this.fingerprint = this.remote.fingerprint;
		} else if (this.remote.markup) {
			this._applyingRemote = true;
			try {
				this.editor.commands.setContent(this.remote.markup, {
					emitUpdate: false,
				});
			} finally {
				this._applyingRemote = false;
			}
			// The HTML fallback can mutate collaborative editor state before the
			// ProseMirror view repaints, which can leave first-opened seeded
			// documents blank until focus changes.
			this.editor.view.updateState(this.editor.state);
			this.snapshot = this._packageState();
			this.fingerprint = this.remote.fingerprint;
		}

		this.remote = null;
	}

	destroy() {
		this.editor?.destroy();
		this.toolbar?.destroy();
		this.ydoc?.destroy();
	}
}
