/*! Third-party licenses: /third-party-licenses.txt */
import { E as Entity } from '../entity-foundation.js?v=b8e0e957';
import '../core-foundation.js?v=b8e0e957';
import '../connectivity.js?v=b8e0e957';
import '../foundation.js?v=b8e0e957';
import '../upstreamUnavailable.js?v=b8e0e957';

class Project extends Entity {
  get secondaryCard() {
    return this.elt.querySelector("#model-tasks");
  }
}

export { Project as default };
