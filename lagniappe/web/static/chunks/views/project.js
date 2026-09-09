/*! Third-party licenses: /third-party-licenses.txt */
import { E as Entity } from '../entity-foundation.js?v=bb100edc';
import '../core-foundation.js?v=bb100edc';
import '../connectivity.js?v=bb100edc';
import '../foundation.js?v=bb100edc';
import '../upstreamUnavailable.js?v=bb100edc';

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
