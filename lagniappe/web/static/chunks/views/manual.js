/*! Third-party licenses: /third-party-licenses.txt */
import { S as ShellView, E as ENDPOINTS, r as request, w as withTransition } from '../foundation.js?v=b438e48a';
import '../upstreamUnavailable.js?v=b438e48a';
import '../connectivity.js?v=b438e48a';

class Manual extends ShellView {
  async init() {
    await super.init();
    this.endpoints = ENDPOINTS.manual;
    if (!this.elt) return;
    const sectionData = this.elt.querySelector("#manual-nav-button")?.dataset?.sections;
    const sections = JSON.parse(sectionData || "[]");
    this.sections = new Map(sections.map((section) => [section.key, section]));
    this._manualClick = (e) => {
      const target = e.target;
      const mobileNavButton = target?.closest?.("#manual-nav-button");
      if (mobileNavButton && this.mobile && !this.mobileDropdown) {
        e.preventDefault();
        e.stopPropagation();
        void this.runColdAction(
          mobileNavButton,
          () => this._ensureMobileDropdown(),
          (dropdown) => dropdown?.showPanel?.(),
          mobileNavButton
        );
        return;
      }
      const button = target?.closest?.("[data-section]");
      if (button?.dataset.section) {
        e.preventDefault();
        this.fetchSection(button.dataset.section, true);
      }
    };
    this.elt.addEventListener("click", this._manualClick);
    this._onPopState = (e) => {
      const state = e.state;
      if (state?.manualSection) this.fetchSection(state.manualSection, false);
    };
    window.addEventListener("popstate", this._onPopState);
    this._manualMobileResize = () => {
      if (this.mobile) void this._ensureMobileDropdown();
      else this._destroyMobileDropdown();
    };
    this.elt.addEventListener("mobile-resize", this._manualMobileResize);
    if (this.mobile) await this._ensureMobileDropdown();
    return this;
  }
  _updateMetadata(key) {
    const metadata = this.sections.get(key)?.metadata;
    if (!metadata) return null;
    document.title = metadata.title;
    const description = document.querySelector("meta[name='description']");
    const robots = document.querySelector("meta[name='robots']");
    const canonical = document.querySelector("link[rel='canonical']");
    description?.setAttribute("content", metadata.description);
    robots?.setAttribute("content", metadata.robots);
    canonical?.setAttribute("href", metadata.canonical_url);
    return metadata;
  }
  async _ensureMobileDropdown() {
    if (this.mobileDropdown || this._mobileDropdownPromise) {
      return this.mobileDropdown ?? this._mobileDropdownPromise ?? null;
    }
    const mobileNavButton = this.elt.querySelector("#manual-nav-button");
    if (!mobileNavButton) return null;
    this._mobileDropdownPromise = import('../combobox.js?v=b438e48a').then(function (n) { return n.e; }).then(({ Dropdown }) => {
      if (this._destroyed || !this.mobile) return null;
      const menu = {
        items: Array.from(this.sections.values()).map((section) => ({
          name: section.name,
          icon: section.icon,
          kind: section.kind,
          onClick: () => this.fetchSection(section.key, true)
        }))
      };
      this.mobileDropdown = new Dropdown(mobileNavButton).init(menu);
      return this.mobileDropdown;
    }).catch((error) => {
      this.reportStartupError(error, mobileNavButton, "manual-dropdown");
      return null;
    }).finally(() => {
      this._mobileDropdownPromise = null;
    });
    return this._mobileDropdownPromise;
  }
  _destroyMobileDropdown() {
    this.mobileDropdown?.destroy?.();
    this.mobileDropdown = null;
  }
  initManual() {
    return { elt: this.elt };
  }
  async fetchSection(key, pushState) {
    if (this.loading) return;
    this.loading = true;
    const response = await request.get(this.endpoints.section(key));
    if (response?.html) {
      const target = this.elt.querySelector("[data-role='manual-content']");
      const newTarget = response.html.querySelector("body");
      await withTransition(
        () => {
          if (newTarget) target?.replaceChildren(newTarget);
          const metadata = this._updateMetadata(key);
          if (pushState) {
            const url = metadata?.path || `/manual/${key}`;
            history.pushState({ manualSection: key }, "", url);
          }
        },
        { label: "manual:change-section" }
      );
    }
    this.loading = false;
    window.scrollTo({ top: 0, behavior: "auto" });
  }
  destroy() {
    if (this._onPopState) {
      window.removeEventListener("popstate", this._onPopState);
    }
    if (this._manualClick)
      this.elt.removeEventListener("click", this._manualClick);
    if (this._manualMobileResize)
      this.elt.removeEventListener("mobile-resize", this._manualMobileResize);
    this._destroyMobileDropdown();
    super.destroy();
  }
}

export { Manual as default };
