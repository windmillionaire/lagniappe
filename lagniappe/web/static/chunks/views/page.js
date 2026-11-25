/*! Third-party licenses: /third-party-licenses.txt */
import { s as setIcon } from '../ui-resources.js?v=b1ee16b4';
import { w as withTransition } from '../foundation.js?v=b1ee16b4';
import { E as Entity } from '../entity-foundation.js?v=b1ee16b4';
import '../upstreamUnavailable.js?v=b1ee16b4';
import '../connectivity.js?v=b1ee16b4';
import '../core-foundation.js?v=b1ee16b4';

class Page extends Entity {
  async reconcilePollingSubscriptions() {
    await super.reconcilePollingSubscriptions();
    const component = this.components.tasks;
    const list = Object.values(component?.widgets || {}).find(
      (widget) => widget?.name === "PageTaskList" && widget.loaded
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
        revision: this.elt.dataset.collectionRevision || null
      },
      {
        mode: "periodic",
        initial: "scheduled",
        onResult: async (result) => {
          if (result.status === "changed") {
            await this._refreshCollectionComponents([component]);
          }
        }
      }
    );
  }
  async init() {
    this.photoHasImage = this.elt.dataset.hasImage === "true";
    this.photoOpen = this.photoHasImage && localStorage.getItem(`${this.hash}-photo-visible`) !== "false";
    this.photoToolsOpen = false;
    this.photoGenerationReturnOpen = null;
    this.elt.addEventListener("click", (event) => this._photoClick(event));
    const taskId = new URLSearchParams(window.location.search).get("task") || this.elt.dataset.focusTask;
    if (taskId) {
      localStorage.setItem(`${this.hash}-active`, "tasks");
      this.postRender = this._focusTask.bind(this, taskId);
    }
    await super.init();
    const photo = this.elt.querySelector("#photo");
    if (photo) {
      const component = this.getComponent(photo);
      const initiallyVisible = component?.active || this.isSecondaryCardVisible(photo);
      if (initiallyVisible && component && !component.active) {
        await component.activate("PagePhoto");
      }
    }
  }
  get secondaryCard() {
    const available = this.mobile ? this.photoHasImage || this.photoToolsOpen : this.photoOpen;
    if (!available) return null;
    return this.elt.querySelector("#photo");
  }
  _initialTabId() {
    const tabId = super._initialTabId();
    return tabId === "photo" && (!this.mobile || !this.secondaryCard) ? "info" : tabId;
  }
  _tabChange(event) {
    super._tabChange(event);
    if (event.detail.subcomponent.elt.dataset.tab === "true") {
      this._syncPhotoControls(event.detail.subcomponent.name);
    }
  }
  async updateLayout(options = {}) {
    return super.updateLayout({
      secondary: this.elt.querySelector("#photo"),
      secondaryActive: Boolean(this.secondaryCard),
      ...options
    });
  }
  _commitLayoutBody(prepared) {
    const tabId = super._commitLayoutBody(prepared);
    this._syncPhotoControls(tabId);
    return tabId;
  }
  _syncPhotoControls(tabId = this.photoActiveTab || this._initialTabId() || "info", controls = this.elt.querySelector(
    "[data-role='photo-prompt']"
  )) {
    this.photoActiveTab = tabId;
    if (!controls) return;
    controls.dataset.visible = !this.mobile || !this.photoHasImage && tabId === "info" ? "true" : "false";
    const toggle = controls.querySelector(
      "[data-role='photo-upload']"
    );
    if (!toggle) return;
    const icon = this.photoHasImage ? this.photoOpen ? "visibility.visible" : "visibility.hidden" : "upload";
    const label = this.photoHasImage ? this.photoOpen ? "Hide page image" : "Show page image" : this.photoOpen ? "Close image upload" : "Upload page image";
    const iconElement = toggle.querySelector("[data-icon]");
    if (iconElement) setIcon(iconElement, icon);
    toggle.title = label;
    toggle.setAttribute("aria-label", label);
    toggle.setAttribute("aria-expanded", String(this.photoOpen));
    controls.querySelectorAll("button").forEach((button) => {
      button.disabled = Boolean(this.photoBusy);
    });
    this.elt.querySelectorAll("button[lp-show='photo:active']").forEach((button) => {
      button.hidden = !this.photoHasImage && !this.photoToolsOpen;
    });
  }
  setPhotoBusy(busy) {
    this.photoBusy = busy;
    this._syncPhotoControls();
  }
  async _photoClick(event) {
    const button = event.target?.closest?.(
      "[data-role='photo-upload'], [data-role='photo-generate']"
    );
    if (!button || this.photoBusy) return;
    const controls = button.closest("[data-role='photo-prompt']");
    if (!controls) return;
    const error = controls.querySelector(
      "[data-role='photo-prompt-error']"
    );
    if (!error) return;
    error.dataset.visible = "false";
    this.setPhotoBusy(true);
    try {
      const generate = button.dataset.role === "photo-generate";
      const component = this.getComponent(
        this.elt.querySelector("#photo")
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
          const photo = component.active;
          if (generate) photo?.showGenerateForm({ transition: false });
          else photo?.hideGenerateForm({ transition: false });
        }
      });
    } catch (failure) {
      error.textContent = failure instanceof Error && failure.message || "Unable to show image tools.";
      error.dataset.visible = "true";
    } finally {
      this.setPhotoBusy(false);
    }
  }
  async cancelPhotoGeneration(widget) {
    this.photoOpen = this.photoGenerationReturnOpen ?? this.photoHasImage;
    this.photoToolsOpen = this.photoOpen && !this.photoHasImage;
    this.photoGenerationReturnOpen = null;
    await this.updateLayout({
      activeTabId: this.mobile && !this.secondaryCard ? "info" : null,
      mutate: () => () => widget.hideGenerateForm({ transition: false })
    });
    this.elt.querySelector(
      this.mobile && this.secondaryCard ? "#photo [data-role='upload-menu']" : "[data-role='photo-generate']"
    )?.focus();
  }
  async updatePhotoImage(hasImage, mutate) {
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
      }
    });
  }
  async _focusTask(taskId) {
    const taskTab = this.getComponent(this.elt.querySelector("#tasks"));
    if (!taskTab) return;
    await taskTab.activate("PageTaskList");
    await taskTab.prepareRender(true);
    await withTransition(() => taskTab.render(true), {
      label: "page:focus-task-tab"
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

export { Page as default };
