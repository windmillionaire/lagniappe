type KeyedSettings = { key: string };

export const ENDPOINTS = {
	CollaborativeDocument: (settings: KeyedSettings) => {
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
	Filters: (settings: KeyedSettings) => {
		return {
			condition: `/filters/${settings.key}/condition`,
			options: `/filters/${settings.key}/options`,
			save: `/filters/${settings.key}/save`,
			test: `/filters/${settings.key}/test`,
			get: `/filters/${settings.key}/get`,
		};
	},
	FileInfo: (settings: KeyedSettings) => {
		return {
			html: `/files/${settings.key}/html`,
		};
	},
	PagePhoto: (settings: KeyedSettings) => {
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
			demote: (key: string) => `/l/site-administrators/${key}`,
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
			completeTask: (key: string) => {
				return `/tasks/${key}/complete`;
			},
			changeDueDate: (key: string) => {
				return `/tasks/${key}/change-due-date`;
			},
		};
	},
	TaskForm: (settings: KeyedSettings) => {
		return {
			latestHistorySubmission: `/tasks/${settings.key}/history/latest-submission`,
		};
	},
	TaskUpload: (settings: KeyedSettings) => {
		return {
			upload: `/tasks/${settings.key}/upload-file`,
			remove: (fileKey: string) => `/tasks/${settings.key}/files/${fileKey}`,
		};
	},
	ImportData: () => {
		return {
			get: (key: string) => `/files/ingress?key=${key}`,
			setStage: (key: string) => `/files/ingress/${key}/stage`,
			update: (key: string) => `/files/ingress/${key}/update`,
			next: (key: string) => `/files/ingress/${key}/next`,
			import: (key: string) => `/files/ingress/${key}/import`,
			stop: (key: string) => `/files/ingress/${key}/stop`,
			deleteImported: (key: string) => `/files/ingress/${key}/delete-imported`,
			getPageForm: (key: string) => `/files/ingress/${key}/get-page-form`,
		};
	},
	search: {
		bar: "/l/search-bar",
		page: "/l/search-page",
	},
	linkPreview: "/l/preview",
	markdown: "/l/markdown",
	location: "/l/search-location",
	facet: (index: string) => {
		return `/l/search-index/${index}`;
	},
	html: (key: string, field: string) => {
		return {
			save: `/assets/${key}/form-html/${field}`,
			addImage: `/assets/${key}/document/image?field=${field}`,
			generateText: `/assets/${key}/document/generate?field=${field}`,
			getContent: `/assets/${key}/html/${field}`,
		};
	},
	renderer: {
		validateRow: (key: string, table_id: string) =>
			`/forms/${key}/validate-row/${table_id}`,
		expandTableCell: (key: string, table_id: string) =>
			`/forms/${key}/expand-table-cell/${table_id}`,
		getSchema: (key: string) => `/forms/${key}/schema`,
	},
	manual: {
		section: (key: string) => {
			return `/manual/section/${key}`;
		},
	},
	collaboration: {
		start: `/collaboration/start`,
		stop: `/collaboration/stop`,
	},
	delete: (key: string) => `/l/delete/${key}`,
	toggleStar: (key: string) => {
		return `/l/toggle-star/${key}`;
	},
	activity: (key: string) => `/l/activity/${key}`,
	poll: "/l/poll",
	notifications: "/l/notifications",
	messages: {
		conversations: "/l/messages/conversations",
		history: (key: string) => `/l/messages/conversations/${key}`,
		send: "/l/messages",
		read: (key: string) => `/l/messages/conversations/${key}/read`,
		remove: (key: string) => `/l/messages/${key}`,
		clearModal: (key: string) => `/l/messages/conversations/${key}/delete`,
	},
	help: (key: string) => {
		return `/reference/section/${key}`;
	},
	createSchema: "/forms/create-schema",
	restrictions: (key: string) => `/forms/${key}/restrictions`,
	sync: "/l/sync",
};
