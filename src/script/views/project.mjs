import Entity from "./base/entity";

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

export default Project;
