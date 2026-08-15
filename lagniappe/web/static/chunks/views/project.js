/*! Third-party licenses: /third-party-licenses.txt */
import { E as Entity } from '../entity-foundation.js?v=b3ba4dd3';
import '../core-foundation.js?v=b3ba4dd3';
import '../connectivity.js?v=b3ba4dd3';
import '../foundation.js?v=b3ba4dd3';

/**
 * @testable true
 * @tests tests_e2e/004_projects/test_004b_info.py::test_toggle_tasks_attribute
 * @tests tests_e2e/004_projects/test_004g_project_mobile_ui.py::test_mobile_enabled_model_tasks_rejoins_section_switching
 * @features projects
 * @dimensions attribute-model-tasks mobile-model-tasks
 */
class Project extends Entity {
	get secondaryCard() {
		const modelTasks = this.elt.querySelector("#model-tasks");
		if (modelTasks?.dataset.hasAttribute === "false") return null;
		return modelTasks;
	}

	/**
	 * @testable false
	 * @covered-by src/script/views/base/entity.mjs::Entity._renderLayout
	 * @covered-by src/script/views/base/entity.mjs::Entity.updateLayout
	 * @reason project-specific inactive attribute guard feeds the shared layout renderer
	 */
	_prerender(tabId, secondaryElement = undefined) {
		const tab = this._tabElement(tabId);
		if (tab?.dataset.hasAttribute === "false") {
			tabId = this._defaultTabId;
		}
		return super._prerender(tabId, secondaryElement);
	}
}

export { Project as default };
