/*! Third-party licenses: /third-party-licenses.txt */
import { F as FormWidget } from './formWidget.js?v=bf6747aa';
import './controller.js?v=bf6747aa';
import './primitives.js?v=bf6747aa';
import './styles.js?v=bf6747aa';
import './icons.js?v=bf6747aa';
import './foundation.js?v=bf6747aa';
import './upstreamUnavailable.js?v=bf6747aa';
import './connectivity.js?v=bf6747aa';
import './loader.js?v=bf6747aa';
import './modal.js?v=bf6747aa';
import './formRepresentation.js?v=bf6747aa';

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
