/*! Third-party licenses: /third-party-licenses.txt */
import { E as Entity } from '../entity-foundation.js?v=b6ea3fe0';
import '../core-foundation.js?v=b6ea3fe0';
import '../connectivity.js?v=b6ea3fe0';
import '../foundation.js?v=b6ea3fe0';
import '../upstreamUnavailable.js?v=b6ea3fe0';

class Project extends Entity {
  get secondaryCard() {
    return this.elt.querySelector("#model-tasks");
  }
}

export { Project as default };
