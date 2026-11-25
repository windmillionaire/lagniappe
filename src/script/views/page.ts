import { setIcon } from "../shared/icons.ts";
import { withTransition } from "../shared/transitions.ts";
import type { PagePhoto } from "../widgets/pagePhoto.ts";
import type { SubcomponentEvent } from "./base/component.ts";
import Entity, {
	type EntityLayoutOptions,
	type PreparedEntityLayout,
} from "./base/entity.ts";

export default class Page extends Entity {
	declare photoHasImage: boolean;
	declare photoOpen: boolean;
	declare photoToolsOpen: boolean;
	declare photoGenerationReturnOpen: boolean | null;
	declare photoActiveTab?: string;
	declare photoBusy?: boolean;
	declare _taskChannelUnsubscribe?: (() => void) | null;
	declare _pendingTabWidget?: { tabId: string; widget: string } | null;

	async reconcilePollingSubscriptions() {
		await super.reconcilePollingSubscriptions();
		const component = this.components.tasks;
		const list = Object.values(component?.widgets || {}).find(
			(widget) => widget?.name === "PageTaskList" && widget.loaded,
		);
		if (!component || !list || !this.PollingCoordinator) {
			this._taskChannelUnsubscribe?.();
			this._taskChannelUnsubscribe = null;
			return;
		}
		if (this._taskChannelUnsubscribe) return;
		this._taskChannelUnsubscribe = this.PollingCoordinator.subscribe(
			{
				id: `page:tasks:${this.key}`,
				type: "channel",
				channel: "tasks",
				revision: this.elt.dataset.collectionRevision || null,
			},
			{
				mode: "periodic",
				initial: "scheduled",
				onResult: async (result) => {
					if (result.status === "changed") {
						await this._refreshCollectionComponents([component]);
					}
				},
			},
		);
	}

	async init() {
		this.photoHasImage = this.elt.dataset.hasImage === "true";
		this.photoOpen =
			this.photoHasImage &&
			localStorage.getItem(`${this.hash}-photo-visible`) !== "false";
		this.photoToolsOpen = false;
		this.photoGenerationReturnOpen = null;
		this.elt.addEventListener("click", (event) => this._photoClick(event));
		const taskId =
			new URLSearchParams(window.location.search).get("task") ||
			this.elt.dataset.focusTask;
		if (taskId) {
			localStorage.setItem(`${this.hash}-active`, "tasks");
			this.postRender = this._focusTask.bind(this, taskId);
		} else if (this._requestedUserSettings()) {
			this._pendingTabWidget = { tabId: "info", widget: "UserSettings" };
		}

		await super.init();

		if (this._requestedUserSettings()) {
			this._replaceInitialTabUrl();
		}

		const photo = this.elt.querySelector<HTMLElement>("#photo");
		if (photo) {
			const component = this.getComponent(photo);
			const initiallyVisible =
				component?.active || this.isSecondaryCardVisible(photo);
			if (initiallyVisible && component && !component.active) {
				await component.activate("PagePhoto");
			}
		}
	}

	get secondaryCard() {
		const available = this.mobile
			? this.photoHasImage || this.photoToolsOpen
			: this.photoOpen;
		if (!available) return null;
		return this.elt.querySelector<HTMLElement>("#photo");
	}

	_requestedUserSettings() {
		const raw = new URLSearchParams(window.location.search).get("tab")?.trim();
		const requested =
			typeof this.querySlug === "function"
				? this.querySlug(raw)
				: raw?.toLowerCase();
		return (
			(requested === "user-settings" || requested === "settings") &&
			Boolean(this.elt.querySelector("form[data-widget='UserSettings']"))
		);
	}

	_initialTabId() {
		if (this._pendingTabWidget) return this._pendingTabWidget.tabId;
		const tabId = super._initialTabId();
		return tabId === "photo" && (!this.mobile || !this.secondaryCard)
			? "info"
			: tabId;
	}

	_initialTabWidget(tabId: string) {
		if (this._pendingTabWidget?.tabId === tabId) {
			const { widget } = this._pendingTabWidget;
			this._pendingTabWidget = null;
			return widget;
		}
		return super._initialTabWidget(tabId);
	}

	_replaceInitialTabUrl() {
		const url = new URL(window.location.href);
		url.searchParams.delete("tab");
		const next = `${url.pathname}${url.search}${url.hash}`;
		window.history.replaceState(null, "", next);
	}

	_tabChange(event: SubcomponentEvent) {
		super._tabChange(event);
		if (event.detail.subcomponent.elt.dataset.tab === "true") {
			this._syncPhotoControls(event.detail.subcomponent.name);
		}
	}

	async updateLayout(options: EntityLayoutOptions = {}) {
		return super.updateLayout({
			secondary: this.elt.querySelector<HTMLElement>("#photo"),
			secondaryActive: Boolean(this.secondaryCard),
			...options,
		});
	}

	_commitLayoutBody(prepared: PreparedEntityLayout) {
		const tabId = super._commitLayoutBody(prepared);
		this._syncPhotoControls(tabId);
		return tabId;
	}

	_syncPhotoControls(
		tabId = this.photoActiveTab || this._initialTabId() || "info",
		controls = this.elt.querySelector<HTMLElement>(
			"[data-role='photo-prompt']",
		),
	) {
		this.photoActiveTab = tabId;
		if (!controls) return;
		controls.dataset.visible =
			!this.mobile || (!this.photoHasImage && tabId === "info")
				? "true"
				: "false";
		const toggle = controls.querySelector<HTMLButtonElement>(
			"[data-role='photo-upload']",
		);
		if (!toggle) return;
		const icon = this.photoHasImage
			? this.photoOpen
				? "visibility.visible"
				: "visibility.hidden"
			: "upload";
		const label = this.photoHasImage
			? this.photoOpen
				? "Hide page image"
				: "Show page image"
			: this.photoOpen
				? "Close image upload"
				: "Upload page image";
		const iconElement = toggle.querySelector<HTMLElement>("[data-icon]");
		if (iconElement) setIcon(iconElement, icon);
		toggle.title = label;
		toggle.setAttribute("aria-label", label);
		toggle.setAttribute("aria-expanded", String(this.photoOpen));
		controls.querySelectorAll("button").forEach((button) => {
			button.disabled = Boolean(this.photoBusy);
		});
		this.elt
			.querySelectorAll<HTMLButtonElement>("button[lp-show='photo:active']")
			.forEach((button) => {
				// The mobile flipper reveals unselected tabs via data-visible.
				// Keep unavailable image tabs hidden independently of selection.
				button.hidden = !this.photoHasImage && !this.photoToolsOpen;
			});
	}

	setPhotoBusy(busy: boolean) {
		this.photoBusy = busy;
		this._syncPhotoControls();
	}

	async _photoClick(event: MouseEvent) {
		const button = (
			event.target as Element | null
		)?.closest?.<HTMLButtonElement>(
			"[data-role='photo-upload'], [data-role='photo-generate']",
		);
		if (!button || this.photoBusy) return;
		const controls = button.closest("[data-role='photo-prompt']");
		if (!controls) return;
		const error = controls.querySelector<HTMLElement>(
			"[data-role='photo-prompt-error']",
		);
		if (!error) return;
		error.dataset.visible = "false";
		this.setPhotoBusy(true);
		try {
			const generate = button.dataset.role === "photo-generate";
			const component = this.getComponent(
				this.elt.querySelector<HTMLElement>("#photo"),
			);
			if (!component) return;
			const open = generate || this.mobile || !this.photoOpen;
			if (open) await component.activate("PagePhoto");
			if (generate) this.photoGenerationReturnOpen ??= this.photoOpen;
			this.photoOpen = open;
			this.photoToolsOpen = open && !this.photoHasImage;
			if (!generate && this.photoHasImage) {
				localStorage.setItem(`${this.hash}-photo-visible`, String(open));
			}
			await this.updateLayout({
				activeTabId: this.mobile ? "photo" : null,
				mutate: () => () => {
					const photo = component.active as PagePhoto | null;
					if (generate) photo?.showGenerateForm({ transition: false });
					else photo?.hideGenerateForm({ transition: false });
				},
			});
		} catch (failure) {
			error.textContent =
				(failure instanceof Error && failure.message) ||
				"Unable to show image tools.";
			error.dataset.visible = "true";
		} finally {
			this.setPhotoBusy(false);
		}
	}

	async cancelPhotoGeneration(widget: Pick<PagePhoto, "hideGenerateForm">) {
		this.photoOpen = this.photoGenerationReturnOpen ?? this.photoHasImage;
		this.photoToolsOpen = this.photoOpen && !this.photoHasImage;
		this.photoGenerationReturnOpen = null;
		await this.updateLayout({
			activeTabId: this.mobile && !this.secondaryCard ? "info" : null,
			mutate: () => () => widget.hideGenerateForm({ transition: false }),
		});
		this.elt
			.querySelector<HTMLElement>(
				this.mobile && this.secondaryCard
					? "#photo [data-role='upload-menu']"
					: "[data-role='photo-generate']",
			)
			?.focus();
	}

	async updatePhotoImage(hasImage: boolean, mutate: () => void) {
		this.photoHasImage = hasImage;
		this.photoOpen = hasImage;
		this.photoToolsOpen = false;
		this.photoGenerationReturnOpen = null;
		localStorage.setItem(`${this.hash}-photo-visible`, String(hasImage));
		await this.updateLayout({
			activeTabId: !hasImage && this.mobile ? "info" : null,
			mutate: () => () => {
				mutate();
				this.elt.dataset.hasImage = String(hasImage);
			},
		});
	}

	async _focusTask(taskId: string) {
		const taskTab = this.getComponent(this.elt.querySelector("#tasks"));
		if (!taskTab) return;
		await taskTab.activate("PageTaskList");
		await taskTab.prepareRender(true);
		await withTransition(() => taskTab.render(true), {
			label: "page:focus-task-tab",
		});
		await taskTab.widgets.PageTaskList?.focusTask(taskId);
		this._replaceFocusedTaskUrl();
		this.postRender = null;
	}

	_replaceFocusedTaskUrl() {
		const pagePath = this.key ? `/pages/${this.key}` : window.location.pathname;
		history.replaceState(null, "", pagePath);
	}
}
