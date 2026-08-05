/*! Third-party licenses: /third-party-licenses.txt */
import { STYLES } from './styles.js?v=bfd37afb';
import { D as Doc, c as collaborativeEditor, T as Toolbar, m as mergeUpdates, e as encodeStateAsUpdate, a as applyUpdate } from './toolbar.js?v=bfd37afb';
import { e as waitForAttribute, u as uint8ArrayToBase64, f as base64ToUint8Array } from './foundation.js?v=bfd37afb';
import './connectivity.js?v=bfd37afb';
import { p as primitives } from './primitives.js?v=bfd37afb';
import './combobox.js?v=bfd37afb';
import './icons.js?v=bfd37afb';
import './dropdown.js?v=bfd37afb';
import './notificationState.js?v=bfd37afb';

/**
 * @testable true
 * @tests tests_e2e/004_projects/test_004d_document.py::test_editor_loads_and_saves_text
 * @tests tests_e2e/004_projects/test_004d_document.py::test_untouched_document_does_not_save_or_touch_project
 * @tests tests_e2e/004_projects/test_004d_document.py::test_formatting_persists
 * @features editor
 * @dimensions text-save reload
 */
class CollaborativeDocument {
	constructor(attributes) {
		Object.assign(this, attributes);
		this.ydoc = new Doc();
		this.updateQueue = [];
		this.syncId = this.target.getAttribute("lp-sync");
		this.initialized = false;

		this._loader = null;
		this._applyingRemote = false;
		this._destroyed = false;
		this._dirty = false;

		this.update = null;
		this.offlineRecord = null;
		this.remote = null;
		this.snapshot = null;
		this.initialStateReady = Promise.resolve(null);
	}

	/**
	 * @testable true
	 * @tests tests_js/test_029_core_startup.py::test_collaborative_document_renders_before_initial_state
	 * @pair sync:editor-readiness
	 * @pair sync:state-only
	 */
	init() {
		this._initContainer();
		this._initEditor();
		if (!this.headless) this._initToolbar();

		if (!this.headless && this.syncId && !this.remote) {
			this.initialStateReady = this._loadInitialState();
		} else {
			this.container.setAttribute("loaded", "");
			this.initialStateReady = Promise.resolve(this.remote);
		}
	}

	async _loadInitialState() {
		try {
			const syncManager = await (this.view?.ensureSyncManager?.() ??
				this.view?.syncReady ??
				this.view?.SyncManager);
			if (!this._destroyed && syncManager) {
				this.remote = await syncManager.state(this);
			}
			return this.remote;
		} catch (error) {
			this.view?.reportStartupError?.(
				error,
				this.target,
				"document-initial-state",
			);
			return null;
		} finally {
			if (!this._destroyed) this.container.setAttribute("loaded", "");
		}
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
			if (this._destroyed) return;
			this._loader?.remove();

			if (!this.headless) {
				const hadOfflineChanges = Boolean(
					this.offlineRecord?.ydoc ||
						this.offlineRecord?.update ||
						Object.hasOwn(this.offlineRecord ?? {}, "html"),
				);
				await this.sync();
				await this.waitForRender();
				if (hadOfflineChanges) this._dirty = true;
				else this._commitInitialBaseline();
			}

			this.container.setAttribute("initialized", "");
			if (!this.headless) {
				this.container.classList.remove("opacity-50", "pointer-events-none");
				this.toolbar?.element?.removeAttribute("aria-busy");
				if (this.toolbar?.element) this.toolbar.element.inert = false;
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
				if (this.initialized) this._dirty = true;
			}
		});
	}

	_initToolbar() {
		if (this.readonly) return;

		this.toolbar = new Toolbar(this);
		this.toolbar.init();
		this.target.prepend(this.toolbar.element);
		this.toolbar.element.inert = true;
		this.toolbar.element.setAttribute("aria-busy", "true");
		this.toolbar.element.setAttribute("initialized", "");
	}

	/**
	 * Treat the hydrated editor as the initial baseline so Tiptap/Yjs setup
	 * transactions cannot be mistaken for user-authored empty content.
	 *
	 * @testable true
	 * @tests tests_js/test_029_core_startup.py::test_collaborative_document_does_not_save_untouched_empty_state
	 * @tests tests_e2e/004_projects/test_004d_document.py::test_untouched_document_does_not_save_or_touch_project
	 * @features sync editor
	 * @dimensions initialization empty-content save-guard parent-modified
	 * @pairs sync:initialization sync:empty-content sync:save-guard sync:parent-modified
	 * @pairs editor:initialization editor:empty-content editor:save-guard
	 */
	_commitInitialBaseline() {
		this.snapshot = this._packageState();
		this.updateQueue.length = 0;
		this._dirty = false;
	}

	/**
	 * Accept a persisted checkpoint without discarding an edit made while its
	 * request was in flight. Remote-only changes do not make the document dirty.
	 *
	 * @testable true
	 * @tests tests_js/test_029_core_startup.py::test_collaborative_document_does_not_save_untouched_empty_state
	 * @features sync editor
	 * @dimensions checkpoint dirty-state concurrent-edit
	 * @pairs sync:checkpoint sync:dirty-state sync:concurrent-edit
	 */
	commitSavedBaseline(snapshot) {
		this.snapshot = snapshot;
		if (this.updateQueue.length === 0) this._dirty = false;
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
		const merged = mergeUpdates(this.updateQueue);
		this.updateQueue.length = 0;
		return uint8ArrayToBase64(merged);
	}

	_packageState() {
		return uint8ArrayToBase64(encodeStateAsUpdate(this.ydoc));
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
	 * @tests tests_js/test_029_core_startup.py::test_collaborative_document_does_not_save_untouched_empty_state
	 * @tests tests_e2e/004_projects/test_004d_document.py::test_untouched_document_does_not_save_or_touch_project
	 * @features sync
	 * @dimensions empty-content save-guard parent-modified intentional-clear
	 * @pairs sync:empty-content sync:save-guard sync:parent-modified sync:intentional-clear
	 */
	get saveData() {
		if (!this.initialized || !this._dirty) return null;

		const ydoc = this._packageState();
		if (ydoc === this.snapshot) return null;

		let html = this.editor.getHTML();
		if (html.trim() === "<p></p>" || html.trim() === "<p><br></p>") html = "";

		const update = this._packageUpdates();

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
	 * @tests tests_e2e/010_sync/test_010c_offline_replay.py::test_headless_offline_replay_merges_concurrent_remote_edits
	 * @features sync
	 * @dimensions document collaboration presence lifecycle offline-replay replay-order concurrency merge author-color
	 */
	async sync() {
		if (this.toolbar && this.remote?.users) {
			const others = this.remote.users.filter(
				(u) => u.hash !== this.remote.user?.hash,
			);
			this.toolbar.userManager.setUsers(others);
		}

		if (!this.remote) {
			if (this.offlineRecord?.ydoc) {
				applyUpdate(
					this.ydoc,
					base64ToUint8Array(this.offlineRecord.ydoc),
					"local",
				);
			}
			this.offlineRecord = null;
			return;
		}

		if (this.remote.mode === "snapshot" && this.remote.ydoc) {
			this.toolbar?.userManager.remoteUpdate(
				this.remote.user_hash,
				this.remote.authors?.[this.remote.user_hash],
			);
			applyUpdate(this.ydoc, base64ToUint8Array(this.remote.ydoc), "remote");
			this.snapshot = this.remote.ydoc;
			this.fingerprint = this.remote.fingerprint;
		} else if (this.remote.mode === "snapshot" && this.remote.markup) {
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
		if (this.offlineRecord?.ydoc) {
			applyUpdate(
				this.ydoc,
				base64ToUint8Array(this.offlineRecord.ydoc),
				"local",
			);
		}
		this.offlineRecord = null;
		for (const update of this.remote.updates ?? []) {
			if (!update?.update) continue;
			this.toolbar?.userManager.remoteUpdate(
				update.user_hash,
				this.remote.authors?.[update.user_hash],
			);
			applyUpdate(this.ydoc, base64ToUint8Array(update.update), "remote");
		}
		if (this.remote.fingerprint) this.fingerprint = this.remote.fingerprint;

		this.remote = null;
	}

	destroy() {
		this._destroyed = true;
		this.editor?.destroy();
		this.toolbar?.destroy();
		this.ydoc?.destroy();
	}
}

export { CollaborativeDocument };
