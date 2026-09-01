/*! Third-party licenses: /third-party-licenses.txt */
import { E as Entity } from '../entity-foundation.js?v=b506293e';
import '../core-foundation.js?v=b506293e';
import '../connectivity.js?v=b506293e';
import '../foundation.js?v=b506293e';
import '../upstreamUnavailable.js?v=b506293e';

/**
 * @testable true
 * @tests tests_e2e/002_home/test_002f_home_directory.py::test_admin_directory_link_opens_admin_settings
 * @matrix admin : page-load site-settings
 */
class Admin extends Entity {
	constructor(node) {
		super(node);
		this._defaultTabId = node.dataset.defaultTab || "settings";
	}
}

export { Admin as default };
