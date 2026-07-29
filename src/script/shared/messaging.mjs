import { initializeApp } from "firebase/app";
import {
	getMessaging,
	getToken as getMessagingToken,
	isSupported as isMessagingSupported,
} from "firebase/messaging";
import { captureError } from "./errors";
import { MessagingModal } from "./modal";
import { request } from "./request";

let askPermission = null;
const TEST_TOKEN_PREFIX = "test:";
const FIREBASE_CONFIG_TIMEOUT_MS = 1500;
const SERVICE_WORKER_READY_TIMEOUT_MS = 1500;
const NOTIFICATION_PERMISSION_TIMEOUT_MS = 3000;
const FCM_TOKEN_TIMEOUT_MS = 2000;
const MESSAGING_DIAGNOSTICS_TIMEOUT_MS = 1000;

// Check if we're in testing mode (set by base.html when TESTING=true)
/**
 * @testable false
 * @covered-by src/script/shared/messaging.mjs::initializeMessaging
 * @reason testing-mode predicate feeds messaging initialization
 */
const isTestingMode = () => window.__TESTING__ === true;

/**
 * @testable false
 * @covered-by src/script/shared/messaging.mjs::initializeMessaging
 * @reason deterministic test token generation is part of messaging initialization
 */
function _getTestMessagingToken() {
	const stored = localStorage.getItem("firebase");
	if (stored) {
		const config = JSON.parse(stored);
		if (config?.fcmToken?.startsWith(TEST_TOKEN_PREFIX)) {
			return config.fcmToken;
		}
	}

	const existing = sessionStorage.getItem("testFcmToken");
	if (existing?.startsWith(TEST_TOKEN_PREFIX)) return existing;

	const userHash = sessionStorage.getItem("userHash");
	const identifier =
		userHash ||
		globalThis.crypto?.randomUUID?.() ||
		`${Date.now()}-${Math.random()}`;
	const token = `${TEST_TOKEN_PREFIX}${identifier}`;
	sessionStorage.setItem("testFcmToken", token);
	return token;
}

/**
 * @testable false
 * @covered-by src/script/shared/messaging.mjs::initializeMessaging
 * @reason Firebase config caching is part of messaging initialization
 */
async function _getFirebaseConfig() {
	const stored = localStorage.getItem("firebase");
	if (stored) {
		const config = JSON.parse(stored);
		if (config.ok === true) {
			return config;
		}
	}

	const firebaseConfig = await request.get("/firebase-config");
	if (firebaseConfig.ok === true) {
		localStorage.setItem("firebase", JSON.stringify(firebaseConfig));
		return firebaseConfig;
	}
	return null;
}

/**
 * @testable false
 * @covered-by src/script/shared/messaging.mjs::initializeMessaging
 * @reason Firebase config writes are part of messaging initialization
 */
function _setFirebaseConfig(config) {
	localStorage.setItem("firebase", JSON.stringify(config));
}

/**
 * @testable false
 * @covered-by src/script/shared/messaging.mjs::initializeMessaging
 * @reason cached-token reuse is part of messaging initialization
 */
function _cachedMessagingToken(config) {
	return typeof config?.fcmToken === "string" && config.fcmToken.length > 0
		? config.fcmToken
		: null;
}

/**
 * @testable false
 * @covered-by src/script/shared/messaging.mjs::initializeMessaging
 * @reason timeout handling belongs to the messaging initialization contract
 */
function _withTimeout(promise, label, timeoutMs) {
	let timeoutId = null;
	const timeout = new Promise((_, reject) => {
		timeoutId = setTimeout(() => {
			const error = new Error(
				`Firebase messaging ${label} timed out after ${timeoutMs}ms`,
			);
			error.name = "MessagingTimeoutError";
			error.messagingPhase = label;
			reject(error);
		}, timeoutMs);
	});

	return Promise.race([promise, timeout]).finally(() => {
		clearTimeout(timeoutId);
	});
}

/**
 * @testable false
 * @covered-by src/script/shared/messaging.mjs::initializeMessaging
 * @reason permission prompts are user-paced and should not be reported as Firebase failures
 */
async function _askNotificationPermission() {
	const messagingModal = new MessagingModal();
	return await messagingModal.init({
		timeoutMs: NOTIFICATION_PERMISSION_TIMEOUT_MS,
	});
}

/**
 * @testable false
 * @covered-by src/script/shared/messaging.mjs::initializeMessaging
 * @reason permission prompts should only happen when the document can present the modal immediately
 */
function _canPromptForNotificationPermission() {
	return globalThis.document?.visibilityState !== "hidden";
}

/**
 * @testable false
 * @covered-by src/script/shared/messaging.mjs::initializeMessaging
 * @reason existing push subscriptions let a cached token avoid a duplicate permission prompt
 */
async function _hasExistingPushSubscription(registration) {
	if (!registration?.pushManager) return false;

	try {
		return Boolean(
			await _withTimeout(
				registration.pushManager.getSubscription(),
				"existing push subscription",
				MESSAGING_DIAGNOSTICS_TIMEOUT_MS,
			),
		);
	} catch {
		return false;
	}
}

/**
 * @testable false
 * @covered-by src/script/shared/messaging.mjs::initializeMessaging
 * @reason anonymized config shape is reported only when messaging initialization fails
 */
function _summarizeFirebaseConfig(config) {
	return {
		cached: Boolean(config),
		ok: config?.ok === true,
		testing: config?.testing === true,
		hasApiKey: typeof config?.apiKey === "string" && config.apiKey.length > 0,
		hasAppId: typeof config?.appId === "string" && config.appId.length > 0,
		hasProjectId:
			typeof config?.projectId === "string" && config.projectId.length > 0,
		hasMessagingSenderId:
			typeof config?.messagingSenderId === "string" &&
			config.messagingSenderId.length > 0,
		hasVapidKey:
			typeof config?.vapidKey === "string" && config.vapidKey.length > 0,
		vapidKeyLength:
			typeof config?.vapidKey === "string" ? config.vapidKey.length : 0,
		hasFcmToken:
			typeof config?.fcmToken === "string" && config.fcmToken.length > 0,
	};
}

/**
 * @testable false
 * @covered-by src/script/shared/messaging.mjs::initializeMessaging
 * @reason diagnostics must remain bounded so messaging failures cannot delay view startup
 */
async function _diagnosticValue(label, callback) {
	try {
		return await _withTimeout(
			Promise.resolve().then(callback),
			`diagnostics ${label}`,
			MESSAGING_DIAGNOSTICS_TIMEOUT_MS,
		);
	} catch (error) {
		return {
			error: error.name || "Error",
			message: error.message || String(error),
		};
	}
}

/**
 * @testable false
 * @covered-by src/script/shared/messaging.mjs::initializeMessaging
 * @reason service worker diagnostics are captured only when messaging initialization fails
 */
async function _getServiceWorkerDiagnostics() {
	const serviceWorker = globalThis.navigator?.serviceWorker;
	const supported = Boolean(serviceWorker);
	const diagnostics = {
		supported,
		controller: Boolean(serviceWorker?.controller),
		controllerState: serviceWorker?.controller?.state || null,
	};
	if (!supported) return diagnostics;

	const registration = await _diagnosticValue(
		"service worker registration",
		() => serviceWorker.getRegistration(),
	);
	if (!registration || registration.error) {
		diagnostics.registration = registration || null;
		return diagnostics;
	}

	diagnostics.registration = {
		found: true,
		scopePath: new URL(registration.scope).pathname,
		activeState: registration.active?.state || null,
		waitingState: registration.waiting?.state || null,
		installingState: registration.installing?.state || null,
		pushManager: Boolean(registration.pushManager),
	};

	if (!registration.pushManager) return diagnostics;

	const subscription = await _diagnosticValue("push subscription", () =>
		registration.pushManager.getSubscription(),
	);
	if (!subscription || subscription.error) {
		diagnostics.pushSubscription = subscription || null;
		return diagnostics;
	}

	diagnostics.pushSubscription = {
		exists: true,
		endpointHost: new URL(subscription.endpoint).host,
		expirationTime: subscription.expirationTime || null,
		hasAuthKey: Boolean(subscription.getKey("auth")),
		hasP256dhKey: Boolean(subscription.getKey("p256dh")),
	};
	return diagnostics;
}

/**
 * @testable false
 * @covered-by src/script/shared/messaging.mjs::initializeMessaging
 * @reason IndexedDB diagnostics are captured only when messaging initialization fails
 */
async function _getIndexedDbDiagnostics() {
	const databaseApi = globalThis.indexedDB;
	const supported = Boolean(databaseApi);
	const diagnostics = {
		supported,
		databasesSupported: Boolean(databaseApi?.databases),
	};
	if (!supported || !databaseApi.databases) return diagnostics;

	const databases = await _diagnosticValue("indexedDB databases", () =>
		databaseApi.databases(),
	);
	if (!Array.isArray(databases)) {
		diagnostics.databases = databases;
		return diagnostics;
	}

	diagnostics.firebaseDatabaseCount = databases.filter(({ name = "" }) =>
		/firebase|fcm|installation/i.test(name),
	).length;
	return diagnostics;
}

/**
 * @testable false
 * @covered-by src/script/shared/messaging.mjs::initializeMessaging
 * @reason messaging diagnostics are reported only after a failed initialization attempt
 */
async function _getMessagingDiagnostics(config, error) {
	return {
		phase: error?.messagingPhase || null,
		online: globalThis.navigator?.onLine ?? null,
		secureContext: globalThis.isSecureContext === true,
		visibilityState: globalThis.document?.visibilityState || null,
		notificationPermission:
			globalThis.Notification?.permission || "unsupported",
		config: _summarizeFirebaseConfig(config),
		serviceWorker: await _getServiceWorkerDiagnostics(),
		indexedDb: await _getIndexedDbDiagnostics(),
	};
}

/**
 * @testable false
 * @covered-by src/script/shared/messaging.mjs::initializeMessaging
 * @reason async diagnostics should not block messaging fallback
 */
function _captureMessagingError(error, config) {
	_getMessagingDiagnostics(config, error)
		.then((diagnostics) => {
			captureError(error, null, {
				firebase_messaging: {
					component: "firebase_messaging",
					...diagnostics,
				},
			});
		})
		.catch((diagnosticError) => {
			captureError(error, null, {
				firebase_messaging: {
					component: "firebase_messaging",
					diagnosticsError: {
						name: diagnosticError.name || "Error",
						message: diagnosticError.message || String(diagnosticError),
					},
				},
			});
		});
}

/**
 * @testable true
 * @tests tests_e2e/001_site/test_001c_messaging.py::test_allow_messages
 * @tests tests_js/test_013_messaging_frontend.py::test_cached_token_with_existing_subscription_skips_permission_prompt
 * @tests tests_js/test_013_messaging_frontend.py::test_hidden_default_permission_skips_permission_prompt
 * @tests tests_js/test_013_messaging_frontend.py::test_messaging_diagnostics_context_is_sentry_object_shaped
 * @tests tests_js/test_013_messaging_frontend.py::test_unsupported_browser_skips_firebase_messaging
 * @features messaging
 * @dimensions permission-modal cached-token hidden-document unsupported-browser graceful-fallback sentry-context diagnostics
 */
export async function initializeMessaging() {
	let config = null;
	try {
		if (isTestingMode()) {
			const token = _getTestMessagingToken();
			_setFirebaseConfig({ ok: true, fcmToken: token, testing: true });
			return token;
		}

		if (!(await isMessagingSupported())) return null;

		config = await _withTimeout(
			_getFirebaseConfig(),
			"config request",
			FIREBASE_CONFIG_TIMEOUT_MS,
		);
		if (!config) {
			const error = new Error("Firebase messaging config is unavailable");
			error.name = "MessagingConfigError";
			throw error;
		}
		const app = initializeApp(config);
		const messaging = getMessaging(app);
		const cachedToken = _cachedMessagingToken(config);

		if ("serviceWorker" in navigator) {
			const registration = await _withTimeout(
				navigator.serviceWorker.ready,
				"service worker readiness",
				SERVICE_WORKER_READY_TIMEOUT_MS,
			);

			if (!globalThis.Notification) return null;
			let permission = Notification.permission;

			if (permission === "default" && !isTestingMode()) {
				if (cachedToken && (await _hasExistingPushSubscription(registration))) {
					return cachedToken;
				}
				if (!_canPromptForNotificationPermission()) return null;
				if (!askPermission) {
					askPermission = _askNotificationPermission().finally(() => {
						askPermission = null;
					});
				}
				permission = await askPermission;
			}
			permission = Notification.permission;

			if (permission === "granted") {
				const currentToken = await _withTimeout(
					getMessagingToken(messaging, {
						vapidKey: config.vapidKey,
						serviceWorkerRegistration: registration,
					}),
					"FCM token request",
					FCM_TOKEN_TIMEOUT_MS,
				);

				if (currentToken && currentToken !== config.fcmToken) {
					config.fcmToken = currentToken;
					_setFirebaseConfig(config);
				}

				return currentToken;
			}
		}

		return null;
	} catch (error) {
		_captureMessagingError(error, config);
		return null;
	}
}
