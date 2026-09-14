import { mergeAttributes } from "@tiptap/core";
import Image from "@tiptap/extension-image";

/**
 * @testable true
 * @tests tests_e2e/003_forms/test_003f_builder_drafts.py::test_image_layout_survives_builder_save_and_reload
 * @matrix editor html-field : image-layout
 */
const getImageStyles = (attrs) => {
	const styles = [`width: ${attrs.width || "100%"}`, "display: block"];

	if (attrs.float && attrs.float !== "none") {
		styles.push(
			`float: ${attrs.float}`,
			attrs.float === "left" ? "margin: 0 1em 1em 0" : "margin: 0 0 1em 1em",
		);
	} else {
		styles.push("float: none");
		switch (attrs.alignment) {
			case "left":
				styles.push("margin-right: auto", "margin-left: 0");
				break;
			case "right":
				styles.push("margin-left: auto", "margin-right: 0");
				break;
			default:
				styles.push("margin-left: auto", "margin-right: auto");
		}
	}

	return styles.join("; ");
};

export const CustomImage = Image.extend({
	addAttributes() {
		return {
			...Image.config.addAttributes(),
			width: {
				default: "100%",
				rendered: false,
				parseHTML: (element) => element.style.width || "100%",
			},
			float: {
				default: "none",
				rendered: false,
				parseHTML: (element) => element.style.float || "none",
			},
			alignment: {
				default: "center",
				rendered: false,
				parseHTML: (element) => {
					const style = element.style;
					if (style.marginLeft === "auto" && style.marginRight === "auto")
						return "center";
					if (style.marginLeft === "auto") return "right";
					if (style.marginRight === "auto") return "left";
					return "center";
				},
			},
		};
	},

	renderHTML({ node, HTMLAttributes }) {
		return [
			"img",
			mergeAttributes(this.options.HTMLAttributes, HTMLAttributes, {
				style: getImageStyles(node.attrs),
			}),
		];
	},

	addNodeView() {
		return ({ node }) => {
			const img = document.createElement("img");
			img.src = node.attrs.src;
			img.alt = node.attrs.alt || "";
			if (node.attrs.title) img.title = node.attrs.title;
			img.style.cssText = getImageStyles(node.attrs);

			return {
				dom: img,
				update(updatedNode) {
					if (updatedNode.type.name !== "image") return false;
					// Update attributes in place without recreating DOM
					img.src = updatedNode.attrs.src;
					img.alt = updatedNode.attrs.alt || "";
					if (updatedNode.attrs.title) img.title = updatedNode.attrs.title;
					img.style.cssText = getImageStyles(updatedNode.attrs);
					return true;
				},
			};
		};
	},

	addCommands() {
		return {
			...Image.config.addCommands(),
			setImageWidth:
				(delta) =>
				({ tr, dispatch }) => {
					const { selection } = tr;
					const node = tr.doc.nodeAt(selection.from);
					if (node && node.type.name === "image") {
						const currentWidth = parseInt(node.attrs.width, 10) || 100;
						const newWidth = Math.max(10, Math.min(100, currentWidth + delta));
						if (dispatch) {
							tr.setNodeMarkup(selection.from, null, {
								...node.attrs,
								width: `${newWidth}%`,
							});
							dispatch(tr);
						}
						return true;
					}
					return false;
				},
			setImageFloat:
				(float) =>
				({ tr, dispatch }) => {
					const { selection } = tr;
					const node = tr.doc.nodeAt(selection.from);
					if (node && node.type.name === "image") {
						if (dispatch) {
							tr.setNodeMarkup(selection.from, null, {
								...node.attrs,
								float,
								alignment: float === "none" ? node.attrs.alignment : "center",
							});
							dispatch(tr);
						}
						return true;
					}
					return false;
				},
			setImageAlignment:
				(alignment) =>
				({ tr, dispatch }) => {
					const { selection } = tr;
					const node = tr.doc.nodeAt(selection.from);
					if (node && node.type.name === "image") {
						if (dispatch) {
							tr.setNodeMarkup(selection.from, null, {
								...node.attrs,
								alignment,
								float: "none",
							});
							dispatch(tr);
						}
						return true;
					}
					return false;
				},
		};
	},
});
