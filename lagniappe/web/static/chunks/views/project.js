/*! Third-party licenses: /third-party-licenses.txt */
import { E as Entity } from '../entity-foundation.js?v=b6c361d7';
import '../core-foundation.js?v=b6c361d7';
import '../connectivity.js?v=b6c361d7';
import '../foundation.js?v=b6c361d7';
import '../upstreamUnavailable.js?v=b6c361d7';

class Project extends Entity {
  get secondaryCard() {
    return this.elt.querySelector("#model-tasks");
  }
}

export { Project as default };
