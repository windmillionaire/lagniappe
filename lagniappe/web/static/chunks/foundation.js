/*! Third-party licenses: /third-party-licenses.txt */
import { h as handleUpstreamResponse } from './upstreamUnavailable.js?v=bf7d4d98';
import { c as connectivity } from './connectivity.js?v=bf7d4d98';

const getErrorDetails = (error) => error && (typeof error === "object" || typeof error === "function") ? error : void 0;
const getElementContext = (element) => {
  const context = {};
  if (!(element instanceof Element)) return context;
  context.element = {
    tagName: element.tagName?.toLowerCase(),
    id: element.id || void 0,
    className: element.className || void 0,
    dataset: { ...element.dataset }
  };
  const widget = element.closest("[data-widget]");
  if (widget && widget !== element) {
    context.widget = widget.dataset;
  }
  const component = element.closest("[lp-component]");
  if (component && component !== element) {
    context.component = component.dataset;
  }
  const view = element.closest("[lp-view]");
  if (view && view !== element) {
    context.view = view.dataset;
  }
  context.page = {
    pathname: window.location.pathname
  };
  return context;
};
const sanitizedObjectContext = (value) => Object.fromEntries(
  Object.entries(value).filter(([, child]) => {
    return child !== void 0 && typeof child !== "function" && typeof child !== "symbol";
  })
);
const normalizeContextValue = (value) => {
  if (value === void 0 || typeof value === "function" || typeof value === "symbol") {
    return null;
  }
  if (Array.isArray(value)) return { values: value };
  if (value && typeof value === "object") return sanitizedObjectContext(value);
  return { value };
};
const normalizeContext = (context) => {
  if (!(context instanceof Object)) return {};
  return Object.fromEntries(
    Object.entries(context).flatMap(([key, value]) => {
      const normalized = normalizeContextValue(value);
      return normalized && Object.keys(normalized).length ? [[key, normalized]] : [];
    })
  );
};
const getErrorText = (error) => {
  if (!error) return "";
  if (typeof error === "string") return error;
  const details = getErrorDetails(error);
  return `${details?.name || ""} ${details?.message || ""} ${String(error)}`.trim();
};
const isSkippedViewTransitionError = (error) => {
  if (!error) return false;
  if (error instanceof DOMException && /transition/i.test(error.message)) {
    return true;
  }
  const text = getErrorText(error);
  if (!text) return false;
  return /transition was (skipped|aborted)/i.test(text) || getErrorDetails(error)?.name === "InvalidStateError" && /transition/i.test(text);
};
const isTransientNetworkError = (error) => {
  if (!error) return false;
  if (getErrorDetails(error)?.name === "AbortError") return true;
  if (error instanceof TypeError) {
    const msg = error.message || "";
    return msg === "Failed to fetch" || msg === "Load failed" || /NetworkError when attempting to fetch resource/i.test(msg);
  }
  return false;
};
const captureError = (error, element, context) => {
  if (isSkippedViewTransitionError(error)) {
    return;
  }
  const normalized = normalizeContext({
    ...getElementContext(element || getErrorDetails(error)?.target),
    ...context || {}
  });
  if (typeof window !== "undefined" && window.Sentry) {
    const captureContext = Object.keys(normalized).length > 0 ? { contexts: normalized } : void 0;
    if (error instanceof Error) {
      window.Sentry.captureException(error, captureContext);
    } else {
      window.Sentry.captureMessage(String(error), {
        level: "error",
        ...captureContext
      });
    }
  }
  const hasContext = Object.keys(normalized).length > 0;
  console.error("[ERROR]", error);
  if (hasContext) console.error("Context:", normalized);
};
const captureNetworkError = (error, url, options = {}) => {
  if (!options.forceReport && isTransientNetworkError(error)) {
    return;
  }
  const context = {
    network: {
      url,
      method: options.method || "GET",
      timestamp: (/* @__PURE__ */ new Date()).toISOString(),
      online: navigator.onLine
    }
  };
  captureError(error, null, context);
};

var errors = /*#__PURE__*/Object.freeze({
	__proto__: null,
	captureError: captureError,
	captureNetworkError: captureNetworkError,
	isSkippedViewTransitionError: isSkippedViewTransitionError,
	isTransientNetworkError: isTransientNetworkError
});

const NOTIFICATION_STATE_HEADER = "X-Lagniappe-Notification-State";
let invalidStateReported = false;
const renderNotificationBadge = (count) => {
  const normalized = Number.isInteger(Number(count)) ? Number(count) : 0;
  const button = document.querySelector(
    "[data-role='notifications']"
  );
  const countElement = document.querySelector(
    "[data-role='notification-count']"
  );
  if (countElement) countElement.textContent = String(normalized);
  if (!button) return normalized;
  button.dataset.visible = "true";
  button.setAttribute("aria-hidden", "false");
  button.setAttribute("aria-busy", "false");
  button.setAttribute("aria-label", `Notifications: ${normalized}`);
  button.tabIndex = 0;
  return normalized;
};
const _normalized = (raw) => {
  if (typeof raw === "string") {
    try {
      raw = JSON.parse(raw);
    } catch {
      return null;
    }
  }
  if (!raw || typeof raw !== "object" || !("generation" in raw) || !("revision" in raw) || !("count" in raw))
    return null;
  if (raw.generation === null && raw.revision === null && raw.count === null) {
    return { generation: null, revision: null, count: null, miss: true };
  }
  if (typeof raw.generation !== "string" || !raw.generation || typeof raw.revision !== "number" || !Number.isInteger(raw.revision) || raw.revision < 0 || typeof raw.count !== "number" || !Number.isInteger(raw.count) || raw.count < 0) {
    return null;
  }
  return {
    generation: raw.generation,
    revision: raw.revision,
    count: raw.count,
    miss: false
  };
};
const applyNotificationState = (raw) => {
  const state = _normalized(raw);
  if (!state) {
    if (raw !== null && raw !== void 0 && !invalidStateReported) {
      invalidStateReported = true;
      captureError(
        new TypeError("Invalid notification state response."),
        null,
        {
          context: "notification-state-contract"
        }
      );
    }
    return null;
  }
  window.__NOTIFICATION_STATE__ = state;
  if (!state.miss) {
    renderNotificationBadge(state.count);
  }
  window.dispatchEvent(
    new CustomEvent("notification-state", { detail: { ...state } })
  );
  return state;
};
const applyNotificationStateHeader = (headers) => {
  const raw = headers?.get?.(NOTIFICATION_STATE_HEADER);
  return raw ? applyNotificationState(raw) : null;
};

const hasThen = (result) => Boolean(result?.then);
const runWithoutTransition = async (callback, label = "unlabeled") => {
  try {
    const result = callback();
    if (hasThen(result)) {
      captureError(
        new TypeError(
          `View transition commit "${label}" returned a promise. Prepare asynchronous work before committing DOM changes.`
        )
      );
      await result;
    }
    return true;
  } catch (error) {
    captureError(error);
    return false;
  }
};
let transitionQueue = Promise.resolve();
let transitionDepth = 0;
let pendingTransitionBatch = null;
const reportSlowCommit = (label, started) => {
  if (typeof performance === "undefined" || !performance.now) return;
  return;
};
const runCommit = (callback, label) => {
  const started = typeof performance !== "undefined" && performance.now ? performance.now() : null;
  try {
    const result = callback();
    if (!hasThen(result)) {
      if (started !== null) reportSlowCommit(label, started);
      return true;
    }
    captureError(
      new TypeError(
        `View transition commit "${label}" returned a promise. Prepare asynchronous work before committing DOM changes.`
      )
    );
    return Promise.resolve(result).then(() => true).catch((error) => {
      captureError(error);
      return false;
    }).finally(() => {
      if (started !== null) reportSlowCommit(label, started);
    });
  } catch (error) {
    captureError(error);
    return false;
  }
};
const runTransitionBatch = (entries) => {
  const results = new Array(entries.length).fill(false);
  const pending = [];
  transitionDepth += 1;
  entries.forEach(({ callback, label }, index) => {
    const result = runCommit(callback, label);
    if (typeof result !== "boolean") {
      pending.push(
        result.then((successful) => {
          results[index] = successful;
        })
      );
    } else {
      results[index] = result;
    }
  });
  if (!pending.length) {
    transitionDepth -= 1;
    return { results, pending: null };
  }
  return {
    results,
    pending: Promise.all(pending).finally(() => {
      transitionDepth -= 1;
    })
  };
};
const executeTransition = async (entries) => {
  const updateState = {
    started: false,
    batch: null
  };
  const update = () => {
    updateState.started = true;
    updateState.batch = runTransitionBatch(entries);
    return updateState.batch.pending || void 0;
  };
  let transition = null;
  if (document.startViewTransition) {
    try {
      transition = document.startViewTransition(update);
    } catch (error) {
      if (!isSkippedViewTransitionError(error)) captureError(error);
    }
  }
  if (!transition) {
    if (!updateState.started) update();
    if (updateState.batch?.pending) await updateState.batch.pending;
    entries.forEach((entry, index) => {
      entry.resolve(updateState.batch?.results[index] ?? false);
    });
    return;
  }
  const observeTransitionError = (error) => {
    if (!isSkippedViewTransitionError(error)) captureError(error);
  };
  void transition.ready?.catch(observeTransitionError);
  const updateDone = transition.updateCallbackDone || transition.finished;
  if (transition.finished !== updateDone) {
    void transition.finished?.catch(observeTransitionError);
  }
  try {
    await updateDone;
  } catch (error) {
    observeTransitionError(error);
  }
  entries.forEach((entry, index) => {
    entry.resolve(updateState.batch?.results[index] ?? false);
  });
};
const withTransition = (callback, { label = "unlabeled" } = {}) => {
  if (transitionDepth > 0) {
    return runWithoutTransition(callback, label);
  }
  return new Promise((resolve) => {
    if (!pendingTransitionBatch) {
      const entries = [];
      pendingTransitionBatch = entries;
      queueMicrotask(() => {
        pendingTransitionBatch = null;
        transitionQueue = transitionQueue.then(() => executeTransition(entries)).catch((error) => {
          captureError(error);
          entries.forEach((entry) => {
            entry.resolve(false);
          });
        });
      });
    }
    pendingTransitionBatch.push({ callback, label, resolve });
  });
};

const generateElementId = (type) => {
  return `${type}-${crypto.randomUUID().split("-")[0]}`;
};
const briefMessageTimers = /* @__PURE__ */ new WeakMap();
const showBriefly = (element, content, duration = 1500) => {
  clearTimeout(briefMessageTimers.get(element));
  void withTransition(
    () => {
      element.replaceChildren(content);
      element.dataset.visible = "true";
    },
    { label: "brief-message-show" }
  );
  const timer = setTimeout(() => {
    briefMessageTimers.delete(element);
    void withTransition(
      () => {
        element.dataset.visible = "false";
        element.replaceChildren();
      },
      { label: "brief-message-hide" }
    );
  }, duration);
  briefMessageTimers.set(element, timer);
};
const debounce = (func, wait) => {
  let timeout;
  const debounced = function(...args) {
    clearTimeout(timeout);
    timeout = setTimeout(() => {
      timeout = void 0;
      func.apply(this, args);
    }, wait);
  };
  debounced.cancel = () => {
    clearTimeout(timeout);
    timeout = void 0;
  };
  return debounced;
};
function waitForAttribute(element, attributeName, timeout = 1e4) {
  if (element.hasAttribute(attributeName)) {
    return Promise.resolve(element.getAttribute(attributeName));
  }
  return new Promise((resolve, reject) => {
    let observer = null;
    let timeoutId;
    const cleanup = () => {
      observer?.disconnect();
      clearTimeout(timeoutId);
    };
    timeoutId = setTimeout(() => {
      cleanup();
      reject(new Error(`Timeout waiting for attribute '${attributeName}'`));
    }, timeout);
    observer = new MutationObserver(() => {
      if (element.hasAttribute(attributeName)) {
        cleanup();
        resolve(element.getAttribute(attributeName));
      }
    });
    observer.observe(element, {
      attributes: true,
      attributeFilter: [attributeName]
    });
  });
}
function _sortObject(obj) {
  if (Array.isArray(obj)) {
    return obj.map((value) => _sortObject(value));
  }
  if (obj === null || typeof obj !== "object") {
    return obj;
  }
  const record = obj;
  return Object.keys(record).sort().reduce((result, key) => {
    result[key] = _sortObject(record[key]);
    return result;
  }, {});
}
const areEqual = (a, b) => {
  return JSON.stringify(_sortObject(a)) === JSON.stringify(_sortObject(b));
};
const base64ToUint8Array = (base64) => {
  const bin = atob(base64);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  return bytes;
};
const uint8ArrayToBase64 = (bytes) => {
  let bin = "";
  for (let i = 0; i < bytes.byteLength; i++)
    bin += String.fromCharCode(bytes[i]);
  return btoa(bin);
};

const ENDPOINTS = {
  CollaborativeDocument: (settings) => {
    return {
      sendUpdates: `/assets/${settings.key}/document/update`,
      saveDocument: `/assets/${settings.key}/document/save`,
      addImage: `/assets/${settings.key}/document/image`,
      generateText: `/assets/${settings.key}/document/generate`,
      removeUser: `/assets/${settings.key}/document/remove-user`,
      getContent: `/assets/${settings.key}/document/state`,
      history: `/assets/${settings.key}/document/history`
    };
  },
  Filters: (settings) => {
    return {
      condition: `/filters/${settings.key}/condition`,
      options: `/filters/${settings.key}/options`,
      save: `/filters/${settings.key}/save`,
      test: `/filters/${settings.key}/test`,
      get: `/filters/${settings.key}/get`
    };
  },
  FileInfo: (settings) => {
    return {
      html: `/files/${settings.key}/html`
    };
  },
  PagePhoto: (settings) => {
    return {
      upload: `/assets/${settings.key}/add-page-image`,
      generate: `/assets/${settings.key}/generate-page-image`,
      remove: `/assets/${settings.key}/remove-page-image`
    };
  },
  SiteAiModels: () => {
    return {
      setAiSettings: "/l/set-ai-settings"
    };
  },
  SiteAdministrators: () => {
    return {
      promote: "/l/site-administrators",
      demote: (key) => `/l/site-administrators/${key}`
    };
  },
  SiteDeployment: () => {
    return {
      setDeploymentSettings: "/l/set-deployment-settings"
    };
  },
  SiteImage: () => {
    return {
      setSiteImage: "/l/set-site-image"
    };
  },
  SiteMaintenance: () => {
    return {
      siteConfiguration: "/l/site-configuration",
      siteUpdate: "/l/site-update",
      rebuildCache: "/l/rebuild-cache"
    };
  },
  SiteSettings: () => {
    return {
      siteSettings: "/l/site-settings"
    };
  },
  HomeTaskList: () => {
    return {
      completeTask: (key) => {
        return `/tasks/${key}/complete`;
      },
      changeDueDate: (key) => {
        return `/tasks/${key}/change-due-date`;
      }
    };
  },
  TaskForm: (settings) => {
    return {
      latestHistorySubmission: `/tasks/${settings.key}/history/latest-submission`
    };
  },
  TaskUpload: (settings) => {
    return {
      upload: `/tasks/${settings.key}/upload-file`,
      remove: (fileKey) => `/tasks/${settings.key}/files/${fileKey}`
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
      getPageForm: (key) => `/files/ingress/${key}/get-page-form`
    };
  },
  search: {
    bar: "/l/search-bar",
    page: "/l/search-page"
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
      getContent: `/assets/${key}/html/${field}`
    };
  },
  renderer: {
    validateRow: (key, table_id) => `/forms/${key}/validate-row/${table_id}`,
    expandTableCell: (key, table_id) => `/forms/${key}/expand-table-cell/${table_id}`,
    getSchema: (key) => `/forms/${key}/schema`
  },
  manual: {
    section: (key) => {
      return `/manual/section/${key}`;
    }
  },
  collaboration: {
    start: `/collaboration/start`,
    stop: `/collaboration/stop`
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
    clearModal: (key) => `/l/messages/conversations/${key}/delete`
  },
  help: (key) => {
    return `/reference/section/${key}`;
  },
  createSchema: "/forms/create-schema",
  restrictions: (key) => `/forms/${key}/restrictions`,
  sync: "/l/sync"
};

const PARSER = new DOMParser();
const TOKEN_REQUEST = {
  credentials: "include",
  headers: { "X-Lagniappe-Request": "true" }
};
const UPDATED_HEADER = "X-Lagniappe-Updated";
const INVALIDATE_CACHE_HEADER = "X-Lagniappe-Invalidate-Cache";
const ENTITY_REVISIONS_HEADER = "X-Lagniappe-Entity-Revisions";
const CSRF_FAILURE_HEADER = "X-Lagniappe-CSRF";
const POLL_CHANNEL_HEADER = "X-Lagniappe-Poll-Channel";
const POLL_REVISION_HEADER = "X-Lagniappe-Poll-Revision";
const CSRF_METHODS = /* @__PURE__ */ new Set(["POST", "PUT", "PATCH", "DELETE"]);
const UPSTREAM_UPLOAD_OVERLOAD_ERROR = "Upload fewer files?";
const UPSTREAM_RESET_PATTERN = /upstream connect error|disconnect\/reset before headers|connection termination/i;
let _tokenRefresh = null;
const csrfFailed = (response) => response.status === 400 && response.headers.get(CSRF_FAILURE_HEADER)?.toLowerCase() === "invalid";
const _tokenInput = () => document.querySelector("#token");
const _parseHtml = (html) => html === "" || html === null ? html : PARSER.parseFromString(html, "text/html");
const _isEntityRevision = (revision) => Boolean(
  revision && typeof revision === "object" && "key" in revision && "fingerprint" in revision && typeof revision.key === "string" && revision.key && typeof revision.fingerprint === "string" && revision.fingerprint && (!("modified" in revision) || revision.modified === null || typeof revision.modified === "string")
);
const _formatResponse = async (response, { acknowledgeEntities = true } = {}) => {
  applyNotificationStateHeader(response.headers);
  if (response.status === 304) {
    return {
      ok: true,
      unchanged: true,
      etag: response.headers.get("ETag")
    };
  }
  const contentType = response.headers.get("content-type");
  const json = contentType?.includes("application/json") ? await response.json() : { html: await response.text() || "" };
  const { html, modal, ...data } = json ?? {};
  const revisions = /* @__PURE__ */ new Map();
  const revisionHeader = response.headers.get(ENTITY_REVISIONS_HEADER);
  if (revisionHeader) {
    try {
      const parsed = JSON.parse(revisionHeader);
      if (Array.isArray(parsed)) {
        for (const revision of parsed) {
          if (_isEntityRevision(revision))
            revisions.set(revision.key, revision);
        }
      }
    } catch {
    }
  }
  const entities = Array.from(revisions.values());
  if (acknowledgeEntities) {
    for (const entity of entities) {
      window.dispatchEvent(
        new CustomEvent("entity-updated", { detail: entity })
      );
    }
  }
  return {
    ok: response.ok,
    ...data,
    updated: response.headers.get(UPDATED_HEADER) !== "false",
    etag: response.headers.get("ETag"),
    pollChannel: response.headers.get(POLL_CHANNEL_HEADER),
    pollRevision: response.headers.get(POLL_REVISION_HEADER),
    reload: Boolean(data.reload) || response.headers.has(INVALIDATE_CACHE_HEADER),
    entities,
    ...html !== void 0 ? { html: _parseHtml(html) } : {},
    ...modal !== void 0 ? {
      modal: modal && !html ? PARSER.parseFromString(modal, "text/html") : modal
    } : {}
  };
};
const _isUploadBody = (body) => {
  if (!(body instanceof FormData)) return false;
  if (typeof body.has === "function" && body.has("direct_uploads")) return true;
  if (typeof body.has === "function" && body.has("assets")) return true;
  if (typeof body.entries !== "function") return true;
  for (const [, value] of body.entries()) {
    if (typeof File !== "undefined" && value instanceof File) return true;
    if (typeof Blob !== "undefined" && value instanceof Blob) return true;
  }
  return false;
};
const _friendlyError = (message, body) => {
  if (_isUploadBody(body) && UPSTREAM_RESET_PATTERN.test(String(message || ""))) {
    return UPSTREAM_UPLOAD_OVERLOAD_ERROR;
  }
  return message;
};
const _formatError = async (response, {
  replaceErrorPage = true,
  body = null
} = {}) => {
  const contentType = response.headers.get("content-type");
  if (contentType?.includes("application/json")) {
    const text2 = await response.text();
    try {
      const parsed = JSON.parse(text2);
      if (parsed === null) {
        return { ok: false, error: _friendlyError(text2, body) };
      }
      const { html, ...data } = parsed;
      if (data.error) {
        data.error = _friendlyError(data.error, body);
      }
      return {
        ok: false,
        ...data,
        ...html !== void 0 ? { html: _parseHtml(html) } : {}
      };
    } catch {
      return { ok: false, error: _friendlyError(text2, body) };
    }
  }
  const text = await response.text();
  const title = response.headers.get("X-Lagniappe-Error");
  const fallback = text.trim() || title || response.statusText || "Network request failed";
  const error = _friendlyError(fallback, body);
  if (!contentType?.includes("text/html")) {
    return {
      ok: false,
      error
    };
  }
  if (error !== fallback) {
    return {
      ok: false,
      error
    };
  }
  if (!replaceErrorPage) {
    return {
      ok: false,
      error: _friendlyError(title || response.statusText || fallback, body)
    };
  }
  if (!title) {
    document.documentElement.innerHTML = text;
    document.title = response.statusText;
  } else {
    const main = document.querySelector("main");
    if (main) main.innerHTML = text;
    document.title = title;
  }
  return {
    ok: false,
    error: _friendlyError(title || response.statusText || fallback, body)
  };
};
const _refreshToken = async () => {
  try {
    const response = await fetch("/l/token", TOKEN_REQUEST);
    if (!response.ok) {
      throw new Error(`Failed to refresh token: ${response.statusText}`);
    }
    const newToken = (await response.text()).trim();
    if (!newToken) {
      throw new Error("Failed to refresh token: empty response");
    }
    const tokenElt = _tokenInput();
    if (tokenElt) {
      tokenElt.value = newToken;
    }
    return newToken;
  } catch (error) {
    captureNetworkError(error, "/l/token", {
      });
    return null;
  }
};
const refreshToken = async () => {
  if (!_tokenRefresh) {
    _tokenRefresh = _refreshToken().finally(() => {
      _tokenRefresh = null;
    });
  }
  return _tokenRefresh;
};
const postRequest = async (url, body, {
  keepalive = false,
  headers = {},
  signal = void 0,
  replaceErrorPage = true
} = {}) => {
  return _request(url, {
    method: "POST",
    body,
    keepalive,
    requestHeaders: headers,
    signal,
    replaceErrorPage
  });
};
const patchRequest = async (url, body) => _request(url, { method: "PATCH", body });
const deleteRequest = async (url, body) => _request(url, { method: "DELETE", body });
const getRequest = async (url, params = null, options = {}) => {
  if (params) {
    let query;
    if (typeof params === "string" || params instanceof URLSearchParams || Array.isArray(params)) {
      query = new URLSearchParams(params);
    } else {
      const entries = params instanceof FormData ? params.entries() : Object.entries(params);
      query = new URLSearchParams(
        Array.from(entries, ([key, value]) => [key, String(value)])
      );
    }
    url = `${url}?${query}`;
  }
  return _request(url, { method: "GET", ...options });
};
const putRequest = async (url, body, options = {}) => _request(url, { method: "PUT", body, ...options });
const _request = (url, options) => (
  // Route-specific fields are supplied by the caller's endpoint contract.
  _requestResponse(url, options)
);
const _requestResponse = async (url, {
  method = "POST",
  body = null,
  keepalive = false,
  requestHeaders = {},
  acknowledgeEntities = true,
  replaceErrorPage = true,
  signal = void 0,
  retryUpstream = true
}) => {
  method = method.toUpperCase();
  const token = _tokenInput()?.value;
  const headers = {
    "Content-Type": "application/json",
    "X-CSRFToken": String(token),
    "X-Lagniappe-Request": "true",
    ...requestHeaders
  };
  const config = {
    method,
    headers,
    credentials: "include",
    ...signal ? { signal } : {},
    ...keepalive ? { keepalive: true } : {}
  };
  if (body) {
    if (body instanceof FormData) {
      delete headers["Content-Type"];
      config.body = body;
    } else {
      config.body = JSON.stringify(body);
    }
  }
  if (!CSRF_METHODS.has(method)) {
    delete headers["X-CSRFToken"];
  }
  const classifyUpstream = (response, allowRetry = retryUpstream) => handleUpstreamResponse(response, {
    method,
    url,
    retryUpstream: allowRetry,
    fetchResponse: () => fetch(url, config),
    retryCurrent: () => _requestResponse(window.location.pathname, {
      method: "GET",
      replaceErrorPage: false,
      retryUpstream: false
    }),
    retryOriginal: () => _requestResponse(url, {
      method: "GET",
      requestHeaders,
      acknowledgeEntities: false,
      replaceErrorPage: false,
      retryUpstream: false
    })
  });
  try {
    let response = await fetch(url, config);
    let upstream = await classifyUpstream(response);
    if ("result" in upstream) return upstream.result;
    response = upstream.response;
    if (CSRF_METHODS.has(method) && csrfFailed(response)) {
      const newToken = await refreshToken();
      if (!newToken) {
        return {
          ok: false,
          error: "Failed to refresh authentication token"
        };
      }
      headers["X-CSRFToken"] = newToken;
      response = await fetch(url, config);
      upstream = await classifyUpstream(response, false);
      if ("result" in upstream) return upstream.result;
      response = upstream.response;
    }
    if (response.status === 422) {
      return {
        ...await _formatError(response, { body, replaceErrorPage: false }),
        status: response.status
      };
    }
    if (response.redirected) {
      window.location.href = response.url;
      return;
    }
    return response.ok || response.status === 304 ? _formatResponse(response, { acknowledgeEntities }) : _formatError(response, { body, replaceErrorPage });
  } catch (error) {
    captureNetworkError(error, url, { method, ...config });
    return {
      ok: false,
      error: error && typeof error === "object" && "message" in error && typeof error.message === "string" && error.message ? error.message : "Network request failed"
    };
  }
};
const request = {
  csrfFailed,
  token: refreshToken,
  put: putRequest,
  post: postRequest,
  patch: patchRequest,
  delete: deleteRequest,
  get: getRequest
};

var request$1 = /*#__PURE__*/Object.freeze({
	__proto__: null,
	request: request
});

class StorageAdapter {
  constructor(name) {
    this.name = name;
  }
  _storage() {
    try {
      return globalThis[this.name] || null;
    } catch {
      return null;
    }
  }
  get(key, fallback = null) {
    try {
      const value = this._storage()?.getItem(key);
      return value === null || value === void 0 ? fallback : value;
    } catch {
      return fallback;
    }
  }
  set(key, value) {
    try {
      const storage = this._storage();
      if (!storage) return false;
      storage.setItem(key, value);
      return true;
    } catch {
      return false;
    }
  }
  remove(key) {
    try {
      const storage = this._storage();
      if (!storage) return false;
      storage.removeItem(key);
      return true;
    } catch {
      return false;
    }
  }
  getJSON(key, fallback = null) {
    const value = this.get(key);
    if (value === null) return fallback;
    try {
      return JSON.parse(value);
    } catch {
      this.remove(key);
      return fallback;
    }
  }
  setJSON(key, value) {
    try {
      const serialized = JSON.stringify(value);
      if (serialized === void 0) return false;
      return this.set(key, serialized);
    } catch {
      return false;
    }
  }
}
const localStore = new StorageAdapter("localStorage");
const sessionStore = new StorageAdapter("sessionStorage");
const clearRecentSearchResults = () => {
  const recentKeys = Array.from(
    { length: localStorage.length },
    (_, index) => localStorage.key(index)
  ).filter((key) => key?.startsWith("recent-") === true);
  recentKeys.forEach((key) => {
    localStorage.removeItem(key);
  });
};

var storage = /*#__PURE__*/Object.freeze({
	__proto__: null,
	clearRecentSearchResults: clearRecentSearchResults,
	localStore: localStore,
	sessionStore: sessionStore
});

const MOBILE_QUERY = "(max-width: 640px)";
function hasClosest(target) {
  return Boolean(
    target && "closest" in target && typeof target.closest === "function"
  );
}
const markPerformance = (name) => {
  if (typeof performance === "undefined" || !performance.mark) return;
  if (performance.getEntriesByName?.(name, "mark")?.length) return;
  performance.mark(name);
};
const whenIdle = () => new Promise((resolve) => {
  if (typeof globalThis.requestIdleCallback === "function") {
    globalThis.requestIdleCallback(resolve, { timeout: 1e3 });
    return;
  }
  setTimeout(resolve, 0);
});
const loadViewService = (view, promiseKey, handleKey, loader) => {
  const handles = view;
  const promises = view;
  const handle = handles[handleKey];
  if (handle) return Promise.resolve(handle);
  const existing = promises[promiseKey];
  if (existing) return existing;
  const pending = Promise.resolve().then(loader).then((manager) => {
    if (view._destroyed) {
      if (manager && "destroy" in manager && typeof manager.destroy === "function")
        manager.destroy();
      return null;
    }
    if (manager) handles[handleKey] = manager;
    return manager || null;
  }).catch((error) => {
    if (promises[promiseKey] === pending) promises[promiseKey] = null;
    throw error;
  });
  promises[promiseKey] = pending;
  return pending;
};
class ShellView {
  constructor(node) {
    this.elt = node;
    this.kind = node.dataset.kind;
    this.hash = node.dataset.hash || node.dataset.index;
    this.key = node.dataset.key;
    this.readonly = node.dataset.readonly === "true";
    this.mobile = window.matchMedia(MOBILE_QUERY).matches;
    this.online = connectivity.online;
    this.hidden = connectivity.hidden;
    this.components = {};
    this.SearchBox = null;
    this.Notifications = null;
    this.PollingCoordinator = null;
    this._destroyed = false;
    this._interactive = false;
    this._published = false;
    this.hasDeferredServices = false;
    this._coldActions = /* @__PURE__ */ new Map();
    this.copyResetTimers = /* @__PURE__ */ new Map();
    this._pointer = null;
    this.isDragging = false;
    this._handleClick = this._handleClick.bind(this);
    this._handleSubmit = this._handleSubmit.bind(this);
    this._pointerDown = this._pointerDown.bind(this);
    this._pointerMove = this._pointerMove.bind(this);
    this._pointerUp = this._pointerUp.bind(this);
    this._mobileChanged = this._mobileChanged.bind(this);
    this._publishedReady = new Promise((resolve) => {
      this._resolvePublished = resolve;
    });
    this.servicesReady = Promise.resolve(this);
  }
  async init() {
    if (this._interactive) return this;
    this._interactive = true;
    this.elt.addEventListener("click", this._handleClick);
    this.elt.addEventListener("submit", this._handleSubmit);
    this.elt.addEventListener("pointerdown", this._pointerDown);
    this._mobileQuery = window.matchMedia(MOBILE_QUERY);
    this._mobileQuery.addEventListener("change", this._mobileChanged);
    const mode = document.querySelector("meta[name='mode']")?.getAttribute("content");
    if (mode !== "public") this._installColdControlListeners?.();
    this.elt.dataset.interactive = "true";
    markPerformance("lagniappe:interaction-ready");
    if (!this.hasDeferredServices && mode !== "public") {
      this.hasDeferredServices = true;
      this._ownsShellServices = true;
      this._initializeShellServices();
    }
    return this;
  }
  ensurePollingCoordinator() {
    return loadViewService(
      this,
      "_pollingPromise",
      "PollingCoordinator",
      async () => {
        const { PollingCoordinator } = await import('./polling.js?v=bf7d4d98');
        return this._destroyed ? null : new PollingCoordinator(this).init();
      }
    );
  }
  ensureSearchBox() {
    return loadViewService(this, "_searchPromise", "SearchBox", async () => {
      const search = document.querySelector("[lp-search]");
      if (!search) return null;
      const { SearchBox } = await import('./combobox.js?v=bf7d4d98').then(function (n) { return n.d; });
      if (this._destroyed) return null;
      const box = new SearchBox(search);
      await box.init();
      return box;
    });
  }
  ensureNotifications() {
    return loadViewService(
      this,
      "_notificationsPromise",
      "Notifications",
      async () => {
        if (!document.querySelector("[data-role='notifications']")) return null;
        await this.ensurePollingCoordinator();
        const { Notifications } = await import('./notifications.js?v=bf7d4d98');
        if (this._destroyed) return null;
        const notifications = new Notifications(this);
        notifications.init();
        return notifications;
      }
    );
  }
  _initializeShellServices() {
    this.servicesReady = this._publishedReady.then(() => whenIdle()).then(async () => {
      const warmers = [];
      if (document.querySelector("[lp-search]")) {
        warmers.push(this.ensureSearchBox());
      }
      if (document.querySelector("[data-role='notifications']")) {
        warmers.push(this.ensureNotifications());
      }
      const results = await Promise.allSettled(warmers);
      for (const result of results) {
        if (result.status === "rejected") {
          this.reportStartupError(
            result.reason,
            this.elt,
            "shell-service-startup"
          );
        }
      }
      return results;
    }).catch((error) => {
      this.reportStartupError(error, this.elt, "shell-service-startup");
      return [];
    }).then(async (result) => {
      await this._publishedReady;
      if (!this._destroyed) markPerformance("lagniappe:services-ready");
      return result;
    });
  }
  reportStartupError(error, element = this.elt, context = "lazy-control") {
    void Promise.resolve().then(function () { return errors; }).then(({ captureError }) => {
      captureError(error, element, { context });
    }).catch(() => {
    });
  }
  _installColdControlListeners() {
    this._shellColdControl = (event) => {
      const { target } = event;
      if (!hasClosest(target)) return;
      const search = target.closest("[lp-search]");
      if (search && !this.SearchBox) {
        this.runColdAction(
          search,
          () => this.ensureSearchBox(),
          (box) => this._activateSearchBox(box),
          search
        );
        return;
      }
      const notifications = target.closest("[data-role='notifications']");
      if (!notifications || this.Notifications) return;
      if (event.type === "click") {
        event.preventDefault();
        event.stopImmediatePropagation?.();
      }
      this.runColdAction(
        notifications,
        () => this.ensureNotifications(),
        (manager) => manager?.dropdown?.showPanel?.(),
        notifications
      );
    };
    for (const type of ["input", "click"]) {
      document.addEventListener(type, this._shellColdControl, true);
    }
  }
  _activateSearchBox(box) {
    if (!box) return;
    const input = box.element;
    if (input?.value?.trim()) box._input({ target: input });
    else box.showPanel?.();
  }
  _removeColdControlListeners() {
    if (!this._shellColdControl) return;
    for (const type of ["input", "click"]) {
      document.removeEventListener(type, this._shellColdControl, true);
    }
    this._shellColdControl = null;
  }
  async sync({ hidden = document.hidden } = {}) {
    this.hidden = hidden;
    this.online = connectivity.online;
    if (hidden || !this.online) this.PollingCoordinator?.pause();
    else await this.PollingCoordinator?.resume();
  }
  publish() {
    if (this._destroyed || this._published) return this;
    this._published = true;
    this.elt.setAttribute("initialized", "");
    this.elt._lp_view = this;
    markPerformance("lagniappe:view-ready");
    this._resolvePublished?.(this);
    if (!this.hasDeferredServices) {
      queueMicrotask(() => {
        if (!this._destroyed) markPerformance("lagniappe:services-ready");
      });
    }
    return this;
  }
  _mobileChanged(event) {
    this.mobile = event.matches;
    this.elt.dispatchEvent(new CustomEvent("mobile-resize"));
  }
  _pointerDown(event) {
    if (event.button !== void 0 && event.button !== 0) return;
    this.isDragging = false;
    this._pointer = {
      id: event.pointerId,
      x: event.clientX,
      y: event.clientY
    };
    window.addEventListener("pointermove", this._pointerMove);
    window.addEventListener("pointerup", this._pointerUp);
    window.addEventListener("pointercancel", this._pointerUp);
  }
  _pointerMove(event) {
    if (!this._pointer) return;
    if (this._pointer.id !== void 0 && event.pointerId !== void 0 && event.pointerId !== this._pointer.id)
      return;
    const deltaX = Math.abs(event.clientX - this._pointer.x);
    const deltaY = Math.abs(event.clientY - this._pointer.y);
    if (deltaX > 5 || deltaY > 5) this.isDragging = true;
  }
  _pointerUp() {
    this._pointer = null;
    window.removeEventListener("pointermove", this._pointerMove);
    window.removeEventListener("pointerup", this._pointerUp);
    window.removeEventListener("pointercancel", this._pointerUp);
  }
  _handleClick(event) {
    if (this.isDragging) {
      this.isDragging = false;
      return;
    }
    const { target } = event;
    const copyButton = hasClosest(target) ? target.closest("[data-role='manual-command-copy']") : null;
    if (copyButton) {
      event.preventDefault();
      void this.copyCommand(copyButton);
      return;
    }
    this._click(event);
  }
  _click(_event) {
  }
  async copyCommand(button) {
    const command = button.closest("[data-role='manual-command-shell']")?.querySelector("[data-role='manual-command'] code")?.textContent;
    if (!command) return;
    let copied = false;
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(command);
        copied = true;
      }
    } catch {
      copied = false;
    }
    if (!copied) {
      const textarea = document.createElement("textarea");
      textarea.value = command;
      textarea.setAttribute("readonly", "");
      textarea.style.position = "fixed";
      textarea.style.opacity = "0";
      document.body.append(textarea);
      textarea.select();
      try {
        copied = document.execCommand("copy");
      } catch {
        copied = false;
      }
      textarea.remove();
      button.focus();
    }
    const resetTimer = this.copyResetTimers.get(button);
    if (resetTimer) clearTimeout(resetTimer);
    button.textContent = copied ? "Copied!" : "Copy failed";
    button.setAttribute(
      "aria-label",
      copied ? "Command copied" : "Command could not be copied"
    );
    this.copyResetTimers.set(
      button,
      setTimeout(() => {
        if (button.isConnected) {
          button.textContent = "Copy";
          button.setAttribute("aria-label", "Copy command");
        }
        this.copyResetTimers.delete(button);
      }, 2e3)
    );
  }
  _handleSubmit(event) {
    if (!this.ensureSubmissionManager || event.defaultPrevented) return;
    const form = event.target;
    if (!hasClosest(form) || !form.closest("[lp-component]")) return;
    event.preventDefault();
    event.stopPropagation();
    const submitter = "submitter" in event && event.submitter && "disabled" in event.submitter ? event.submitter : null;
    if (submitter) submitter.disabled = true;
    let handedOff = false;
    this.runColdAction(
      form,
      () => this.ensureSubmissionManager?.(),
      (manager) => {
        if (this._destroyed || !form.isConnected || !manager) return;
        handedOff = true;
        return manager.submit(event);
      },
      submitter
    ).finally(() => {
      if (submitter && !handedOff) submitter.disabled = false;
    });
  }
  runColdAction(owner, load, activate, busyOwner = owner) {
    if (!owner || this._destroyed) return Promise.resolve(null);
    const existing = this._coldActions.get(owner);
    if (existing) return existing;
    busyOwner?.setAttribute?.("aria-busy", "true");
    const dataset = busyOwner && "dataset" in busyOwner ? busyOwner.dataset : void 0;
    if (dataset) dataset.loading = "true";
    const pending = Promise.resolve().then(load).then((value) => {
      if (this._destroyed) return null;
      return activate(value);
    }).catch((error) => {
      this.reportStartupError?.(error, owner);
      return null;
    }).finally(() => {
      busyOwner?.removeAttribute?.("aria-busy");
      if (dataset) delete dataset.loading;
      if (this._coldActions.get(owner) === pending) {
        this._coldActions.delete(owner);
      }
    });
    this._coldActions.set(owner, pending);
    return pending;
  }
  destroy() {
    this._destroyed = true;
    for (const timer of this.copyResetTimers.values()) clearTimeout(timer);
    this.copyResetTimers.clear();
    this._pointerUp();
    this.elt.removeEventListener("click", this._handleClick);
    this.elt.removeEventListener("submit", this._handleSubmit);
    this.elt.removeEventListener("pointerdown", this._pointerDown);
    this._mobileQuery?.removeEventListener("change", this._mobileChanged);
    this._removeColdControlListeners?.();
    this._coldActions.clear();
    if (this._ownsShellServices) {
      this.Notifications?.destroy?.();
      this.PollingCoordinator?.destroy?.();
      this.SearchBox?.destroy?.();
    }
    if (this.elt._lp_view === this) delete this.elt._lp_view;
  }
}

class QueryLifecycle {
  constructor() {
    this.epoch = 0;
    this.controller = null;
    this.destroyed = false;
  }
  begin(key, { cancelTransport = true } = {}) {
    if (this.destroyed) return null;
    this.invalidate();
    if (this.destroyed) return null;
    if (cancelTransport && typeof AbortController !== "undefined") {
      this.controller = new AbortController();
    }
    return {
      epoch: this.epoch,
      key,
      signal: this.controller?.signal
    };
  }
  isCurrent(token, currentKey = token?.key) {
    return Boolean(
      token && !this.destroyed && token.epoch === this.epoch && token.key === currentKey
    );
  }
  invalidate() {
    this.epoch += 1;
    this.controller?.abort();
    this.controller = null;
  }
  destroy() {
    if (this.destroyed) return;
    this.destroyed = true;
    this.invalidate();
  }
  async run(key, loader, publisher, { getCurrentKey = () => key, cancelTransport = true } = {}) {
    const token = this.begin(key, { cancelTransport });
    if (!token) return false;
    try {
      const result = await loader(token);
      if (!this.isCurrent(token, getCurrentKey())) return false;
      await publisher(result, token);
      return this.isCurrent(token, getCurrentKey());
    } catch (error) {
      const failure = error;
      if (failure?.name === "AbortError" && !this.isCurrent(token, getCurrentKey())) {
        return false;
      }
      throw error;
    }
  }
}

export { ENDPOINTS as E, QueryLifecycle as Q, ShellView as S, clearRecentSearchResults as a, whenIdle as b, captureError as c, debounce as d, localStore as e, areEqual as f, generateElementId as g, base64ToUint8Array as h, waitForAttribute as i, sessionStore as j, applyNotificationStateHeader as k, loadViewService as l, markPerformance as m, renderNotificationBadge as n, errors as o, request$1 as p, storage as q, request as r, showBriefly as s, uint8ArrayToBase64 as u, withTransition as w };
