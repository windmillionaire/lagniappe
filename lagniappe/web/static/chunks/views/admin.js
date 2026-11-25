/*! Third-party licenses: /third-party-licenses.txt */
import { E as Entity } from '../entity-foundation.js?v=b8c49d0d';
import '../core-foundation.js?v=b8c49d0d';
import '../connectivity.js?v=b8c49d0d';
import '../foundation.js?v=b8c49d0d';
import '../upstreamUnavailable.js?v=b8c49d0d';

class Admin extends Entity {
  constructor(node) {
    super(node);
    this._defaultTabId = node.dataset.defaultTab || "settings";
  }
}

export { Admin as default };
