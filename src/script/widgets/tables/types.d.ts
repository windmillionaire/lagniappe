import type { LoadedWidget } from "../../types/widgets.d.ts";
import type { TableEditor } from "./editor.ts";
import type { IndexTable } from "./indexTable.ts";
import type { TableSorting } from "./sorting.ts";
import type { TableVisibility } from "./visibility.ts";

/** The loader supplies lifecycle methods to the table's registered widgets. */
export interface TableWidgets {
	IndexTable?: IndexTable & LoadedWidget;
	TableEditor?: TableEditor & LoadedWidget;
	TableSorting?: TableSorting & LoadedWidget;
	TableVisibility?: TableVisibility & LoadedWidget;
}
