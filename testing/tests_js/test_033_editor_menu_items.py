"""Node-backed checks for editor toolbar menu-item state."""

import textwrap


# @features editor
# @dimensions menu-active-state dropdown-rerender
def test_editor_menu_item_serializes_current_active_state(run_node):
    run_node(
        textwrap.dedent(
            r"""
            import assert from "node:assert/strict";
            import { readFileSync } from "node:fs";
            import vm from "node:vm";

            class FakeElement {
              constructor(tagName) {
                this.tagName = tagName;
                this.children = [];
                this.className = "";
                this.dataset = {};
                this.innerHTML = "";
                this.role = "";
                this.textContent = "";
                this.title = "";
              }

              appendChild(child) {
                this.children.push(child);
                return child;
              }

              get outerHTML() {
                const attributes = [
                  this.className && `class="${this.className}"`,
                  this.role && `role="${this.role}"`,
                  this.title && `title="${this.title}"`,
                  ...Object.entries(this.dataset).map(
                    ([key, value]) => `data-${key}="${value}"`,
                  ),
                ].filter(Boolean).join(" ");
                const content =
                  this.innerHTML ||
                  this.children.map((child) => child.outerHTML).join("") ||
                  this.textContent;
                return `<${this.tagName}${attributes ? ` ${attributes}` : ""}>${content}</${this.tagName}>`;
              }
            }

            const context = {
              document: {
                createElement: (tagName) => new FakeElement(tagName),
              },
              setIcon(element, name, classes = "") {
                element.className = `icon ${classes}`.trim();
                element.dataset.icon = name;
              },
              STYLES: {
                dropdown: {
                  icon: "dropdown-option-icon",
                  option: { action: "dropdown-option group" },
                },
              },
            };
            vm.createContext(context);

            let source = readFileSync(
              "src/script/elements/editor/options/menuItems.mjs",
              "utf8",
            );
            source = source
              .replace(/^import .*;\n/gm, "")
              .replace(
                /export \{[\s\S]*?\};\s*$/,
                "globalThis.ToolbarMenuItem = ToolbarMenuItem;",
              );
            vm.runInContext(source, context);

            const item = new context.ToolbarMenuItem({});
            item.init({
              icon: "underline",
              name: "underline",
              title: "Underline",
            });

            assert.match(item.html, /data-active="false"/);
            assert.doesNotMatch(item.html, /title="Underline"/);
            item.enable();
            assert.match(item.html, /data-active="true"/);
            item.disable();
            assert.match(item.html, /data-active="false"/);

            const renderedButton = new FakeElement("button");
            renderedButton.dataset.active = "false";
            item.button = renderedButton;
            item.enable();
            assert.match(item.html, /data-active="true"/);
            """
        )
    )
