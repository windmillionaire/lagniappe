import { FormWidget, type FormWidgetSettings } from "./base/formWidget.ts";

export class PagePermissions extends FormWidget {
	constructor(attributes: FormWidgetSettings) {
		super(attributes);
		this.messages = {
			submit: "Save Restrictions",
			submitting: "Saving Restrictions",
			submitted: "Restrictions Saved",
		};
	}
}
