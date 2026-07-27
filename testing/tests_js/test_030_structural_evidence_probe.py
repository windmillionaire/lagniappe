"""Node-backed checks for structural-evidence browser instrumentation."""

import json

from testing.utility.structural_evidence import COMPONENT_REFRESH_INSTRUMENTATION


def test_component_refresh_instrumentation_skips_components_without_refresh(run_node):
    source = json.dumps(COMPONENT_REFRESH_INSTRUMENTATION)
    run_node(
        f"""
const instrument = eval({source});
const stats = {{ component_refreshes: {{}}, widget_reconciliations: {{}} }};
const events = [];
const passive = {{ widgets: {{ label: {{}} }} }};
const active = {{
  widgets: {{
    table: {{
      async refresh(value) {{
        if (this !== active.widgets.table) throw new Error("Widget binding changed");
        events.push(`widget:${{value}}`);
      }},
    }},
  }},
  async refresh(value) {{
    if (this !== active) throw new Error("Component binding changed");
    events.push(`component:${{value}}`);
  }},
}};

instrument({{ passive, active }}, stats);
await active.refresh("one");
await active.widgets.table.refresh("two");

if (passive.refresh !== undefined) {{
  throw new Error("A missing component refresh was replaced");
}}
if (events.join(",") !== "component:one,widget:two") {{
  throw new Error(`Wrapped refresh calls changed: ${{events}}`);
}}
if (stats.component_refreshes.active !== 1) {{
  throw new Error(`Component refresh was not counted: ${{JSON.stringify(stats)}}`);
}}
if (stats.component_refreshes.passive !== undefined) {{
  throw new Error(`Passive component was counted: ${{JSON.stringify(stats)}}`);
}}
if (stats.widget_reconciliations["active:table"] !== 1) {{
  throw new Error(`Widget refresh was not counted: ${{JSON.stringify(stats)}}`);
}}
""",
        module=True,
    )
