/*! Third-party licenses: /third-party-licenses.txt */
import { E as Entity } from '../entity-foundation.js?v=ba683140';
import '../core-foundation.js?v=ba683140';
import '../connectivity.js?v=ba683140';
import '../foundation.js?v=ba683140';
import '../upstreamUnavailable.js?v=ba683140';

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
