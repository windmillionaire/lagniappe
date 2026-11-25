/*! Third-party licenses: /third-party-licenses.txt */
import { E as Entity } from '../entity-foundation.js?v=be84e1e9';
import '../core-foundation.js?v=be84e1e9';
import '../connectivity.js?v=be84e1e9';
import '../foundation.js?v=be84e1e9';
import '../upstreamUnavailable.js?v=be84e1e9';

class Project extends Entity {
  get secondaryCard() {
    return this.elt.querySelector("#model-tasks");
  }
}

export { Project as default };
