import assert from "node:assert/strict";
import { test } from "node:test";
import esmock from "esmock";
import { createBrowser } from "../utility/js/environment.mjs";

function operationNode(key, { visible = true, append = true } = {}) {
	const node = document.createElement("section");
	node.dataset.operation = key;
	node.dataset.operationRevision = "0";
	const phase = document.createElement("span");
	phase.dataset.role = "deferred-phase";
	phase.textContent = "Waiting to start";
	const elapsed = document.createElement("span");
	elapsed.dataset.role = "deferred-elapsed";
	elapsed.textContent = "just now";
	node.append(phase, elapsed);
	node.closest = () => (visible ? null : document.body);
	node.getClientRects = () => (visible ? [{}] : []);
	if (append) document.body.append(node);
	return { elapsed, node, phase };
}

async function loadManager() {
	const capturedErrors = [];
	const createIcon = () => document.createElement("span");
	const withTransition = (callback) => callback();
	const { DeferredOperationManager } = await esmock.strict(
		"../../src/script/shared/deferredOperations.mjs",
		{
			"../../src/script/shared/errors.mjs": {
				captureError: (...args) => capturedErrors.push(args),
			},
			"../../src/script/shared/icons.mjs": { createIcon },
			"../../src/script/shared/transitions.mjs": { withTransition },
		},
	);
	return { capturedErrors, DeferredOperationManager };
}

/**
 * @matrix deferred-jobs : backoff decoration-opt-out lazy-watcher polling progress rendered-visibility revision status teardown terminal-ownership timing visible-blur
 */
test("test_deferred_operation_manager_batches_orders_and_renders_status", async (t) => {
	createBrowser(t);
	const first = operationNode("operation-a");
	operationNode("operation-b", { visible: false });
	const subscriptions = new Map();
	const descriptors = new Map();
	const schedules = new Map();
	const triggers = [];
	const reconciled = [];
	const expectedCompletions = [];
	let ensureEditWatcherCalls = 0;
	let reschedules = 0;
	const blurStarts = [];
	const coordinator = {
		subscribe(descriptor, hooks) {
			descriptors.set(descriptor.id, descriptor);
			schedules.set(descriptor.id, {
				mode: hooks.mode,
				initial: hooks.initial,
			});
			subscriptions.set(descriptor.id, hooks);
			return () => subscriptions.delete(descriptor.id);
		},
		async trigger(ids) {
			triggers.push(ids);
			return [];
		},
		blur(startedAt) {
			blurStarts.push(startedAt);
		},
		reschedule() {
			reschedules += 1;
		},
	};
	const { DeferredOperationManager } = await loadManager();
	const editWatcher = {
		expectDeferredCompletion(key, operation) {
			expectedCompletions.push({ key, operation });
		},
	};
	const view = {
		PollingCoordinator: coordinator,
		EditWatcher: null,
		async ensureEditWatcher() {
			ensureEditWatcherCalls += 1;
			this.EditWatcher = editWatcher;
			return editWatcher;
		},
		async reconcileChange(change) {
			reconciled.push(change);
		},
	};
	const manager = new DeferredOperationManager(view).init();

	assert.equal(subscriptions.size, 2);
	assert.equal(triggers.length, 0);
	assert.equal(descriptors.get("operation:operation-a")?.revision, 0);
	assert.equal(schedules.get("operation:operation-a")?.initial, "scheduled");
	assert.equal(subscriptions.get("operation:operation-a").whileBlurred(), true);
	assert.equal(
		subscriptions.get("operation:operation-b").whileBlurred(),
		false,
	);
	manager.track("operation-local", { revision: 2 });
	assert.equal(triggers[0], "operation:operation-local");
	assert.equal(
		subscriptions.get("operation:operation-local").whileBlurred(),
		false,
	);
	view.hidden = true;
	view.blurred = true;
	view.blurredAt = 42;
	manager.track("operation-a", { node: first.node, immediate: false });
	view.hidden = false;
	view.blurred = false;
	assert.equal(reschedules, 1);
	assert.deepEqual(blurStarts, [42]);
	await manager.poll();
	assert.equal(triggers.length, 2);
	assert.equal(triggers[1].length, 3);

	await subscriptions.get("operation:operation-a").onResult({
		status: "changed",
		payload: {
			key: "operation-a",
			status: "running",
			phase: "generating",
			phase_label: "Generating",
			elapsed_seconds: 75,
			revision: 3,
			terminal: false,
		},
	});
	assert.equal(first.phase.textContent, "Generating");
	assert.equal(first.elapsed.textContent, "1 min");

	await subscriptions.get("operation:operation-b").onResult({
		status: "changed",
		payload: {
			key: "operation-b",
			status: "succeeded",
			phase: "complete",
			phase_label: "Complete",
			elapsed_seconds: 12,
			revision: 2,
			terminal: true,
			entity_key: "report-b",
			source_widget: "CreateToolReport",
			destination: "tools:ToolReportList",
		},
	});
	assert.equal(manager.operations.has("operation-b"), false);
	assert.equal(reconciled[0]?.key, "report-b");
	assert.equal(ensureEditWatcherCalls, 1);
	assert.deepEqual(expectedCompletions[0], {
		key: "report-b",
		operation: "operation-b",
	});
	assert.equal(manager.nudge("operation-a", 2), false);

	const newer = operationNode("operation-a");
	Object.assign(newer.node.dataset, {
		operationRevision: "5",
		operationStatus: "retry_wait",
		operationPhase: "using_tools",
		operationPhaseLabel: "Checking context",
		operationRecovering: "true",
		operationElapsed: "80",
	});
	const older = operationNode("operation-a");
	Object.assign(older.node.dataset, {
		operationRevision: "2",
		operationStatus: "running",
		operationPhase: "generating",
		operationPhaseLabel: "Generating",
	});
	manager.scan();
	for (const operation of [first, newer, older]) {
		assert.equal(
			operation.phase.textContent,
			"Checking context. Taking longer than expected.",
		);
		assert.equal(operation.node.dataset.operationRevision, "5");
	}
	manager.scan();
	await subscriptions
		.get("operation:operation-a")
		.onResult({ status: "unchanged" });
	assert.equal(older.phase.textContent, newer.phase.textContent);
	assert.equal(
		manager.operations.get("operation-a").status.phase_label,
		"Checking context",
	);
	manager.nudge("operation-a");
	assert.equal(manager.operations.get("operation-a").revision, 5);
	manager.track("operation-replacement", {
		node: newer.node,
		immediate: false,
	});
	assert.equal(subscriptions.has("operation:operation-a"), true);
	assert.equal(older.node.dataset.operation, "operation-a");

	const owner = document.createElement("section");
	owner.dataset.operation = "operation-owned";
	owner.dataset.operationRevision = "0";
	owner.closest = () => null;
	owner.getClientRects = () => [{}];
	document.body.append(owner);
	manager.track("operation-owned", { node: owner, immediate: false });
	const progress = owner.querySelector("[data-role='deferred-progress']");
	assert.ok(progress);
	assert.equal(Boolean(progress.dataset.operation), false);
	manager.track("operation-next", { node: owner, immediate: false });
	assert.equal(subscriptions.has("operation:operation-owned"), false);
	assert.equal(owner.dataset.operation, "operation-next");

	for (const [scope, expected] of [
		["form-change", "Schema migration in progress"],
		["form-autofill", "Autofill queued"],
	]) {
		const form = document.createElement("form");
		form.dataset.operation = `operation-${scope}`;
		form.dataset.operationRevision = "0";
		form.dataset.deferredLock = "form";
		form.dataset.operationScope = scope;
		const autofill = document.createElement("button");
		autofill.dataset.role = "autofill";
		const submit = document.createElement("div");
		submit.dataset.role = "submit-group";
		form.append(autofill, submit);
		document.body.append(form);
		manager.scan({ querySelectorAll: () => [form] });
		assert.equal(
			form.querySelector("[data-role='deferred-phase']")?.textContent,
			expected,
		);
		await manager.receive({
			key: form.dataset.operation,
			revision: 1,
			status: "running",
			phase_label: "Applying changes",
			terminal: false,
		});
		assert.equal(
			form.querySelector("[data-role='deferred-phase']").textContent,
			"Applying changes",
		);
	}

	manager.destroy();
	assert.equal(manager.operations.size, 0);
	assert.equal(subscriptions.size, 0);
});

/** @matrix deferred-jobs : terminal-ownership revision */
test("test_deferred_operation_manager_reconciles_server_rendered_terminal_status", async (t) => {
	createBrowser(t);
	const operation = operationNode("operation-complete");
	Object.assign(operation.node.dataset, {
		key: "report-ready",
		operationRevision: "7",
		operationStatus: "succeeded",
		operationPhase: "complete",
		operationPhaseLabel: "Complete",
		operationElapsed: "3",
		operationRecovering: "false",
		operationTerminal: "true",
	});
	operation.phase.textContent = "Complete";
	const subscriptions = new Map();
	const triggers = [];
	const events = [];
	const reconciled = [];
	const expectedCompletions = [];
	window.addEventListener("deferred-operation", (event) => events.push(event));
	const { DeferredOperationManager } = await loadManager();
	const view = {
		PollingCoordinator: {
			subscribe(descriptor, hooks) {
				subscriptions.set(descriptor.id, { descriptor, ...hooks });
				return () => subscriptions.delete(descriptor.id);
			},
			trigger(ids) {
				triggers.push(ids);
			},
			reschedule() {},
		},
		EditWatcher: {
			expectDeferredCompletion(key, operationKey) {
				expectedCompletions.push({ key, operation: operationKey });
			},
		},
		async reconcileChange(change) {
			reconciled.push(change);
			if (reconciled.length === 1) {
				throw new Error("Replacement temporarily unavailable");
			}
		},
	};
	const manager = new DeferredOperationManager(view).init();
	manager.scan();
	const subscription = subscriptions.get("operation:operation-complete");
	assert.equal(events.length, 0);
	assert.equal(reconciled.length, 0);
	assert.equal(subscriptions.size, 1);
	assert.ok(subscription.descriptor.revision < 7);
	assert.equal(triggers.length, 2);
	const result = {
		status: "changed",
		payload: {
			key: "operation-complete",
			revision: 7,
			status: "succeeded",
			phase: "complete",
			phase_label: "Complete",
			terminal: true,
			entity_key: "authoritative-report",
			source_widget: "CreateToolReport",
			destination: "tools:ToolReportList",
		},
	};
	assert.equal(await subscription.onResult(result), false);
	assert.equal(subscriptions.size, 1);
	assert.equal(await subscription.onResult(result), true);
	assert.equal(events.length, 2);
	assert.equal(events[0].type, "deferred-operation");
	assert.equal(events[0].detail.key, "operation-complete");
	assert.equal(events[0].detail.entity_key, "authoritative-report");
	assert.equal(reconciled.length, 2);
	assert.equal(reconciled[0].type, "deferred-complete");
	assert.equal(reconciled[0].key, "authoritative-report");
	assert.equal(reconciled[0].destination, "tools:ToolReportList");
	assert.equal(reconciled[0].source_widget, "CreateToolReport");
	assert.equal(expectedCompletions[0]?.operation, "operation-complete");
	assert.equal(manager.operations.size, 0);
	assert.equal(subscriptions.size, 0);
});

/** @matrix deferred-jobs : rendered-autofill rendered-visibility */
test("test_cold_task_operations_wait_for_activation_and_completed_reviews_need_no_poll", async (t) => {
	createBrowser(t);
	const running = operationNode("task-running").node;
	running.dataset.widget = "TaskForm";
	running.dataset.operationRevision = "2";
	running.dataset.operationBootstrap = JSON.stringify({
		key: "task-running",
		revision: 2,
		type: "autofill",
		status: "running",
		terminal: false,
	});
	running.dataset.formState = JSON.stringify({
		operation: JSON.parse(running.dataset.operationBootstrap),
		reviews: [],
	});
	const complete = operationNode("task-complete").node;
	complete.dataset.widget = "TaskForm";
	complete.dataset.operationRevision = "7";
	complete.dataset.operationBootstrap = JSON.stringify({
		key: "task-complete",
		revision: 7,
		type: "autofill",
		status: "succeeded",
		terminal: true,
	});
	complete.dataset.formState = JSON.stringify({
		operation: JSON.parse(complete.dataset.operationBootstrap),
		reviews: [{ operation: "task-complete" }],
	});
	const subscriptions = new Map();
	const triggers = [];
	const { DeferredOperationManager } = await loadManager();
	const manager = new DeferredOperationManager({
		PollingCoordinator: {
			subscribe(descriptor, hooks) {
				subscriptions.set(descriptor.id, hooks);
				return () => subscriptions.delete(descriptor.id);
			},
			trigger(ids) {
				triggers.push(ids);
			},
			reschedule() {},
		},
	}).init();
	assert.equal(subscriptions.size, 0);
	assert.equal(triggers.length, 0);

	// Opening a task registers its running operation; closing drops it.
	manager.resumeTaskForm(running);
	assert.equal(subscriptions.has("operation:task-running"), true);
	assert.deepEqual(triggers, ["operation:task-running"]);
	manager.suspendTaskForm(running);
	assert.equal(subscriptions.size, 0);
	assert.equal(manager.operations.size, 0);
	manager.resumeTaskForm(running);
	assert.equal(subscriptions.has("operation:task-running"), true);

	// The server-rendered review is already authoritative; it needs no
	// operation poll or task-form reconciliation even after opening.
	manager.resumeTaskForm(complete);
	assert.equal(subscriptions.has("operation:task-complete"), false);
	assert.equal(triggers.includes("operation:task-complete"), false);
	manager.destroy();
});

/**
 * @source src/script/shared/deferredOperations.mjs::DeferredOperationManager
 * @pair deferred-jobs:review-probe
 */
test("test_successful_autofill_waits_for_active_form_review_before_retiring", async (t) => {
	createBrowser(t);
	const form = document.createElement("form");
	form.dataset.operation = "autofill-job";
	form.dataset.operationRevision = "0";
	document.body.append(form);
	const widget = { visible: true, reviewState: { reviews: [] } };
	widget.component = { active: widget };
	form._lp_widget = widget;
	const subscriptions = new Map();
	const { DeferredOperationManager } = await loadManager();
	const view = {
		PollingCoordinator: {
			subscribe(descriptor, hooks) {
				subscriptions.set(descriptor.id, hooks);
				return () => subscriptions.delete(descriptor.id);
			},
			reschedule() {},
		},
		EditWatcher: { expectDeferredCompletion() {} },
		async reconcileChange() {},
	};
	const manager = new DeferredOperationManager(view);
	manager.track("autofill-job", { node: form, immediate: false });
	const status = {
		key: "autofill-job",
		revision: 1,
		type: "autofill",
		status: "succeeded",
		terminal: true,
		entity_key: "task-key",
	};
	assert.equal(await manager.receive(status), false);
	assert.equal(manager.operations.has("autofill-job"), true);
	assert.equal(subscriptions.has("operation:autofill-job"), true);
	widget.reviewState.reviews = [{ operation: "autofill-job" }];
	assert.equal(await manager.receive(status), true);
	assert.equal(manager.operations.has("autofill-job"), false);
	assert.equal(subscriptions.has("operation:autofill-job"), false);
	form.dataset.operation = "obsolete-job";
	widget.reviewState.reviews = [];
	manager.track("obsolete-job", { node: form, immediate: false });
	const obsoleteStatus = { ...status, key: "obsolete-job" };
	assert.equal(await manager.receive(obsoleteStatus), false);
	widget.reviewState.stale_autofill = true;
	assert.equal(await manager.receive(obsoleteStatus), true);
	assert.equal(manager.operations.has("obsolete-job"), false);
	assert.equal(subscriptions.has("operation:obsolete-job"), false);
});
