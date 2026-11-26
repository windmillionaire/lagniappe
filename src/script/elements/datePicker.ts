import {
	autoUpdate,
	computePosition,
	flip,
	offset,
	shift,
} from "@floating-ui/dom";
import { STYLES } from "../generated/styles.mjs";
import { setIcon } from "../shared/icons.ts";

const WEEKDAYS = ["Su", "Mo", "Tu", "We", "Th", "Fr", "Sa"] as const;
const MONTHS = [
	"January",
	"February",
	"March",
	"April",
	"May",
	"June",
	"July",
	"August",
	"September",
	"October",
	"November",
	"December",
] as const;

let activePicker: DatePicker | null = null;
const pickers = new WeakMap<HTMLInputElement, DatePicker>();

export function closeActiveDatePicker() {
	activePicker?.close();
}

export function toggleDatePicker(
	input: HTMLInputElement,
	trigger: HTMLButtonElement,
) {
	let picker = pickers.get(input);
	if (!picker) {
		picker = new DatePicker(input, trigger, { bindTrigger: false });
		pickers.set(input, picker);
	}
	picker.toggle();
}

export function formatIsoDate(year: number, monthIndex: number, day: number) {
	const y = String(year).padStart(4, "0");
	const m = String(monthIndex + 1).padStart(2, "0");
	const d = String(day).padStart(2, "0");
	return `${y}-${m}-${d}`;
}

export function todayIsoDate(now = new Date()) {
	return formatIsoDate(now.getFullYear(), now.getMonth(), now.getDate());
}

export function addDaysIsoDate(days: number, now = new Date()) {
	const next = new Date(
		now.getFullYear(),
		now.getMonth(),
		now.getDate() + days,
	);
	return formatIsoDate(next.getFullYear(), next.getMonth(), next.getDate());
}

export function parseIsoDate(
	value: string | null | undefined,
): { year: number; month: number; day: number } | null {
	if (!value) return null;
	const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value.trim());
	if (!match) return null;
	const year = Number(match[1]);
	const month = Number(match[2]) - 1;
	const day = Number(match[3]);
	const check = new Date(year, month, day);
	if (
		check.getFullYear() !== year ||
		check.getMonth() !== month ||
		check.getDate() !== day
	) {
		return null;
	}
	return { year, month, day };
}

export interface CalendarCell {
	iso: string;
	day: number;
	outside: boolean;
}

export function buildCalendarMonth(
	year: number,
	month: number,
): CalendarCell[] {
	const firstDayOfWeek = new Date(year, month, 1).getDay();
	const daysInMonth = new Date(year, month + 1, 0).getDate();
	const prevMonthDays = new Date(year, month, 0).getDate();
	const cells: CalendarCell[] = [];

	const prevDate = new Date(year, month - 1, 1);
	for (let i = firstDayOfWeek - 1; i >= 0; i -= 1) {
		const day = prevMonthDays - i;
		cells.push({
			iso: formatIsoDate(prevDate.getFullYear(), prevDate.getMonth(), day),
			day,
			outside: true,
		});
	}

	for (let day = 1; day <= daysInMonth; day += 1) {
		cells.push({
			iso: formatIsoDate(year, month, day),
			day,
			outside: false,
		});
	}

	const nextDate = new Date(year, month + 1, 1);
	const trailing = (7 - (cells.length % 7)) % 7;
	for (let day = 1; day <= trailing; day += 1) {
		cells.push({
			iso: formatIsoDate(nextDate.getFullYear(), nextDate.getMonth(), day),
			day,
			outside: true,
		});
	}

	return cells;
}

export class DatePicker {
	declare input: HTMLInputElement;
	declare trigger: HTMLButtonElement;
	declare popover: HTMLDivElement | null;
	declare cleanupPosition: (() => void) | null;
	declare viewYear: number;
	declare viewMonth: number;
	declare _onTriggerClick: (e: MouseEvent) => void;
	declare _onDocPointerDown: (e: Event) => void;
	declare _onDocKeydown: (e: KeyboardEvent) => void;
	declare _onExternalClose: () => void;

	constructor(
		input: HTMLInputElement,
		trigger: HTMLButtonElement,
		options: { bindTrigger?: boolean } = {},
	) {
		this.input = input;
		this.trigger = trigger;
		this.popover = null;
		this.cleanupPosition = null;
		const now = new Date();
		this.viewYear = now.getFullYear();
		this.viewMonth = now.getMonth();

		this._onTriggerClick = this._handleTriggerClick.bind(this);
		this._onDocPointerDown = this._handleDocPointerDown.bind(this);
		this._onDocKeydown = this._handleDocKeydown.bind(this);
		this._onExternalClose = () => this.close();

		if (options.bindTrigger !== false) {
			this.trigger.addEventListener("click", this._onTriggerClick);
		}
	}

	get isOpen() {
		return Boolean(this.popover?.isConnected);
	}

	toggle() {
		if (this.input.disabled || this.input.readOnly) return;
		if (this.isOpen) {
			this.close();
		} else {
			this.open();
		}
	}

	_handleTriggerClick(e: MouseEvent) {
		e.preventDefault();
		e.stopPropagation();
		this.toggle();
	}

	_handleDocPointerDown(e: Event) {
		const target = e.target as Node | null;
		if (!target) return;
		if (this.popover?.contains(target) || this.trigger.contains(target)) return;
		this.close();
	}

	_handleDocKeydown(e: KeyboardEvent) {
		if (e.key !== "Escape" || !this.isOpen) return;
		e.preventDefault();
		e.stopPropagation();
		this.close(true);
	}

	open() {
		if (activePicker && activePicker !== this) {
			activePicker.close();
		}
		activePicker = this;

		const parsed = parseIsoDate(this.input.value);
		const now = new Date();
		this.viewYear = parsed ? parsed.year : now.getFullYear();
		this.viewMonth = parsed ? parsed.month : now.getMonth();

		const popover = document.createElement("div");
		popover.className = STYLES.datePicker.popover;
		popover.setAttribute("role", "dialog");
		popover.setAttribute("aria-label", "Choose date");
		popover.dataset.role = "date-picker-popover";
		const kind =
			this.input.closest<HTMLElement>("[data-kind]")?.dataset.kind || "task";
		popover.dataset.kind = kind;
		this.popover = popover;

		this._renderPopover();
		document.body.appendChild(popover);
		this.trigger.setAttribute("aria-expanded", "true");

		document.addEventListener("pointerdown", this._onDocPointerDown, true);
		document.addEventListener("keydown", this._onDocKeydown, true);
		document.addEventListener("lp:close-date-picker", this._onExternalClose);

		this.cleanupPosition = autoUpdate(this.trigger, popover, () => {
			if (!this.input.isConnected || !this.trigger.isConnected) {
				this.close();
				return;
			}
			void computePosition(this.trigger, popover, {
				placement: "bottom-end",
				strategy: "fixed",
				middleware: [offset(6), flip(), shift({ padding: 8 })],
			}).then(({ x, y }) => {
				if (!this.popover) return;
				this.popover.style.left = `${x}px`;
				this.popover.style.top = `${y}px`;
			});
		});

		const focusTarget =
			popover.querySelector<HTMLButtonElement>(
				"button[data-date][aria-pressed='true']",
			) ||
			popover.querySelector<HTMLButtonElement>(
				"button[data-date][data-today='true']",
			) ||
			popover.querySelector<HTMLButtonElement>(
				"button[data-date]:not([data-outside='true'])",
			);
		focusTarget?.focus({ preventScroll: true });
	}

	close(returnFocus = false) {
		if (activePicker === this) activePicker = null;
		this.cleanupPosition?.();
		this.cleanupPosition = null;
		this.popover?.remove();
		this.popover = null;
		this.trigger.setAttribute("aria-expanded", "false");
		document.removeEventListener("pointerdown", this._onDocPointerDown, true);
		document.removeEventListener("keydown", this._onDocKeydown, true);
		document.removeEventListener("lp:close-date-picker", this._onExternalClose);
		if (returnFocus && this.trigger.isConnected) {
			this.trigger.focus({ preventScroll: true });
		}
	}

	_selectIso(iso: string) {
		this.input.value = iso;
		this.input.dispatchEvent(new Event("input", { bubbles: true }));
		this.input.dispatchEvent(new Event("change", { bubbles: true }));
		this.close(true);
	}

	_shiftMonth(delta: number) {
		const next = new Date(this.viewYear, this.viewMonth + delta, 1);
		this.viewYear = next.getFullYear();
		this.viewMonth = next.getMonth();
		this._renderPopover();
	}

	_focusDate(iso: string) {
		const parsed = parseIsoDate(iso);
		if (!parsed) return;
		if (parsed.year !== this.viewYear || parsed.month !== this.viewMonth) {
			this.viewYear = parsed.year;
			this.viewMonth = parsed.month;
			this._renderPopover();
		}
		this.popover
			?.querySelector<HTMLButtonElement>(`button[data-date='${iso}']`)
			?.focus({ preventScroll: true });
	}

	_renderPopover() {
		const popover = this.popover;
		if (!popover) return;

		const selectedIso = this.input.value || "";
		const today = todayIsoDate();

		const header = document.createElement("div");
		header.className = "lp-dp-header";

		const prevBtn = document.createElement("button");
		prevBtn.type = "button";
		prevBtn.className = "lp-dp-nav";
		prevBtn.setAttribute("aria-label", "Previous month");
		prevBtn.title = "Previous month";
		setIcon(prevBtn.appendChild(document.createElement("span")), "left");
		prevBtn.addEventListener("click", (e) => {
			e.preventDefault();
			e.stopPropagation();
			this._shiftMonth(-1);
		});

		const pickers = document.createElement("div");
		pickers.className = "lp-dp-selects";

		const monthSelect = document.createElement("select");
		monthSelect.className = "lp-dp-select";
		monthSelect.setAttribute("aria-label", "Month");
		MONTHS.forEach((name, index) => {
			const opt = document.createElement("option");
			opt.value = String(index);
			opt.textContent = name;
			opt.selected = index === this.viewMonth;
			monthSelect.appendChild(opt);
		});
		monthSelect.addEventListener("change", () => {
			this.viewMonth = Number(monthSelect.value);
			this._renderPopover();
		});

		const yearSelect = document.createElement("select");
		yearSelect.className = "lp-dp-select";
		yearSelect.setAttribute("aria-label", "Year");
		const currentYear = new Date().getFullYear();
		const minYear = Math.min(currentYear - 100, this.viewYear - 5);
		const maxYear = Math.max(currentYear + 25, this.viewYear + 5);
		for (let y = minYear; y <= maxYear; y += 1) {
			const opt = document.createElement("option");
			opt.value = String(y);
			opt.textContent = String(y);
			opt.selected = y === this.viewYear;
			yearSelect.appendChild(opt);
		}
		yearSelect.addEventListener("change", () => {
			this.viewYear = Number(yearSelect.value);
			this._renderPopover();
		});

		pickers.append(monthSelect, yearSelect);

		const nextBtn = document.createElement("button");
		nextBtn.type = "button";
		nextBtn.className = "lp-dp-nav";
		nextBtn.setAttribute("aria-label", "Next month");
		nextBtn.title = "Next month";
		setIcon(nextBtn.appendChild(document.createElement("span")), "right");
		nextBtn.addEventListener("click", (e) => {
			e.preventDefault();
			e.stopPropagation();
			this._shiftMonth(1);
		});

		header.append(prevBtn, pickers, nextBtn);

		const weekdays = document.createElement("div");
		weekdays.className = "lp-dp-weekdays";
		weekdays.setAttribute("aria-hidden", "true");
		for (const day of WEEKDAYS) {
			const span = document.createElement("span");
			span.textContent = day;
			weekdays.appendChild(span);
		}

		const grid = document.createElement("div");
		grid.className = "lp-dp-grid";
		grid.setAttribute("role", "grid");

		for (const cell of buildCalendarMonth(this.viewYear, this.viewMonth)) {
			const btn = document.createElement("button");
			btn.type = "button";
			btn.className = "lp-dp-day";
			btn.dataset.date = cell.iso;
			if (cell.outside) btn.dataset.outside = "true";
			if (cell.iso === today) btn.dataset.today = "true";
			btn.setAttribute(
				"aria-pressed",
				cell.iso === selectedIso ? "true" : "false",
			);
			btn.textContent = String(cell.day);
			btn.addEventListener("click", (e) => {
				e.preventDefault();
				e.stopPropagation();
				this._selectIso(cell.iso);
			});
			btn.addEventListener("keydown", (e) => {
				const parsed = parseIsoDate(cell.iso);
				if (!parsed) return;
				let next: Date | null = null;
				if (e.key === "ArrowLeft") {
					next = new Date(parsed.year, parsed.month, parsed.day - 1);
				} else if (e.key === "ArrowRight") {
					next = new Date(parsed.year, parsed.month, parsed.day + 1);
				} else if (e.key === "ArrowUp") {
					next = new Date(parsed.year, parsed.month, parsed.day - 7);
				} else if (e.key === "ArrowDown") {
					next = new Date(parsed.year, parsed.month, parsed.day + 7);
				} else if (e.key === "PageUp") {
					next = new Date(parsed.year, parsed.month - 1, parsed.day);
				} else if (e.key === "PageDown") {
					next = new Date(parsed.year, parsed.month + 1, parsed.day);
				}
				if (!next) return;
				e.preventDefault();
				e.stopPropagation();
				this._focusDate(
					formatIsoDate(next.getFullYear(), next.getMonth(), next.getDate()),
				);
			});
			grid.appendChild(btn);
		}

		const footer = document.createElement("div");
		footer.className = "lp-dp-footer";

		const todayBtn = document.createElement("button");
		todayBtn.type = "button";
		todayBtn.className = "lp-dp-foot-btn";
		todayBtn.dataset.role = "dp-today";
		todayBtn.textContent = "Today";
		todayBtn.addEventListener("click", (e) => {
			e.preventDefault();
			e.stopPropagation();
			this._selectIso(todayIsoDate());
		});
		footer.appendChild(todayBtn);

		if (selectedIso) {
			const clearBtn = document.createElement("button");
			clearBtn.type = "button";
			clearBtn.className = "lp-dp-foot-btn lp-dp-foot-clear";
			clearBtn.dataset.role = "dp-clear";
			clearBtn.textContent = "Clear";
			clearBtn.addEventListener("click", (e) => {
				e.preventDefault();
				e.stopPropagation();
				this._selectIso("");
			});
			footer.appendChild(clearBtn);
		}

		popover.replaceChildren(header, weekdays, grid, footer);
	}
}

export function enhanceDateInput(input: HTMLInputElement): HTMLSpanElement {
	const wrap = document.createElement("span");
	wrap.className = STYLES.datePicker.wrap;
	wrap.dataset.role = "date-input-wrap";

	const trigger = document.createElement("button");
	trigger.type = "button";
	trigger.className = STYLES.datePicker.trigger;
	trigger.dataset.role = "date-picker-trigger";
	trigger.setAttribute("aria-label", "Choose date");
	trigger.setAttribute("aria-haspopup", "dialog");
	trigger.setAttribute("aria-expanded", "false");
	trigger.title = "Choose date";
	if (input.disabled) trigger.disabled = true;
	setIcon(trigger.appendChild(document.createElement("span")), "date");

	wrap.append(input, trigger);
	new DatePicker(input, trigger);
	return wrap;
}
