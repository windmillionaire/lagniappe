/*! Third-party licenses: /third-party-licenses.txt */
import { E as Entity } from '../entity-foundation.js?v=be84e1e9';
import '../core-foundation.js?v=be84e1e9';
import '../connectivity.js?v=be84e1e9';
import '../foundation.js?v=be84e1e9';
import '../upstreamUnavailable.js?v=be84e1e9';

class File extends Entity {
  constructor(node) {
    super(node);
    this._defaultTabId = node.dataset.defaultTab || "info";
    this._reloadAfterExtract = this._reloadAfterExtract.bind(this);
  }
  async init() {
    await super.init();
    this.elt.addEventListener("click", this._reloadAfterExtract);
  }
  afterReconcileChange(change) {
    if (change.type !== "extract-complete") return;
    if (change.key !== this.key) return;
    if (this.elt.querySelector("#text")) return;
    this.showExtractReloadNotice();
  }
  showExtractReloadNotice() {
    const notice = this.elt.querySelector(
      "[data-role='extract-reload']"
    );
    if (!notice) return;
    notice.dataset.visible = "true";
    this.addFlash(notice);
  }
  _reloadAfterExtract(event) {
    const button = event.target?.closest?.(
      "[data-role='extract-reload-button']"
    );
    if (!button) return;
    window.location.reload();
  }
  destroy() {
    this.elt.removeEventListener("click", this._reloadAfterExtract);
    super.destroy();
  }
}

export { File as default };
