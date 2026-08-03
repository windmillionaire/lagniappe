# This file is auto-generated. Do not edit manually.
STYLES = {
	"attributes": {
		"container": "flex flex-row items-center gap-2 flex-wrap",
		"button": "font-semibold pl-2 pr-3 py-2 flex items-center rounded-md gap-1 border text-base-dark bg-white border-base-light/50",
		"icon": "text-kind-default",
		"iconStack": "grid shrink-0",
		"form": "font-semibold pl-2 pr-3 py-2 flex items-center rounded-md gap-1 outline outline-form-light/70 bg-form-bg/70 text-form-default hover:bg-white hover:outline-form-default focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-form-default data-[selected=false]:opacity-50 data-[selected=true]:bg-white data-[selected=true]:outline-2 data-[selected=true]:outline-form-default"
	},
	"badge": {
		"builder": "ring-kind-light inline-flex items-center gap-1.5 rounded-md bg-white py-1 pr-2.5 pl-2 text-sm/6 font-medium whitespace-nowrap text-base-default ring ring-inset sm:text-xs/5",
		"default": "lp-badge ring-kind-light inline-flex min-w-0 max-w-full items-center gap-1 overflow-hidden rounded-md bg-white py-1 pl-2 pr-2.5 text-sm/6 font-medium whitespace-nowrap text-kind-default ring ring-inset",
		"icon": "icon-base text-kind-default"
	},
	"builder": {
		"view": "group/builder mx-auto flex max-w-7xl flex-row justify-center gap-8 px-4 pt-4 sm:px-0 sm:pt-6 lg:pt-8",
		"component": "text-md flex cursor-move flex-row items-center gap-3 rounded-md bg-form-bg px-3 py-1.5 font-semibold text-base-dark shadow-sm outline-2 outline-form-default hover:bg-form-light hover:outline-form-dark",
		"header": {
			"model": "h-8 flex flex-row justify-between items-center text-base-dark gap-4 mb-6 text-lg font-bold",
			"side": "h-8 flex flex-row justify-between items-center text-base-dark gap-4 mb-6 text-lg font-bold"
		},
		"panels": {
			"model": "group/model mb-4 flex min-h-75 flex-col gap-4 rounded-lg p-4 outline-2 outline-form-default outline-dashed",
			"default": "mb-4 flex flex-col gap-4 rounded-lg p-4 outline-2 outline-form-default",
			"preview": "outline-2 p-6 rounded-lg flex flex-col gap-6 w-full outline-form-default bg-form-bg"
		},
		"name": "border-b border-dashed focus:outline-none ml-2 w-auto max-w-xs bg-transparent border-base-medium focus:border-form-default",
		"switch": {
			"container": "relative inline-flex h-6 w-11 shrink-0 rounded-full border-2 border-form-light bg-form-bg transition-colors ease-in-out focus:outline-none hover:border-form-dark focus-visible:border-form-dark data-[active=true]:border-form-default data-[active=true]:bg-form-default",
			"toggle": "pointer-events-none h-5 w-5 transform rounded-full bg-white shadow-sm transition duration-200 ease-in-out grid place-items-center group-data-[active=true]/toggle:translate-x-5"
		},
		"model": "form-element rounded-md bg-base-bg p-2 text-sm data-[selected=true]:outline-2 data-[selected=true]:outline-kind-default",
		"generate": "flex grow flex-row items-center gap-3 rounded-md bg-kind-bg px-3 py-1.5 text-base font-semibold text-base-dark shadow-sm outline-2 outline-kind-default hover:bg-kind-light hover:outline-kind-dark",
		"sections": {
			"side": "basis-1/4 group-data-[expanded=true]/builder:hidden",
			"main": "basis-1/2 justify-self-center group-data-[expanded=true]/builder:basis-2/3"
		},
		"settings": {
			"item": "flex flex-row items-center justify-between group",
			"section": "flex flex-col gap-1 sm:text-sm p-2 rounded-md outline-2 bg-form-bg outline-form-default",
			"title": "sm:text-sm font-semibold flex justify-between items-center text-base-dark",
			"toggle": {
				"container": "grid place-items-center rounded-md hover:bg-white text-form-default transition-colors duration-100 hover:outline-kind-default focus:outline-none focus-visible:outline-kind-default focus-visible:bg-white hover:shadow-sm",
				"icon": "icon-xs text-kind-default"
			}
		}
	},
	"button": {
		"submit": "grid grow place-items-center rounded-md bg-kind-default px-3 py-1.5 text-base font-semibold text-white shadow-sm action-button",
		"explain": "inline-flex items-center gap-1 text-sm font-semibold justify-center",
		"close": "ml-2 text-center text-base rounded-md px-2.5 py-1 font-semibold shadow-sm focus-visible:outline-2 focus-visible:outline-offset-2 hover:outline-2 hover:outline-offset-2 text-white bg-delete-default hover:bg-delete-dark outline-delete-default hover:outline-delete-dark",
		"group": "flex flex-col sm:flex-row gap-3",
		"cancel": "ml-auto grid size-6 translate-x-1 place-items-center rounded-md text-delete-default hover:outline-2 hover:outline-delete-default focus-visible:outline-2 focus-visible:outline-delete-default hover:bg-delete-bg focus-visible:bg-delete-bg transition-colors duration-100"
	},
	"card": {
		"secondary": "group w-full border-base-light/50 bg-white sm:block sm:basis-1/3 sm:rounded-lg sm:border sm:shadow-sm shrink-0",
		"image": "group w-full sm:block sm:basis-1/3 sm:rounded-lg shrink-0",
		"primary": "max-w-100% w-full min-w-0 grow-0 border-base-light/50 bg-white sm:rounded-lg sm:border sm:shadow-sm"
	},
	"checkbox": {
		"container": "grid size-5 shrink-0 place-items-center",
		"default": "form-input [grid-area:1/1] size-5 appearance-none rounded-sm text-white",
		"icon": "checkbox-icon [grid-area:1/1] pointer-events-none text-white",
		"label": "flex flex-row items-start gap-2 font-semibold text-base-dark sm:text-sm py-1",
		"grid": "grid grid-cols-[repeat(auto-fit,minmax(100px,1fr))] lg:grid-cols-[repeat(auto-fit,minmax(140px,1fr))] gap-x-4 gap-y-2 sm:text-sm border-t border-base-medium pt-4"
	},
	"dropdown": {
		"menu": "absolute z-101 flex min-w-37.5 flex-col gap-1 rounded-md bg-white p-1 shadow-lg outline outline-base-light/50",
		"icon": "dropdown-option-icon",
		"option": {
			"action": "dropdown-option dropdown-option-action cursor-default",
			"flow": "dropdown-option dropdown-option-flow cursor-default",
			"multiple": "dropdown-option-multiple"
		},
		"panel": "p-1 scrollbar-thin scrollbar-thumb-base-light scrollbar-track-transparent absolute z-50 hidden max-h-96 min-w-64 overflow-y-auto rounded-md bg-white shadow-lg outline outline-base-light/50",
		"history": "text-left px-3 py-1.5 rounded-sm hover:bg-base-bg w-full",
		"search": {
			"result": "dropdown-option dropdown-option-flow cursor-default",
			"link": "dropdown-option dropdown-option-flow cursor-pointer",
			"more": "dropdown-option dropdown-option-flow font-semibold text-base-default italic"
		}
	},
	"editor": {
		"toolbar": {
			"container": {
				"page": "group/toolbar sticky top-16 z-40 border-b border-base-light/50 bg-base-bg p-4 sm:border-t sm:px-6",
				"project": "group/toolbar sticky top-16 z-40 border-b border-base-light/50 bg-base-bg p-4 sm:border-t sm:px-6",
				"form": "group/toolbar border-b border-base-light/50 bg-base-bg p-4 sm:p-6",
				"email": "group/toolbar border-b border-base-light/50 bg-base-bg p-2 sm:p-4",
				"default": "group/toolbar mt-4 border-base-light/50 bg-base-bg"
			},
			"divider": "mx-1 hidden h-6 w-px bg-base-light/50 md:block md:first:hidden md:last:hidden",
			"section": "flex flex-row items-center gap-2",
			"tool": "grid size-8 place-items-center rounded-md bg-white outline outline-base-light/50 shadow-sm",
			"menu": "flex min-h-8 w-fit flex-row items-center gap-1 rounded-md bg-white outline outline-base-light/50 px-2 py-1 text-center text-base font-semibold shadow-sm",
			"optionHeader": "text-lg font-bold pt-2 text-kind-default pb-1",
			"optionPanel": "outline rounded-md px-4 pb-4 flex flex-col bg-white outline-base-light mt-2",
			"tools": "flex flex-row flex-wrap items-center gap-2 sm:gap-3",
			"imageSettings": "group mt-4 hidden flex-row flex-wrap items-center gap-2 group-data-[open-form='setImage']/toolbar:flex",
			"iconContext": "editor-toolbar-icon-context",
			"portalIconContext": "editor-toolbar-portal-icon-context",
			"menuIcon": "editor-toolbar-menu-icon",
			"historyIcon": "editor-toolbar-history-icon",
			"caret": "editor-toolbar-caret opacity-50"
		},
		"container": "html-content min-h-50 px-4 pt-6 pb-4 focus:outline-none sm:px-6 sm:pt-8 sm:pb-6"
	},
	"entity": {
		"cards": "flex flex-row flex-wrap items-start sm:flex-nowrap sm:gap-4 lg:gap-8",
		"description": "rounded-md px-4 py-3 text-sm flex flex-row items-center w-full slide-right bg-kind-bg empty:hidden mt-4",
		"tabIcon": "relative inline-grid place-items-center text-kind-default hover:text-kind-dark tab-icon outline-none",
		"name": {
			"wrapper": "min-w-0",
			"parent": "whitespace-nowrap",
			"separator": "mx-1 text-base-medium",
			"anchor": "min-w-0"
		}
	},
	"filters": "flex flex-row gap-3",
	"form": {
		"default": "group/form flex mx-4 mb-4 flex-col gap-6 rounded-md bg-kind-bg p-4 sm:mx-2 sm:mb-2",
		"tools": "group/form flex flex-col gap-6",
		"login": "max-w-md mx-auto mt-8 p-6 rounded-lg border shadow-sm bg-white border-slate-300",
		"submit": {
			"group": "flex flex-col gap-2",
			"buttons": "flex flex-row justify-between gap-2"
		},
		"header": {
			"container": "flex flex-row items-center justify-between gap-6",
			"title": "text-lg font-semibold text-kind-default flex flex-row items-center gap-2",
			"controls": "flex flex-row items-center gap-1"
		},
		"icon": "text-kind-default hover:text-kind-dark focus-visible:text-kind-dark focus-visible:bg-kind-bg focus-visible:outline-none ml-1 inline-grid place-items-center rounded-full",
		"restriction": "flex flex-row items-center gap-2 px-3 py-2 justify-between border-t border-user-light",
		"table": {
			"body": "divide-y-kind-bg w-full border-t border-base-light",
			"container": "max-w-full flex flex-col gap-2 min-w-0",
			"table": "w-max min-w-full table-auto border-collapse bg-white sm:text-sm",
			"form": "table-container rounded-md p-4 flex flex-col gap-6 bg-base-bg",
			"cell": {
				"th": "w-72 min-w-48 max-w-88 p-3 text-left font-medium whitespace-nowrap",
				"default": "w-72 min-w-48 max-w-88 px-3 py-2 align-top text-left font-medium whitespace-normal [overflow-wrap:anywhere]",
				"compact": {
					"th": "w-28 min-w-24 max-w-32 p-3 text-left font-medium leading-snug whitespace-normal",
					"default": "w-28 min-w-24 max-w-32 px-3 py-2 align-top text-left font-medium whitespace-nowrap"
				},
				"title": "flex flex-row items-center gap-1"
			},
			"rowActions": "table-row-actions absolute top-0 right-0 z-20 m-0 flex h-8 w-max flex-row items-center rounded-bl-md border-b border-l border-kind-bg bg-base-bg px-1",
			"rowActionCell": "sticky right-0 z-20 w-px min-w-px max-w-px p-0 align-top overflow-visible",
			"rowActionHeader": "w-px min-w-px max-w-px p-0",
			"actionButton": "grid size-6 place-items-center rounded-sm text-kind-default outline-offset-0 transition-colors duration-100 hover:bg-white hover:text-kind-dark hover:outline hover:outline-kind-default focus-visible:bg-white focus-visible:text-kind-dark focus-visible:outline focus-visible:outline-kind-default disabled:pointer-events-none disabled:opacity-50"
		},
		"elementLabel": "flex flex-col gap-1 font-semibold sm:text-sm text-base-dark",
		"submission": {
			"default": "submission-outline flex min-h-10 w-fit flex-row items-center justify-center rounded-md bg-white/60 px-3 py-1.25 font-medium shadow-xs sm:text-sm",
			"grows": "submission-outline w-fit rounded-md bg-white/60 px-3 py-2.5 font-medium shadow-xs sm:text-sm"
		}
	},
	"home": {
		"card": {
			"item": "flex flex-row items-start justify-between gap-2 px-3 py-2 text-base font-semibold hover:bg-kind-bg group/item",
			"directory": "flex flex-row items-center gap-2 px-3 py-2 text-base font-semibold hover:bg-kind-bg group/item",
			"list": "bg-white rounded-md outline-2 outline-kind-default",
			"actions": "flex flex-row items-center gap-1"
		},
		"column": "flex flex-col gap-4 sm:gap-6 lg:gap-8",
		"count": "font-bold ml-auto text-kind-default",
		"loading": "ml-auto hidden items-center justify-center text-kind-default group-data-[loading=true]/list-toggle:flex",
		"create": "grid w-fit place-items-center flex-row items-center gap-2 rounded-md bg-white hover:bg-kind-bg px-3 py-1.5 font-semibold text-base-dark shadow-sm outline focus-visible:outline-kind-default hover:outline-kind-default outline-base-light/50 hover:outline-2 focus-visible:outline-2",
		"component": "flex flex-col gap-4 group",
		"form": "group/form flex flex-col gap-6 rounded-md bg-kind-bg p-4 outline-2 outline-kind-default",
		"generate": "home-generate-button flex w-full min-w-0 flex-row items-center justify-center gap-2 rounded-md bg-white p-2 px-3 font-semibold text-kind-default shadow-sm sm:grow data-[active=true]:bg-kind-light data-[active=true]:text-kind-dark",
		"ingress": {
			"details": "flex flex-col gap-1 text-sm px-3 pb-2",
			"item": "group/item",
			"list": "divide-y rounded-md bg-white outline-2 outline-base-light/50 divide-base-light/50 text-base-dark"
		},
		"pagination": {
			"container": "flex flex-row items-center",
			"button": "grow py-2 text-center hover:bg-kind-bg text-kind-default hover:text-kind-dark"
		},
		"section": "border border-base-light/50 shadow-sm flex flex-col gap-4 p-4 bg-base-bg rounded-md",
		"toggle": "flex w-full flex-row items-center gap-2 rounded-md bg-white hover:bg-kind-bg px-2.5 py-1.5 font-semibold text-base-dark shadow-sm outline focus-visible:outline-kind-default hover:outline-kind-default outline-base-light/50 hover:outline-2 focus-visible:outline-2",
		"toggleLabel": "flow-root min-w-0 flex-1 text-left",
		"listToggle": "flex w-full flex-row items-center gap-2 rounded-md bg-white hover:bg-kind-bg px-2.5 py-1.5 font-semibold text-base-dark shadow-sm outline focus-visible:outline-kind-default hover:outline-kind-default outline-base-light/50 hover:outline-2 focus-visible:outline-2 group/list-toggle",
		"view": "grid grid-cols-1 md:grid-cols-2 gap-4 sm:gap-6 lg:gap-8 w-full p-4 sm:pb-0 sm:pt-6 lg:pt-8 sm:px-6 lg:px-8 mx-auto max-w-7xl"
	},
	"note": {
		"section": "mt-4 flex flex-col gap-4",
		"form": {
			"home": "group/form flex flex-col gap-5 rounded-md bg-note-bg p-4 outline-2 outline-note-default shadow-sm",
			"page": "group/form flex w-full flex-col gap-5 rounded-md bg-note-bg p-4 outline-2 outline-note-default shadow-sm sm:p-5"
		},
		"textarea": {
			"home": "min-h-24 resize-y bg-white/80",
			"page": "min-h-36 resize-y bg-white/80"
		},
		"list": {
			"home": "flex flex-col gap-3",
			"page": "flex flex-col gap-3 data-[visible=false]:hidden"
		},
		"item": {
			"home": "group/note flex items-start justify-between gap-3 rounded-sm border border-note-light bg-note-bg px-3 py-3 text-base-dark shadow-sm",
			"page": "group/note flex w-full items-start justify-between gap-4 rounded-sm border border-note-light bg-note-bg p-4 text-base-dark shadow-sm sm:p-5"
		},
		"content": "flex min-w-0 flex-1 flex-col gap-3",
		"body": "whitespace-pre-wrap break-words text-sm font-medium leading-relaxed text-base-dark",
		"photo": {
			"home": "max-h-48 w-auto max-w-full rounded-md object-contain",
			"page": "max-h-96 w-auto max-w-full rounded-md object-contain"
		},
		"meta": "flex flex-wrap items-center gap-x-3 gap-y-1 text-xs font-normal text-base-medium",
		"discard": "grid size-7 shrink-0 place-items-center rounded-md text-base-medium hover:bg-white hover:text-delete-default focus-visible:outline-2 focus-visible:outline-delete-default"
	},
	"icon": {
		"default": "text-kind-default"
	},
	"iconLabel": {
		"wrapper": "flow-root min-w-0 text-left",
		"icon": "float-left mr-2"
	},
	"index": {
		"mobile": {
			"controls": "rounded-md bg-kind-bg p-4 text-base flex flex-col gap-2 font-semibold mt-4",
			"row": "flex flex-row items-center justify-between gap-4 group/form"
		},
		"tools": {
			"container": "mx-auto w-full flex flex-row gap-4",
			"main": "flex-1 rounded-md bg-kind-bg p-4",
			"navigation": "shrink-0 flex-col gap-2 rounded-md bg-kind-bg p-2 sm:flex sm:min-w-64 sm:p-4",
			"toggle": "w-full flex flex-row items-center justify-end gap-2 rounded-md bg-kind-bg px-2 py-1.5 font-semibold text-kind-default text-right focus:outline-kind-default hover:outline-kind-default hover:outline-2 focus:outline-2 data-[selected=true]:bg-kind-light data-[selected=true]:text-kind-dark",
			"dropdown": {
				"toggle": "rounded-md px-2 py-1.5 font-semibold text-kind-default hover:bg-kind-light hover:text-kind-dark text-right",
				"panel": "outline-kind-light absolute z-101 flex min-w-37.5 flex-col gap-1 rounded-md outline-2 bg-kind-bg p-1 shadow-lg"
			},
			"selector": {
				"container": "flex flex-row flex-wrap items-center gap-4",
				"show": "flex flex-row items-center gap-1 rounded-md bg-white px-3 py-2 font-semibold text-kind-default hover:bg-kind-light hover:text-kind-dark loader"
			}
		}
	},
	"input": "h-10 form-input w-full rounded-md px-3 py-1.25 text-base sm:text-sm font-normal",
	"label": {
		"default": "sm:text-sm font-semibold text-base-dark",
		"column": "flex flex-col gap-1 sm:text-sm font-semibold text-base-dark",
		"row": "flex flex-row items-center gap-1 sm:text-sm font-semibold text-base-dark",
		"sectionHeading": "sm:text-sm font-semibold text-base-dark mb-1"
	},
	"layout": {
		"contentView": "mx-auto max-w-7xl px-4 sm:px-0",
		"view": {
			"header": "pt-4 lg:pt-6 bg-white sm:border-none px-4 sm:px-0",
			"title": "grid grid-cols-[minmax(0,1fr)_auto] items-start gap-4 font-semibold text-xl"
		},
		"body": "h-full bg-white font-sans",
		"main": "min-h-full pt-16 pb-16 text-slate-900 px-0 sm:px-6 lg:px-8 max-w-7xl mx-auto",
		"nav": {
			"mobile": "group/nav flex flex-row items-center justify-between gap-4 border-y border-base-light/50 bg-base-bg pr-4 py-1 text-lg",
			"flipper": "inline-grid place-items-center focus:outline-none text-kind-default sm:hidden text-lg",
			"group": "flex flex-row items-center",
			"header": "gap-2 flex w-full flex-row items-center justify-between",
			"title": "gap-2 flex w-full flex-row items-center justify-between pl-4 py-3 sm:px-6 sm:py-5 text-lg font-semibold",
			"toggles": "flex flex-row items-center gap-3 pl-2 slide-left",
			"adminToggles": "flex flex-row items-center gap-3 pl-2 slide-left",
			"card": "flex flex-row items-center"
		}
	},
	"link": {
		"default": "focus-visible:outline-none focus-visible:underline link-default",
		"emphasized": "focus-visible:outline-none focus-visible:underline link-default font-semibold",
		"title": "font-semibold focus-visible:outline-none focus-visible:underline link-title",
		"alternate": "text-sm"
	},
	"list": {
		"container": "-mt-px divide-y divide-base-light/50 border-t border-base-light/50",
		"itemHeader": "flex flex-row items-center justify-between gap-2 p-4 text-base font-medium sm:px-6",
		"links": {
			"container": "grid w-full grid-cols-1 grid-rows-2 border-t border-base-light/50 sm:grid-cols-2 sm:grid-rows-1 sm:divide-x sm:divide-base-light/50",
			"item": "group/item flex flex-row items-center justify-between gap-2 px-4 py-2 text-sm font-semibold hover:bg-kind-bg sm:px-6 sm:py-3"
		}
	},
	"siteSettings": {
		"migration": {
			"releaseSummary": "cursor-pointer font-semibold",
			"migrationList": "mt-1 space-y-2 pl-3",
			"completion": "text-xs text-base-medium",
			"attemptList": "mt-1 space-y-1 text-xs text-base-medium"
		}
	},
	"loading": {
		"wrapper": "mt-4 space-y-3",
		"pulse": "h-4 bg-base-light rounded-full animate-pulse"
	},
	"login": {
		"message": "text-center mb-4 text-base-dark",
		"error": "border px-4 py-3 rounded-md mb-4 hidden bg-delete-bg border-delete-default text-delete-default",
		"success": "border px-4 py-3 rounded-md mb-4 hidden bg-saved-bg border-saved-default text-saved-default"
	},
	"manual": {
		"button": "flex grow flex-row items-center justify-center gap-2 rounded-md bg-kind-default px-3 py-1.5 text-base font-semibold text-white shadow-sm",
		"codeShell": "bg-base-dark rounded-lg my-2 w-full min-w-0 max-w-full overflow-hidden",
		"codeToolbar": "flex justify-end px-2 pt-2",
		"copyButton": "rounded-md border border-base-light/50 px-2 py-1 text-xs font-semibold text-white hover:bg-base-medium focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-white",
		"code": "text-project-light px-4 pb-4 pt-2 font-mono text-sm block w-full min-w-0 max-w-full overflow-x-auto whitespace-pre",
		"content": "sm:rounded-lg sm:shadow-sm w-full sm:border bg-white sm:border-base-light/50 sm:p-6",
		"heading": "flex items-center gap-3 text-2xl font-semibold text-base-dark mb-4",
		"conceptTitle": "flex items-center gap-2.5 text-lg font-semibold mb-2",
		"navButton": "flex items-center gap-3 rounded-md px-3 py-1.5 font-semibold shadow-sm outline w-full focus-visible:outline-2 hover:outline-2 bg-white hover:bg-page-bg outline-base-light text-base-dark focus-visible:outline-page-default hover:outline-page-default"
	},
	"message": "w-full sm:text-sm italic rounded-md px-3 py-2 outline-kind-default bg-kind-bg",
	"modal": {
		"wrapper": "fixed inset-0 bg-slate-900/50 backdrop-blur-sm flex items-center justify-center z-50 transition-opacity duration-100",
		"content": "bg-white rounded-lg shadow-xl max-w-4xl mx-4 max-h-[90vh] overflow-y-auto relative",
		"header": "sticky top-0 bg-white border-b px-6 py-4 flex justify-between items-center",
		"actions": "flex flex-row gap-3"
	},
	"nav": {
		"button": "action-icon-button transition-colors duration-100",
		"mobileButton": "action-icon-button transition-colors duration-100 mobile",
		"desktopButton": "action-icon-button transition-colors duration-100 desktop",
		"bar": {
			"wrapper": "fixed top-0 z-50 w-full bg-page-default",
			"contents": "mx-auto px-4 sm:px-6 lg:px-8 flex h-16 items-center justify-between w-full"
		},
		"link": "shrink-0 focus-visible:outline-2 hover:outline-2 focus-visible:outline-offset-2 hover:outline-offset-2 rounded-full focus-visible:outline-white hover:outline-white",
		"user": "size-8 flex rounded-full items-center justify-center",
		"search": {
			"icon": "nav-search-icon pointer-events-none text-slate-400 absolute left-1.5 mr-1 z-10",
			"input": "sm:text-sm rounded-md pl-8 pr-2 h-8 w-48 sm:w-64 bg-white text-slate-900 placeholder:text-slate-400 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-white"
		}
	},
	"radio": {
		"default": "form-input order-first size-4 shrink-0 appearance-none rounded-full",
		"fieldset": {
			"grid": "grid grid-cols-[repeat(auto-fit,minmax(80px,1fr))] gap-x-4 gap-y-2 sm:text-sm",
			"row": "flex flex-row items-center gap-4 sm:text-sm font-semibold",
			"column": "flex flex-col gap-1 sm:text-sm font-semibold"
		},
		"label": "flex items-center gap-2 font-semibold sm:text-sm text-base-dark"
	},
	"section": "outline outline-base-light rounded-md px-4 pb-4 bg-white w-full",
	"select": {
		"container": "flex flex-col",
		"wrapper": "grid grid-cols-1 h-10",
		"default": "form-input col-start-1 row-start-1 h-10 w-full appearance-none rounded-md py-1.25 pr-8 pl-3 sm:text-sm placeholder:text-base-medium",
		"icon": "select-icon pointer-events-none col-start-1 row-start-1 mr-2.5 self-center justify-self-end z-25 text-base-medium",
		"button": "select-button flex min-h-10 w-full flex-row items-center rounded-md bg-white p-2 px-3 font-semibold sm:grow focus-visible:outline-kind-default hover:outline-kind-default hover:outline-2 focus-visible:outline-2 disabled:pointer-events-none disabled:hover:outline-0 disabled:focus-visible:outline-0"
	},
	"signature": {
		"pad": "relative rounded-md w-full h-40 bg-white outline-base-light outline",
		"reset": "absolute top-2 left-2 px-2 py-1 text-base sm:text-sm border rounded shadow-sm text-base-dark border-base-light hover:bg-delete-default hover:text-white"
	},
	"table": {
		"default": "w-full table-auto border-collapse divide-y sm:text-sm mt-4",
		"embedded": "w-full table-auto border-collapse divide-y sm:text-sm min-w-max bg-white",
		"body": "sm:divide-y w-full sm:divide-base-light/50",
		"thead": {
			"default": "sticky top-16 z-40 bg-white",
			"embedded": "bg-white",
			"th": "group/header max-w-48 gap-2 truncate py-2.5 pr-3 text-left font-medium data-[active=false]:border-b-2",
			"actionCell": "sticky right-0 z-20 w-px min-w-px max-w-px p-0 align-top overflow-visible",
			"actions": "absolute top-1/2 right-0 z-20 m-0 grid -translate-y-1/2 place-items-center",
			"actionButton": "grid size-7 place-items-center rounded-md bg-white text-kind-default outline-offset-0 transition-colors duration-100 hover:text-kind-dark hover:outline-2 hover:outline-kind-default focus-visible:text-kind-dark focus-visible:outline-2 focus-visible:outline-kind-default",
			"actionIcon": "embedded-table-action-icon"
		},
		"cell": {
			"default": "max-w-48 py-3.5 pr-3 text-left font-medium",
			"action": "w-px py-2.5 text-right text-lg font-medium whitespace-nowrap",
			"compact": {
				"th": "group/header w-28 min-w-24 max-w-32 py-2.5 pr-3 text-left font-medium leading-snug whitespace-normal data-[active=false]:border-b-2",
				"default": "w-28 min-w-24 max-w-32 py-3.5 pr-3 text-left font-medium whitespace-nowrap"
			}
		},
		"filters": {
			"title": "font-semibold align-middle",
			"icon": {
				"container": "ml-1.5 inline-grid align-middle text-slate-400",
				"active": "[grid-area:1/1] group-data-[sorting=true]/header:invisible hover:text-kind-default",
				"inactive": "[grid-area:1/1] invisible text-kind-default group-data-[sorting=true]/header:visible hover:text-delete-default"
			}
		}
	},
	"task": {
		"actionIconContext": "task-action-icon-context",
		"buttons": "flex flex-col gap-3",
		"title": "min-w-0 flex-1 leading-relaxed",
		"complete": "order-first mt-0.5 grid size-5 shrink-0 place-items-center self-start",
		"home": {
			"complete": "float-left mt-0.5 mr-2 grid size-5 place-items-center",
			"group": "text-sm font-semibold italic px-3 py-2 due-date",
			"skipped": "text-sm italic text-delete-default",
			"item": "flex flex-col my-2 pt-1",
			"header": "flex flex-col px-3 text-sm font-semibold",
			"details": "grid grid-cols-[minmax(0,1fr)_auto] items-start w-full",
			"title": "min-w-0 font-semibold text-base leading-relaxed",
			"snooze": "home-task-snooze grid size-8 place-items-center rounded-sm text-xl text-kind-default",
			"notification": "text-sm italic border rounded-md w-fit px-3 py-2 mx-3 mt-3 empty:hidden text-delete-default border-delete-default"
		}
	},
	"textarea": "form-input block w-full rounded-md px-3 py-2 text-base font-normal placeholder:text-base-medium sm:text-sm",
	"toggle": {
		"container": "group/toggle action-icon-button transition-colors duration-100 group-data-[visible=true]/form:shadow-sm group-data-[visible=true]/form:bg-white hover:bg-white shrink-0",
		"plain": "group/toggle action-icon-button transition-colors duration-100 hover:bg-white",
		"icon": {
			"documentSettings": "page-document-settings-icon",
			"taskControl": "task-control-icon",
			"active": "invisible group-data-[active=false]/toggle:group-hover/toggle:visible group-data-[active=true]/toggle:group-[:not(:hover)]/toggle:visible",
			"inactive": "invisible group-data-[active=true]/toggle:group-hover/toggle:visible group-data-[active=false]/toggle:group-[:not(:hover)]/toggle:visible",
			"enabled": "text-kind-default invisible group-data-[active=true]/toggle:visible",
			"disabled": "text-kind-default invisible group-data-[active=false]/toggle:visible"
		}
	},
	"upload": {
		"options": "outline rounded-md px-4 pb-4 flex flex-col gap-4 bg-white outline-base-light",
		"processing": "pt-4 border-t flex flex-col gap-2 bg-white",
		"context": "pt-4 border-t flex flex-col gap-2 outline-base-light bg-white",
		"contextRow": "flex flex-col sm:flex-row gap-3",
		"header": "text-lg font-bold pt-2 pb-1 text-kind-default",
		"dropzone": "relative flex h-24 w-full flex-col content-center justify-center rounded-md border-2 border-dashed border-base-light bg-white p-3 text-center text-sm text-base-medium italic",
		"image": {
			"container": "relative aspect-square rounded-lg p-4 outline-2 outline-base-light outline-dashed",
			"text": "absolute top-0 right-0 w-full h-full flex flex-col items-center justify-center",
			"icon": "text-4xl mb-4 text-kind-default text-center"
		}
	}
}
