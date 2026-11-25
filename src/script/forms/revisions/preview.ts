import type { FormRevisionResponse } from "../../types/forms.d.ts";
import type { LoadedWidget } from "../../types/widgets";
import type { FormWidget } from "../../widgets/base/formWidget.ts";
import { loadWidget } from "../../widgets/loader.ts";

/**
 * Build a fully rendered, detached copy of a form widget for revision
 * comparison. The response document is cloned so the original remains
 * available if the user chooses to apply it.
 *
 */
export async function loadRevisionPreview(
	liveWidget: Pick<FormWidget, "key" | "kind" | "name" | "readonly">,
	response: FormRevisionResponse,
	{ readonly = liveWidget.readonly } = {},
): Promise<FormWidget | null> {
	const html = response.html;
	if (!html) return null;
	const responseTarget = html.querySelector(
		`[data-widget='${liveWidget.name}']`,
	);
	if (!responseTarget) return null;

	const container = document.createElement("div");
	container.appendChild(responseTarget.cloneNode(true));
	const view = {
		key: liveWidget.key,
		kind: liveWidget.kind,
		readonly,
		online: true,
		hidden: false,
		showExtractReloadNotice() {},
	};
	const component = {
		elt: container,
		view,
		key: liveWidget.key,
		kind: liveWidget.kind,
		widgets: {},
		get readonly() {
			return readonly;
		},
	};
	const preview = (await loadWidget(component, liveWidget.name, {
		revisionPreview: true,
		schema: response.schema ?? null,
		submission: response.submission ?? null,
	})) as LoadedWidget & FormWidget;
	const previewResponse = {
		...response,
		html: html.cloneNode(true) as Document,
	};

	if (preview.updated) await preview.updated(previewResponse);
	if (preview.prereconcile) await preview.prereconcile();
	if (preview.postreconcile) preview.postreconcile();
	return preview;
}
