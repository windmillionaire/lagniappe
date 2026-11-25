// Generated from the registered Flask routes. Regenerate with venv/bin/python -m runner.browser_endpoints.
type KeyedSettings = { key: string };

export const ENDPOINTS = {
	CollaborativeDocument: ({ key }: KeyedSettings) => ({
		addImage: `/assets/${key}/document/image`,
		generateText: `/assets/${key}/document/generate`,
		getContent: `/assets/${key}/document/state`,
		history: `/assets/${key}/document/history`,
	}),
	Filters: ({ key }: KeyedSettings) => ({
		condition: `/filters/${key}/condition`,
		options: `/filters/${key}/options`,
		save: `/filters/${key}/save`,
		test: `/filters/${key}/test`,
		get: `/filters/${key}/get`,
	}),
	FileInfo: ({ key }: KeyedSettings) => ({
		html: `/files/${key}/html`,
	}),
	PagePhoto: ({ key }: KeyedSettings) => ({
		upload: `/assets/${key}/add-page-image`,
		generate: `/assets/${key}/generate-page-image`,
		remove: `/assets/${key}/remove-page-image`,
	}),
	SiteAiModels: () => ({
		setAiSettings: `/l/set-ai-settings`,
	}),
	SiteAdministrators: () => ({
		promote: `/l/site-administrators`,
		demote: (key: string) => `/l/site-administrators/${key}`,
	}),
	SiteDeployment: () => ({
		setDeploymentSettings: `/l/set-deployment-settings`,
	}),
	SiteImage: () => ({
		setSiteImage: `/l/set-site-image`,
	}),
	SiteMaintenance: () => ({
		siteConfiguration: `/l/site-configuration`,
		siteUpdate: `/l/site-update`,
		rebuildCache: `/l/rebuild-cache`,
	}),
	SiteSettings: () => ({
		siteSettings: `/l/site-settings`,
	}),
	HomeTaskList: () => ({
		completeTask: (key: string) => `/tasks/${key}/complete`,
		changeDueDate: (key: string) => `/tasks/${key}/change-due-date`,
	}),
	TaskForm: ({ key }: KeyedSettings) => ({
		latestHistorySubmission: `/tasks/${key}/history/latest-submission`,
	}),
	TaskUpload: (settings: KeyedSettings) => ({
		upload: `/tasks/${settings.key}/upload-file`,
		remove: (fileKey: string) => `/tasks/${settings.key}/files/${fileKey}`,
	}),
	ImportData: () => ({
		get: (key: string) => `/files/ingress?key=${key}`,
		setStage: (key: string) => `/files/ingress/${key}/stage`,
		update: (key: string) => `/files/ingress/${key}/update`,
		next: (key: string) => `/files/ingress/${key}/next`,
		import: (key: string) => `/files/ingress/${key}/import`,
		stop: (key: string) => `/files/ingress/${key}/stop`,
		deleteImported: (key: string) => `/files/ingress/${key}/delete-imported`,
		getPageForm: (key: string) => `/files/ingress/${key}/get-page-form`,
	}),
	search: {
		bar: `/l/search-bar`,
		page: `/l/search-page`,
	},
	linkPreview: `/l/preview`,
	markdown: `/l/markdown`,
	location: `/l/search-location`,
	facet: (index: string) => `/l/search-index/${index}`,
	html: (key: string, field: string) => ({
		save: `/assets/${key}/form-html/${field}`,
		addImage: `/assets/${key}/document/image?field=${field}`,
		generateText: `/assets/${key}/document/generate?field=${field}`,
		getContent: `/assets/${key}/html/${field}`,
	}),
	renderer: {
		validateRow: (key: string, table_id: string) => `/forms/${key}/validate-row/${table_id}`,
		expandTableCell: (key: string, table_id: string) => `/forms/${key}/expand-table-cell/${table_id}`,
		getSchema: (key: string) => `/forms/${key}/schema`,
	},
	manual: {
		section: (key: string) => `/manual/section/${key}`,
	},
	delete: (key: string) => `/l/delete/${key}`,
	toggleStar: (key: string) => `/l/toggle-star/${key}`,
	activity: (key: string) => `/l/activity/${key}`,
	poll: `/l/poll`,
	notifications: `/l/notifications`,
	messages: {
		conversations: `/l/messages/conversations`,
		history: (key: string) => `/l/messages/conversations/${key}`,
		send: `/l/messages`,
		read: (key: string) => `/l/messages/conversations/${key}/read`,
		remove: (key: string) => `/l/messages/${key}`,
		clearModal: (key: string) => `/l/messages/conversations/${key}/delete`,
	},
	help: (key: string) => `/reference/section/${key}`,
	createSchema: `/forms/create-schema`,
	restrictions: (key: string) => `/forms/${key}/restrictions`,
	sync: `/l/sync`,
};
