/*! Third-party licenses: /third-party-licenses.txt */
import { E as Entity } from '../entity-foundation.js?v=bb7cd952';
import '../core-foundation.js?v=bb7cd952';
import '../connectivity.js?v=bb7cd952';
import '../foundation.js?v=bb7cd952';
import '../notificationState.js?v=bb7cd952';

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
