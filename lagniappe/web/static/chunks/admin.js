/*! Third-party licenses: /third-party-licenses.txt */
import { E as Entity } from './entity.js?v=bda9a134';
import './core.js?v=bda9a134';
import './entityMenu.js?v=bda9a134';
import './shared.js?v=bda9a134';
import './combobox.js?v=bda9a134';
import './primitives.js?v=bda9a134';
import './results2.js?v=bda9a134';
import './formatting.js?v=bda9a134';
import './dropdown.js?v=bda9a134';

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
