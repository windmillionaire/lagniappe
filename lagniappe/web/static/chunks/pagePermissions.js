/*! Third-party licenses: /third-party-licenses.txt */
import { F as FormWidget } from './formWidget.js?v=b158c05a';
import './controller.js?v=b158c05a';
import './primitives.js?v=b158c05a';
import './styles.js?v=b158c05a';
import './icons.js?v=b158c05a';
import './foundation.js?v=b158c05a';
import './upstreamUnavailable.js?v=b158c05a';
import './connectivity.js?v=b158c05a';
import './loader.js?v=b158c05a';
import './modal.js?v=b158c05a';
import './representation.js?v=b158c05a';

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
