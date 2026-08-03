/*! Third-party licenses: /third-party-licenses.txt */
import { E as Entity } from '../entity.js?v=b26991f5';
import '../core.js?v=b26991f5';
import '../connectivity.js?v=b26991f5';
import '../endpoints.js?v=b26991f5';
import '../errors.js?v=b26991f5';
import '../request.js?v=b26991f5';
import '../utilities.js?v=b26991f5';
import '../shell.js?v=b26991f5';

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
