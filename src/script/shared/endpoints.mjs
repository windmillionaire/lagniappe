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
	SiteAiModels: () => {
		return {
			setAiSettings: "/l/set-ai-settings",
		};
	},
	SiteAdministrators: () => {
		return {
			promote: "/l/site-administrators",
			demote: (key) => `/l/site-administrators/${key}`,
		};
	},
	SiteDeployment: () => {
		return {
			setDeploymentSettings: "/l/set-deployment-settings",
		};
	},
	SiteImage: () => {
		return {
			setSiteImage: "/l/set-site-image",
		};
	},
	SiteMaintenance: () => {
		return {
			siteConfiguration: "/l/site-configuration",
			siteUpdate: "/l/site-update",
			rebuildCache: "/l/rebuild-cache",
		};
	},
	SiteSettings: () => {
		return {
			siteSettings: "/l/site-settings",
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
		bar: "/l/search-bar",
		page: "/l/search-page",
	},
	linkPreview: "/l/preview",
	markdown: "/l/markdown",
	location: "/l/search-location",
	facet: (index) => {
		return `/l/search-index/${index}`;
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
	delete: (key) => `/l/delete/${key}`,
	toggleStar: (key) => {
		return `/l/toggle-star/${key}`;
	},
	activity: (key) => `/l/activity/${key}`,
	poll: "/l/poll",
	notifications: "/l/notifications",
	messages: {
		conversations: "/l/messages/conversations",
		history: (key) => `/l/messages/conversations/${key}`,
		send: "/l/messages",
		read: (key) => `/l/messages/conversations/${key}/read`,
		remove: (key) => `/l/messages/${key}`,
		clearModal: (key) => `/l/messages/conversations/${key}/delete`,
	},
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
	sync: "/l/sync",
};
