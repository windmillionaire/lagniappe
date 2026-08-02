/*! Third-party licenses: /third-party-licenses.txt */
import { E as Entity } from '../entity.js?v=be1b1fb2';
import '../core.js?v=be1b1fb2';
import '../connectivity.js?v=be1b1fb2';
import '../endpoints.js?v=be1b1fb2';
import '../errors.js?v=be1b1fb2';
import '../request.js?v=be1b1fb2';
import '../utilities.js?v=be1b1fb2';
import '../shell.js?v=be1b1fb2';

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
