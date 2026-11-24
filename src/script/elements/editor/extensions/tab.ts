import { Extension } from "@tiptap/core";

export const TabCharacter = Extension.create({
	name: "tabCharacter",

	addKeyboardShortcuts() {
		return {
			Tab: () => {
				if (
					this.editor.isActive("bulletList") ||
					this.editor.isActive("orderedList") ||
					this.editor.isActive("taskList")
				) {
					return false;
				}
				return this.editor.commands.insertContent("\t");
			},
		};
	},
});
