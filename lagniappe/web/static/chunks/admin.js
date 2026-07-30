/*! Third-party licenses: /third-party-licenses.txt */
import { E as Entity } from './entity.js?v=b30f3f24';
import './core.js?v=b30f3f24';
import './entityMenu.js?v=b30f3f24';
import './shared.js?v=b30f3f24';
import './combobox.js?v=b30f3f24';
import './primitives.js?v=b30f3f24';
import './results2.js?v=b30f3f24';
import './formatting.js?v=b30f3f24';
import './dropdown.js?v=b30f3f24';

/**
 * @testable true
 * @tests tests_e2e/002_home/test_002f_home_directory.py::test_admin_directory_link_opens_admin_settings
 * @features admin
 * @dimensions page-load site-settings
 */
class Admin extends Entity {
	constructor(node) {
		super(node);
		this._defaultTabId = node.dataset.defaultTab || "settings";
	}
}

export { Admin as default };
