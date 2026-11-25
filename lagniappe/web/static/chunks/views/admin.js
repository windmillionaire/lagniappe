/*! Third-party licenses: /third-party-licenses.txt */
import { E as Entity } from '../entity-foundation.js?v=b74a2211';
import '../core-foundation.js?v=b74a2211';
import '../connectivity.js?v=b74a2211';
import '../foundation.js?v=b74a2211';
import '../upstreamUnavailable.js?v=b74a2211';

class Admin extends Entity {
  constructor(node) {
    super(node);
    this._defaultTabId = node.dataset.defaultTab || "settings";
  }
}

export { Admin as default };
