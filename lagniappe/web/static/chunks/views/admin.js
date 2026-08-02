/*! Third-party licenses: /third-party-licenses.txt */
import { E as Entity } from '../entity.js?v=b55964c3';
import '../core.js?v=b55964c3';
import '../connectivity.js?v=b55964c3';
import '../endpoints.js?v=b55964c3';
import '../errors.js?v=b55964c3';
import '../request.js?v=b55964c3';
import '../utilities.js?v=b55964c3';
import '../shell.js?v=b55964c3';

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
