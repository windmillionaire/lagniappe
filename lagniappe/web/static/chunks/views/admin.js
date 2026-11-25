/*! Third-party licenses: /third-party-licenses.txt */
import { E as Entity } from '../entity-foundation.js?v=bcd14aa3';
import '../core-foundation.js?v=bcd14aa3';
import '../connectivity.js?v=bcd14aa3';
import '../foundation.js?v=bcd14aa3';
import '../upstreamUnavailable.js?v=bcd14aa3';

class Admin extends Entity {
  constructor(node) {
    super(node);
    this._defaultTabId = node.dataset.defaultTab || "settings";
  }
}

export { Admin as default };
