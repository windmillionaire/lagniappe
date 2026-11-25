/*! Third-party licenses: /third-party-licenses.txt */
import { E as Entity } from '../entity-foundation.js?v=b1ee16b4';
import '../core-foundation.js?v=b1ee16b4';
import '../connectivity.js?v=b1ee16b4';
import '../foundation.js?v=b1ee16b4';
import '../upstreamUnavailable.js?v=b1ee16b4';

class Admin extends Entity {
  constructor(node) {
    super(node);
    this._defaultTabId = node.dataset.defaultTab || "settings";
  }
}

export { Admin as default };
