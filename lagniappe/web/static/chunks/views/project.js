/*! Third-party licenses: /third-party-licenses.txt */
import { E as Entity } from '../entity-foundation.js?v=be396a6a';
import '../core-foundation.js?v=be396a6a';
import '../connectivity.js?v=be396a6a';
import '../foundation.js?v=be396a6a';
import '../upstreamUnavailable.js?v=be396a6a';

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
