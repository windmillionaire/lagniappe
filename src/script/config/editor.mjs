const TOOLBAR_TOOLS = [
	{ command: "toggleBold", icon: "bold", title: "Bold", name: "bold" },
	{ command: "toggleItalic", icon: "italic", title: "Italic", name: "italic" },
	{
		command: "toggleBulletList",
		icon: "listUl",
		title: "Bullet List",
		name: "bulletList",
	},
	{
		command: "toggleOrderedList",
		icon: "listOl",
		title: "Ordered List",
		name: "orderedList",
	},
	{
		command: "toggleTaskList",
		icon: "checklist",
		title: "Task List",
		name: "taskList",
	},
	{ command: "undo", icon: "undo", title: "Undo" },
	{ command: "redo", icon: "redo", title: "Redo" },
	{ command: "toggleFocus", icon: "maximize", title: "Toggle Focus" },
	{ command: "documentHistory", icon: "history", title: "History" },
];

const TOOLBAR_MENUS = {
	style: {
		icon: "textStyle",
		title: "Style",
		items: [
			{
				command: "setFontFamily",
				title: "Font Family",
				icon: "fontStyle",
				form: true,
			},
			{
				command: "setColor",
				title: "Text Color",
				icon: "textColor",
				form: true,
			},
			{
				command: "toggleUnderline",
				title: "Underline",
				icon: "underline",
				name: "underline",
			},
			{
				command: "toggleStrike",
				title: "Strikethrough",
				icon: "strikethrough",
				name: "strike",
			},
			{
				command: "toggleCode",
				title: "Inline Code",
				icon: "code",
				name: "code",
			},
			{
				command: "toggleSuperscript",
				title: "Superscript",
				icon: "superscript",
				name: "superscript",
			},
			{
				command: "toggleSubscript",
				title: "Subscript",
				icon: "subscript",
				name: "subscript",
			},
			{ command: "clearFormat", title: "Clear Format", icon: "clearFormat" },
		],
	},
	headings: {
		icon: "h1",
		title: "Headings",
		items: [
			{
				command: "toggleHeading",
				title: "Heading 1",
				icon: "h1",
				args: { level: 1 },
				name: "level:1",
			},
			{
				command: "toggleHeading",
				title: "Heading 2",
				icon: "h2",
				args: { level: 2 },
				name: "level:2",
			},
			{
				command: "toggleHeading",
				title: "Heading 3",
				icon: "h3",
				args: { level: 3 },
				name: "level:3",
			},
			{ command: "setParagraph", title: "Paragraph", icon: "paragraph" },
		],
	},
	insert: {
		icon: "insert",
		title: "Insert",
		items: [
			{ command: "addLink", title: "Link", icon: "link", form: true },
			{ command: "addImage", title: "Image", icon: "image", form: true },
			{
				command: "addYouTube",
				title: "YouTube Video",
				icon: "youtube",
				form: true,
			},
			{
				command: "generateText",
				title: "Generate Text",
				icon: "generate",
				form: true,
			},
			{ command: "setHorizontalRule", title: "Horizontal Rule", icon: "minus" },
			{
				command: "toggleCodeBlock",
				title: "Code Block",
				icon: "code",
				name: "language:null",
			},
			{
				command: "toggleBlockquote",
				title: "Blockquote",
				icon: "quoteRight",
				name: "blockquote",
			},
		],
	},
	align: {
		icon: "alignMenu",
		title: "Align",
		items: [
			{
				command: "setTextAlign",
				title: "Align Left",
				icon: "alignLeft",
				args: "left",
				name: "textAlign:left",
			},
			{
				command: "setTextAlign",
				title: "Align Center",
				icon: "alignCenter",
				args: "center",
				name: "textAlign:center",
			},
			{
				command: "setTextAlign",
				title: "Align Right",
				icon: "alignRight",
				args: "right",
				name: "textAlign:right",
			},
			{
				command: "setTextAlign",
				title: "Align Justify",
				icon: "alignJustify",
				args: "justify",
				name: "textAlign:justify",
			},
		],
	},
};

const IMAGE_GROUPS = [
	[
		// Alignment
		{
			icon: "imageAlign.left",
			command: "setImageAlignment",
			args: "left",
			title: "Align left",
			name: "alignment:left",
		},
		{
			icon: "imageAlign.center",
			command: "setImageAlignment",
			args: "center",
			title: "Align center",
			name: "alignment:center",
		},
		{
			icon: "imageAlign.right",
			command: "setImageAlignment",
			args: "right",
			title: "Align right",
			name: "alignment:right",
		},
	],
	[
		// Float
		{
			icon: "floatLeft",
			command: "setImageFloat",
			args: "left",
			title: "Float left",
			name: "float:left",
		},
		{
			icon: "floatRight",
			command: "setImageFloat",
			args: "right",
			title: "Float right",
			name: "float:right",
		},
	],
	[
		// Size
		{
			icon: "minus",
			command: "setImageWidth",
			args: -10,
			title: "Decrease size",
		},
		{
			icon: "increase",
			command: "setImageWidth",
			args: 10,
			title: "Increase size",
		},
	],
];

const COLOR_MENU = [
	{ color: "rgb(0, 0, 0)", title: "Black" },
	{ color: "rgb(71, 85, 105)", title: "Slate" },
	{ color: "rgb(220, 38, 38)", title: "Red" },
	{ color: "rgb(234, 88, 12)", title: "Orange" },
	{ color: "rgb(202, 138, 4)", title: "Yellow" },
	{ color: "rgb(22, 163, 74)", title: "Green" },
	{ color: "rgb(8, 145, 178)", title: "Cyan" },
	{ color: "rgb(37, 99, 235)", title: "Blue" },
	{ color: "rgb(147, 51, 234)", title: "Purple" },
	{ color: "rgb(219, 39, 119)", title: "Pink" },
];

const USER_COLORS = [
	"rgba(220, 38, 38, 1)", // Red
	"rgba(234, 88, 12, 1)", // Orange
	"rgba(202, 138, 4, 1)", // Yellow
	"rgba(22, 163, 74, 1)", // Green
	"rgba(8, 145, 178, 1)", // Cyan
	"rgba(37, 99, 235, 1)", // Blue
	"rgba(147, 51, 234, 1)", // Purple
	"rgba(219, 39, 119, 1)", // Pink
];

const FONT_MENU = [
	{ style: "var(--font-serif)", name: "Serif" },
	{ style: "var(--font-sans)", name: "Sans" },
	{ style: "var(--font-mono)", name: "Mono" },
];

export {
	COLOR_MENU,
	FONT_MENU,
	IMAGE_GROUPS,
	TOOLBAR_MENUS,
	TOOLBAR_TOOLS,
	USER_COLORS,
};
