/*! Third-party licenses: /third-party-licenses.txt */
import { E as Entity } from '../entity-foundation.js?v=b438e48a';
import '../core-foundation.js?v=b438e48a';
import '../connectivity.js?v=b438e48a';
import '../foundation.js?v=b438e48a';
import '../upstreamUnavailable.js?v=b438e48a';

class Project extends Entity {
  get secondaryCard() {
    return this.elt.querySelector("#model-tasks");
  }
}

export { Project as default };
