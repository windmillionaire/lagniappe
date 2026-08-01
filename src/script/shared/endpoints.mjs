export const ENDPOINTS = {
	CollaborativeDocument: (settings) => {
		return {
			sendUpdates: `/assets/${settings.key}/document/update`,
			saveDocument: `/assets/${settings.key}/document/save`,
			addImage: `/assets/${settings.key}/document/image`,
			generateText: `/assets/${settings.key}/document/generate`,
			removeUser: `/assets/${settings.key}/document/remove-user`,
			getContent: `/assets/${settings.key}/document/state`,
			history: `/assets/${settings.key}/document/history`,
		};
	},
	Filters: (settings) => {
		return {
			condition: `/filters/${settings.key}/condition`,
			options: `/filters/${settings.key}/options`,
			save: `/filters/${settings.key}/save`,
			test: `/filters/${settings.key}/test`,
			get: `/filters/${settings.key}/get`,
		};
	},
	FileInfo: (settings) => {
		return {
			html: `/files/${settings.key}/html`,
		};
	},
	PagePhoto: (settings) => {
		return {
			upload: `/assets/${settings.key}/add-page-image`,
			generate: `/assets/${settings.key}/generate-page-image`,
			remove: `/assets/${settings.key}/remove-page-image`,
		};
	},
	PageInfo: (settings) => {
		return {
			attribute: (attribute) =>
				`/pages/${settings.key}/attributes/${attribute}`,
			disablePhoto: `/pages/${settings.key}/attributes/photo`,
		};
	},
	ProjectInfo: (settings) => {
		return {
			attribute: (attribute) =>
				`/projects/${settings.key}/attributes/${attribute}`,
		};
	},
	SiteAiModels: () => {
		return {
			setAiSettings: "/set-ai-settings",
		};
	},
	SiteDeployment: () => {
		return {
			setDeploymentSettings: "/set-deployment-settings",
		};
	},
	SiteImage: () => {
		return {
			setSiteImage: "/set-site-image",
		};
	},
	SiteMaintenance: () => {
		return {
			siteConfiguration: "/site-configuration",
			siteUpdate: "/site-update",
			rebuildCache: "/rebuild-cache",
		};
	},
	SiteSettings: () => {
		return {
			siteSettings: "/site-settings",
		};
	},
	SiteExport: () => {
		return {
			start: "/site-export",
		};
	},
	HomeTaskList: () => {
		return {
			completeTask: (key) => {
				return `/tasks/${key}/complete`;
			},
			changeDueDate: (key) => {
				return `/tasks/${key}/change-due-date`;
			},
		};
	},
	TaskForm: (settings) => {
		return {
			latestHistorySubmission: `/tasks/${settings.key}/history/latest-submission`,
			saveDefaultField: `/tasks/${settings.key}/default-submission`,
		};
	},
	TaskUpload: (settings) => {
		return {
			upload: `/tasks/${settings.key}/upload-file`,
			remove: (fileKey) => `/tasks/${settings.key}/files/${fileKey}`,
		};
	},
	ImportData: () => {
		return {
			get: (key) => `/files/ingress?key=${key}`,
			setStage: (key) => `/files/ingress/${key}/stage`,
			update: (key) => `/files/ingress/${key}/update`,
			next: (key) => `/files/ingress/${key}/next`,
			import: (key) => `/files/ingress/${key}/import`,
			stop: (key) => `/files/ingress/${key}/stop`,
			deleteImported: (key) => `/files/ingress/${key}/delete-imported`,
			getPageForm: (key) => `/files/ingress/${key}/get-page-form`,
		};
	},
	search: {
		bar: "/search-bar",
		page: "/search-page",
	},
	linkPreview: "/preview",
	location: "/search-location",
	facet: (index) => {
		return `/search-index/${index}`;
	},
	html: (key, field) => {
		return {
			save: `/assets/${key}/form-html/${field}`,
			addImage: `/assets/${key}/document/image?field=${field}`,
			generateText: `/assets/${key}/document/generate?field=${field}`,
			getContent: `/assets/${key}/html/${field}`,
		};
	},
	renderer: {
		validateRow: (key, table_id) => `/forms/${key}/validate-row/${table_id}`,
		expandTableCell: (key, table_id) =>
			`/forms/${key}/expand-table-cell/${table_id}`,
		getSchema: (key) => `/forms/${key}/schema`,
	},
	manual: {
		section: (key) => {
			return `/manual/section/${key}`;
		},
	},
	collaboration: {
		start: `/collaboration/start`,
		stop: `/collaboration/stop`,
	},
	delete: (key) => `/delete/${key}`,
	toggleStar: (key) => {
		return `/toggle-star/${key}`;
	},
	activity: (key) => `/activity/${key}`,
	poll: "/poll",
	notifications: "/notifications",
	help: (key) => {
		return `/reference/section/${key}`;
	},
	createSchema: "/forms/create-schema",
	restrictions: (key) => `/forms/${key}/restrictions`,
	PagePermissions: (settings) => {
		return {
			viewAccess: `/pages/${settings.key}/view-access`,
			restrictAccess: `/pages/${settings.key}/restrictions`,
		};
	},
	UserSettings: (settings) => {
		return ENDPOINTS.PagePermissions(settings);
	},
	sync: "/sync",
};
