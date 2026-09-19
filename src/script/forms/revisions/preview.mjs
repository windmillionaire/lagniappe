import { loadWidget } from "../../widgets/loader";

/**
 * Build a fully rendered, detached copy of a form widget for revision
 * comparison. The response document is cloned so the original remains
 * available if the user chooses to apply it.
 *
 * @testable infrastructure
 */
export async function loadRevisionPreview(
	liveWidget,
	response,
	{ readonly = liveWidget.readonly } = {},
) {
	const responseTarget = response.html?.querySelector(
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
	const preview = await loadWidget(component, liveWidget.name, {
		revisionPreview: true,
		schema: response.schema ?? null,
		submission: response.submission ?? null,
	});
	const previewResponse = {
		...response,
		html: response.html?.cloneNode(true),
	};

	if (preview.updated) await preview.updated(previewResponse);
	if (preview.prereconcile) await preview.prereconcile();
	if (preview.postreconcile) preview.postreconcile();
	return preview;
}
