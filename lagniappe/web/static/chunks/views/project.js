/*! Third-party licenses: /third-party-licenses.txt */
import { E as Entity } from '../entity-foundation.js?v=bf7d4d98';
import '../core-foundation.js?v=bf7d4d98';
import '../connectivity.js?v=bf7d4d98';
import '../foundation.js?v=bf7d4d98';
import '../upstreamUnavailable.js?v=bf7d4d98';

class Project extends Entity {
  get secondaryCard() {
    return this.elt.querySelector("#model-tasks");
  }
}

export { Project as default };
