/*! Third-party licenses: /third-party-licenses.txt */
import { F as FormWidget } from './formWidget.js?v=b43106f0';
import './controller.js?v=b43106f0';
import './primitives.js?v=b43106f0';
import './styles.js?v=b43106f0';
import './icons.js?v=b43106f0';
import './foundation.js?v=b43106f0';
import './upstreamUnavailable.js?v=b43106f0';
import './connectivity.js?v=b43106f0';
import './loader.js?v=b43106f0';
import './modal.js?v=b43106f0';
import './representation.js?v=b43106f0';

/**
 * @testable true
 * @tests tests_e2e/005_pages/test_005d_page_permissions.py::test_owner_can_open_page_permissions_panel
 * @tests tests_e2e/005_pages/test_005e_page_access_restrictions.py::test_page_restrictions_save_drafts_and_show_each_source
 * @matrix pages : permission-gates permissions-panel access-restrictions explicit-submit group-restricted owner-restricted source-summary
 */
class PagePermissions extends FormWidget {
	constructor(attributes) {
		super(attributes);
		this.messages = {
			submit: "Save Restrictions",
			submitting: "Saving Restrictions",
			submitted: "Restrictions Saved",
		};
	}
}

export { PagePermissions };
