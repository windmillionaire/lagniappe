/*! Third-party licenses: /third-party-licenses.txt */
import { E as Entity } from '../entity-foundation.js?v=b8e0e957';
import '../core-foundation.js?v=b8e0e957';
import '../connectivity.js?v=b8e0e957';
import '../foundation.js?v=b8e0e957';
import '../upstreamUnavailable.js?v=b8e0e957';

class Admin extends Entity {
  constructor(node) {
    super(node);
    this._defaultTabId = node.dataset.defaultTab || "settings";
  }
}

export { Admin as default };
