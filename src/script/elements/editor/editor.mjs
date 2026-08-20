import { Editor } from "@tiptap/core";
import { Collaboration } from "@tiptap/extension-collaboration";
import { FontFamily } from "@tiptap/extension-font-family";
import { TaskItem, TaskList } from "@tiptap/extension-list";
import { Subscript } from "@tiptap/extension-subscript";
import { Superscript } from "@tiptap/extension-superscript";
import { TableKit } from "@tiptap/extension-table";
import { TextAlign } from "@tiptap/extension-text-align";
import { Color, TextStyle } from "@tiptap/extension-text-style";
import { Typography } from "@tiptap/extension-typography";
import { Youtube } from "@tiptap/extension-youtube";
import { StarterKit } from "@tiptap/starter-kit";
import {
	CustomImage,
	CustomLink,
	EditorPaste,
	FlashRemoteChanges,
	LagniappeMention,
	SelectionHighlight,
	TabCharacter,
} from "./extensions";

/**
 * @testable infrastructure
 */
const focusEditorOnSurfacePointerDown = (editor, target) => {
	/**
	 * @testable false
	 * @covered-by src/script/elements/editor/editor.mjs::focusEditorOnSurfacePointerDown
	 * @reason local event callback owned by the surface focus helper
	 */
	const focusEditor = (event) => {
		if (event.defaultPrevented || event.button !== 0) return;
		if (!editor.isEditable || editor.isDestroyed || !editor.view?.dom) return;
		if (editor.view.dom.contains(event.target)) return;

		event.preventDefault();
		editor.commands.focus();
	};

	target.addEventListener("pointerdown", focusEditor);
	editor.on("destroy", () => {
		target.removeEventListener("pointerdown", focusEditor);
	});
};

/**
 * @testable infrastructure
 */
export const collaborativeEditor = (target, ydoc, editable = true) => {
	const extensions = [
		StarterKit.configure({
			link: false,
			underline: true,
			history: false,
		}),
		TaskList,
		TaskItem.configure({
			nested: true,
		}),
		CustomLink.configure({
			openOnClick: false,
			autolink: true,
			defaultProtocol: "https",
		}),
		Typography,
		TableKit.configure({
			table: {
				HTMLAttributes: {
					class: "editor-table",
				},
				renderWrapper: true,
			},
		}),
		Color,
		TextStyle,
		TextAlign.configure({
			types: ["heading", "paragraph"],
		}),
		Superscript,
		Subscript,
		Youtube.configure({
			nocookie: true,
		}),
		CustomImage.configure({
			HTMLAttributes: {
				class: "editor-image",
			},
		}),
		FontFamily.configure({
			types: ["textStyle"],
		}),
		Collaboration.configure({
			document: ydoc,
			field: "default",
			yUndoOptions: {
				protectedUndo: true,
				trackedOrigins: new Set([null]),
			},
		}),
		FlashRemoteChanges,
		SelectionHighlight,
		EditorPaste,
		TabCharacter,
		LagniappeMention,
	];

	const editor = new Editor({
		element: target,
		editable,
		extensions,
	});

	focusEditorOnSurfacePointerDown(editor, target);

	return editor;
};

/**
 * @testable infrastructure
 */
export const independentEditor = (target) => {
	const extensions = [
		StarterKit.configure({
			link: false,
			underline: true,
			history: true,
		}),
		TaskList,
		TaskItem.configure({
			nested: true,
		}),
		CustomLink.configure({
			openOnClick: false,
			autolink: true,
			defaultProtocol: "https",
		}),
		Typography,
		TableKit.configure({
			table: {
				HTMLAttributes: {
					class: "editor-table",
				},
				renderWrapper: true,
			},
		}),
		Color,
		TextStyle,
		TextAlign.configure({
			types: ["heading", "paragraph"],
		}),
		Superscript,
		Subscript,
		Youtube.configure({
			nocookie: true,
		}),
		CustomImage.configure({
			HTMLAttributes: {
				class: "editor-image",
			},
		}),
		FontFamily.configure({
			types: ["textStyle"],
		}),
		SelectionHighlight,
		EditorPaste,
		TabCharacter,
	];

	const editor = new Editor({
		element: target,
		editable: true,
		extensions,
	});

	focusEditorOnSurfacePointerDown(editor, target);

	return editor;
};
