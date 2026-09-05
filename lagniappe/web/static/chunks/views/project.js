/*! Third-party licenses: /third-party-licenses.txt */
import { E as Entity } from '../entity-foundation.js?v=bdd0711b';
import '../core-foundation.js?v=bdd0711b';
import '../connectivity.js?v=bdd0711b';
import '../foundation.js?v=bdd0711b';
import '../upstreamUnavailable.js?v=bdd0711b';

/**
 * @testable true
 * @tests tests_e2e/004_projects/test_004g_project_mobile_ui.py::test_mobile_model_tasks_rejoins_section_switching
 * @matrix projects : mobile-model-tasks
 */
class Project extends Entity {
	get secondaryCard() {
		return this.elt.querySelector("#model-tasks");
	}
}

export { Project as default };
