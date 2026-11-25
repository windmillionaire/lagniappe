declare module "sortablejs" {
	export interface SortableEvent {
		item: HTMLElement;
		to: HTMLElement;
		newDraggableIndex?: number;
	}

	export interface MoveEvent {
		dragged: HTMLElement;
	}

	interface Options {
		group: { name: string; pull: boolean | "clone"; put: boolean };
		animation?: number;
		sort?: boolean;
		onAdd?(event: SortableEvent): void;
		onUpdate?(event: SortableEvent): void;
		onMove?(event: MoveEvent): boolean;
	}

	export default class Sortable {
		static create(element: HTMLElement, options: Options): Sortable;
		readonly el: HTMLElement;
		option(name: "disabled", value: boolean): void;
		destroy(): void;
	}
}
