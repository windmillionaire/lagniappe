/*! Third-party licenses: /third-party-licenses.txt */
import { E as Entity } from '../entity-foundation.js?v=bbf4a50a';
import '../core-foundation.js?v=bbf4a50a';
import '../connectivity.js?v=bbf4a50a';
import '../foundation.js?v=bbf4a50a';
import '../upstreamUnavailable.js?v=bbf4a50a';

class Admin extends Entity {
  constructor(node) {
    super(node);
    this._defaultTabId = node.dataset.defaultTab || "settings";
  }
}

export { Admin as default };
