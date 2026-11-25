/*! Third-party licenses: /third-party-licenses.txt */
import { E as Entity } from '../entity-foundation.js?v=b1ee16b4';
import '../core-foundation.js?v=b1ee16b4';
import '../connectivity.js?v=b1ee16b4';
import '../foundation.js?v=b1ee16b4';
import '../upstreamUnavailable.js?v=b1ee16b4';

class Project extends Entity {
  get secondaryCard() {
    return this.elt.querySelector("#model-tasks");
  }
}

export { Project as default };
