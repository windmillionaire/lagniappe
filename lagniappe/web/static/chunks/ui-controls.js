/*! Third-party licenses: /third-party-licenses.txt */
import { S as STYLES, s as setIcon, c as createIcon, i as iconDefinition } from './ui-resources.js?v=b8e0e957';

let controlIdCounter = 0;
const linkLabelToControl = (labelElt, control) => {
  if (labelElt.tagName !== "LABEL") return;
  if (!control.id) {
    controlIdCounter += 1;
    control.id = `lp-control-${controlIdCounter}`;
  }
  labelElt.setAttribute("for", control.id);
};
const setAttributes = (elt, attributes) => {
  if (attributes.name) elt.name = attributes.name;
  if (attributes.id) elt.id = attributes.id;
  if (attributes.value != null) elt.value = String(attributes.value);
  if (attributes.required) elt.required = true;
  if (attributes.disabled) {
    elt.classList.add("pointer-events-none", "select-none");
    elt.readOnly = true;
    elt.tabIndex = -1;
    elt.disabled = true;
  }
  for (const [k, v] of Object.entries(attributes.data || {})) {
    if (v != null) elt.dataset[k] = String(v);
  }
};
function label(attributes) {
  const {
    label: label2,
    icon: icon2,
    role = "label",
    tag = "label",
    styles = {}
  } = attributes;
  const labelElt = document.createElement(tag);
  labelElt.className = `${styles.label ?? STYLES.form.elementLabel}`;
  const container = labelElt.appendChild(div({ role }));
  container.className = styles.container ?? "flex flex-row flex-wrap items-center gap-1";
  if (icon2) {
    const iconElt = container.appendChild(document.createElement("span"));
    setIcon(iconElt, icon2, styles.icon ?? STYLES.icon.default);
    const span2 = container.appendChild(document.createElement("span"));
    span2.textContent = label2 == null ? null : String(label2);
  } else {
    const span2 = container.appendChild(document.createElement("span"));
    span2.textContent = label2 == null ? null : String(label2);
  }
  return labelElt;
}
function input(attributes) {
  const { type = "text", placeholder, styles = {} } = attributes;
  const elt = document.createElement("input");
  elt.type = type;
  elt.autocomplete = "off";
  elt.setAttribute("data-1p-ignore", "");
  if (placeholder) {
    elt.placeholder = placeholder;
    elt.dataset.placeholder = placeholder;
  }
  elt.className = styles.input ?? STYLES.input;
  attributes.name = attributes.name ?? attributes.id;
  attributes.data = {
    kind: attributes.kind,
    index: attributes.index,
    ...attributes.data
  };
  setAttributes(elt, attributes);
  if (["text", "email", "url", "tel"].includes(type)) {
    elt.pattern = ".*";
  } else if (type === "number") {
    elt.step = "any";
  }
  if (attributes.label) {
    const container = label(attributes);
    container.appendChild(elt);
    container.classList.add("flex-col");
    linkLabelToControl(container, elt);
    return container;
  }
  return elt;
}
function textarea(attributes) {
  const { rows = 3, placeholder, styles = {} } = attributes;
  const elt = document.createElement("textarea");
  elt.rows = rows;
  if (placeholder) elt.placeholder = placeholder;
  elt.className = styles.textarea ?? STYLES.textarea;
  setAttributes(elt, attributes);
  if (attributes.label) {
    const container = label(attributes);
    container.appendChild(elt);
    container.classList.add("flex-col");
    linkLabelToControl(container, elt);
    return container;
  }
  return elt;
}
const checkbox = (attributes) => {
  const { checked = false, styles = {}, visible = true } = attributes;
  styles.label ??= STYLES.checkbox.label;
  let element = null;
  const wrapper = document.createElement("div");
  wrapper.className = styles.container ?? STYLES.checkbox.container;
  const elt = wrapper.appendChild(document.createElement("input"));
  elt.type = "checkbox";
  elt.checked = checked;
  elt.className = styles.checkbox ?? STYLES.checkbox.default;
  setAttributes(elt, attributes);
  const icon2 = wrapper.appendChild(document.createElement("span"));
  setIcon(icon2, "check", styles.icon ?? STYLES.checkbox.icon);
  if (attributes.label) {
    element = document.createElement("label");
    element.dataset.role = "label";
    const text = document.createElement("span");
    text.textContent = attributes.label;
    element.className = styles.label ?? STYLES.checkbox.label;
    wrapper.classList.add("order-first");
    element.append(wrapper, text);
  } else {
    element = wrapper;
  }
  if (!visible) element.dataset.visible = "false";
  return element;
};
const radio = (attributes) => {
  const { checked = false, styles = {} } = attributes;
  const elt = document.createElement("input");
  elt.type = "radio";
  elt.checked = checked;
  elt.className = styles.radio ?? STYLES.radio.default;
  setAttributes(elt, attributes);
  const labelElt = document.createElement("label");
  labelElt.dataset.role = "label";
  const text = document.createElement("span");
  text.textContent = attributes.label == null ? null : String(attributes.label);
  labelElt.className = styles.label ?? STYLES.radio.label;
  elt.classList.add("order-first");
  labelElt.append(elt, text);
  return labelElt;
};
const select = (attributes) => {
  const { placeholder, options = [], styles = {} } = attributes;
  const container = document.createElement("div");
  container.className = STYLES.select.wrapper;
  if (attributes.kind) container.dataset.kind = attributes.kind;
  const elt = container.appendChild(document.createElement("select"));
  elt.className = styles.select ?? STYLES.select.default;
  setAttributes(elt, attributes);
  if (attributes.name) elt.name = attributes.name;
  if (attributes.id) elt.id = attributes.id;
  if (attributes.required) elt.required = true;
  if (placeholder) {
    elt.dataset.placeholder = placeholder;
    const pl = elt.appendChild(document.createElement("option"));
    pl.textContent = placeholder;
    pl.value = "";
    pl.selected = true;
    pl.hidden = true;
  }
  for (const o of options) {
    const opt = elt.appendChild(document.createElement("option"));
    opt.value = o.value;
    opt.textContent = o.label;
    opt.dataset.details = JSON.stringify(
      o.details ?? { name: o.label, id: o.value }
    );
    if (o.selected) opt.selected = true;
  }
  const icon2 = container.appendChild(document.createElement("span"));
  const iconType = attributes.selectIcon || (options.length ? "dropdown" : "search");
  setIcon(icon2, iconType, STYLES.select.icon);
  container.setAttribute("lp-select", "");
  if (attributes.label) {
    const labelElt = label(attributes);
    labelElt.appendChild(container);
    labelElt.classList.add("flex-col");
    linkLabelToControl(labelElt, elt);
    return labelElt;
  }
  return container;
};
const badge = (attributes) => {
  const { icon: icon2, text, kind, styles = {} } = attributes;
  const badge2 = document.createElement("div");
  badge2.className = styles.badge ?? STYLES.badge.default;
  badge2.dataset.kind = kind;
  const badgeIcon = badge2.appendChild(document.createElement("span"));
  setIcon(badgeIcon, icon2, styles.icon ?? STYLES.badge.icon);
  const name = badge2.appendChild(document.createElement("span"));
  name.textContent = text ?? null;
  name.className = styles.text ?? "text-kind-default";
  return badge2;
};
const toggle = (attributes) => {
  const { icon: icon2, styles = {} } = attributes;
  const toggle2 = document.createElement("button");
  toggle2.className = styles.container ?? STYLES.toggle.container;
  const iconElt = toggle2.appendChild(document.createElement("span"));
  setIcon(iconElt, icon2, styles.icon ?? "");
  setAttributes(toggle2, attributes);
  return toggle2;
};
const loading = () => {
  const wrapper = document.createElement("div");
  wrapper.className = STYLES.loading.wrapper;
  const pulse = "h-4 bg-base-light rounded-full animate-pulse";
  const delays = [0, 200, 400];
  wrapper.innerHTML = delays.map(
    (d) => `<div class="${pulse}${d ? ` [animation-delay:${d}ms]` : ""}"></div>`
  ).join("");
  return wrapper;
};
const icon$1 = (attributes) => {
  const { icon: icon2, kind = null, role = null, style = null } = attributes;
  const elt = document.createElement("span");
  if (kind) elt.dataset.kind = kind;
  if (role) elt.dataset.role = role;
  setIcon(elt, icon2, `${style ?? ""} text-kind-default`.trim());
  return elt;
};
const div = (attributes) => {
  const { kind = null, role = null, style = null, data = {} } = attributes;
  const elt = document.createElement("div");
  if (kind) elt.dataset.kind = kind;
  if (role) elt.dataset.role = role;
  if (style) elt.className = style;
  for (const [k, v] of Object.entries(data)) {
    if (v != null) elt.dataset[k] = String(v);
  }
  return elt;
};
const error = (message) => {
  const error2 = document.createElement("div");
  error2.className = STYLES.message;
  error2.dataset.role = "error";
  error2.dataset.visible = "false";
  error2.dataset.kind = "error";
  if (message) error2.textContent = message;
  return error2;
};
const span = (attributes) => {
  const { text = "", style = null, data = {} } = attributes;
  const span2 = document.createElement("span");
  span2.textContent = text;
  if (style) span2.className = style;
  for (const [k, v] of Object.entries(data)) {
    if (v != null) span2.dataset[k] = String(v);
  }
  return span2;
};
const primitives = {
  checkbox,
  input,
  radio,
  textarea,
  select,
  label,
  badge,
  toggle,
  loading,
  icon: icon$1,
  div,
  error,
  span
};

const ROUTES = {
  task: "pages",
  model: "projects",
  project: "projects",
  page: "pages",
  category: "categories",
  form: "forms"
};
function entityParent(value) {
  if (!value || typeof value !== "object") return null;
  return {
    id: "id" in value && typeof value.id === "string" ? value.id : void 0,
    kind: "kind" in value && typeof value.kind === "string" ? value.kind : void 0,
    name: "name" in value && typeof value.name === "string" ? value.name : void 0
  };
}
const date = (date2) => {
  if (!date2) return "";
  if (typeof date2 === "string") {
    date2 = /* @__PURE__ */ new Date(`${date2}T00:00:00`);
  }
  return date2.toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric"
  });
};
const time = (timeValue) => {
  if (!timeValue) return null;
  const [hours, minutes] = timeValue.split(":").map(Number);
  const period = hours >= 12 ? "PM" : "AM";
  const displayHours = hours === 0 ? 12 : hours > 12 ? hours - 12 : hours;
  return `${displayHours}:${minutes.toString().padStart(2, "0")} ${period}`;
};
const tel = (telValue) => {
  if (!telValue) return null;
  return telValue.replace(/(\d{3})(\d{3})(\d{4})/, "($1) $2-$3");
};
const url = (data) => {
  let url2 = null;
  const parent = entityParent(data.parent);
  if (data.kind === "model" && parent) {
    url2 = new URL(
      `projects/${parent.id}/status/${data.id}`,
      window.location.origin
    );
    url2.searchParams.set("completed", "false");
  } else if (data.kind === "task" && parent) {
    url2 = new URL(
      `${ROUTES[parent.kind ?? ""]}/${parent.id}`,
      window.location.origin
    );
    url2.searchParams.set("task", String(data.id));
  } else if (data.kind === "user") {
    url2 = new URL(`pages/${data.id}`, window.location.origin);
  } else if (data.kind === "group") {
    url2 = new URL("users/index", window.location.origin);
    url2.searchParams.set("group", String(data.id));
  } else {
    url2 = new URL(
      `${ROUTES[data.kind || data.index || ""]}/${data.id}`,
      window.location.origin
    );
  }
  return url2;
};
const email = (email2) => {
  const emailElement = document.createElement("a");
  emailElement.href = `mailto:${email2}`;
  emailElement.textContent = email2;
  emailElement.className = `${STYLES.link.emphasized}`;
  return emailElement;
};
const icon = (data) => {
  if (data.icon || data.kind) {
    const iconElement = document.createElement("span");
    iconElement.dataset.kind = data.kind || "default";
    setIcon(iconElement, data.icon || data.kind, "text-kind-default");
    return iconElement;
  }
  return null;
};
const iconLabel = ({
  icon: iconName,
  kind = null,
  content,
  classes = "",
  iconClasses = ""
}) => {
  const container = document.createElement("span");
  container.className = `${STYLES.iconLabel.wrapper} ${classes}`.trim();
  if (iconName && iconDefinition(iconName)) {
    const iconElement = document.createElement("span");
    if (kind) iconElement.dataset.kind = kind;
    setIcon(
      iconElement,
      iconName,
      `${STYLES.iconLabel.icon} ${iconClasses}`.trim()
    );
    container.appendChild(iconElement);
  }
  if (typeof content === "string") {
    container.appendChild(document.createTextNode(content));
  } else if (content) {
    container.appendChild(content);
  }
  return container;
};
const name = (data) => {
  const kind = data.kind || data.index || data.type;
  const container = document.createElement("span");
  container.className = STYLES.entity.name.wrapper;
  const name2 = document.createElement(data.link ? "a" : "span");
  name2.dataset.kind = String(kind);
  name2.textContent = data.name ?? null;
  if (name2.tagName === "A") {
    name2.setAttribute("href", url(data).href);
    name2.className = `${STYLES.link.emphasized}`;
  } else {
    name2.className = "text-kind-default font-semibold";
  }
  const parentDetails = entityParent(data.parent);
  if (parentDetails) {
    const parent = container.appendChild(document.createElement("span"));
    parent.dataset.kind = String(parentDetails.kind);
    parent.className = `text-kind-default font-medium ${STYLES.entity.name.parent}`;
    const parentName = parent.appendChild(document.createElement("span"));
    parentName.textContent = parentDetails.name ?? null;
    const separator = parent.appendChild(document.createElement("span"));
    separator.setAttribute("aria-hidden", "true");
    separator.className = STYLES.entity.name.separator;
    separator.textContent = "/";
    container.appendChild(document.createElement("wbr"));
  }
  container.appendChild(name2);
  return container;
};
const text = (data) => {
  const { kind = "default", text: text2 } = data;
  const textElement = document.createElement("span");
  textElement.dataset.kind = kind;
  textElement.className = "text-kind-default";
  textElement.textContent = text2 ?? null;
  return textElement;
};
const working = (button, newText) => {
  const iconWrapper = document.createElement("span");
  iconWrapper.dataset.role = "icon";
  iconWrapper.dataset.visible = "true";
  iconWrapper.appendChild(createIcon("spinner"));
  const textElement = document.createElement("span");
  textElement.dataset.role = "text";
  textElement.textContent = newText;
  button.replaceChildren(iconWrapper, textElement);
};
const formatting = {
  date,
  time,
  tel,
  url,
  email,
  icon,
  iconLabel,
  name,
  text,
  working
};

const buttonContents = (icon, text) => {
  if (icon && text) {
    return formatting.iconLabel({
      icon,
      content: text
    });
  }
  if (icon) {
    const iconElt = document.createElement("span");
    setIcon(iconElt, icon);
    return iconElt;
  }
  const textElt = document.createElement("span");
  textElt.textContent = text;
  return textElt;
};
const submit = (attributes) => {
  return button({
    type: "submit",
    style: STYLES.button.submit,
    ...attributes
  });
};
const button = (attributes) => {
  const {
    text = "",
    type = "button",
    icon = null,
    style = STYLES.button.submit,
    kind = null,
    role = null,
    data = {},
    classes = []
  } = attributes;
  const buttonElt = document.createElement("button");
  buttonElt.type = type;
  buttonElt.className = style;
  if (icon || text) buttonElt.appendChild(buttonContents(icon, text));
  if (kind) buttonElt.dataset.kind = kind;
  if (role) buttonElt.dataset.role = role;
  for (const [k, v] of Object.entries(data)) {
    if (v != null) buttonElt.dataset[k] = String(v);
  }
  if (classes.length > 0) {
    buttonElt.classList.add(...classes);
  }
  return buttonElt;
};
const active = (attributes) => {
  const buttonElt = attributes.existingButton || button(attributes);
  const {
    defaultText = attributes.defaultText || attributes.text || buttonElt.textContent,
    processingText = attributes.processingText || false,
    processingIcon = attributes.processingIcon || "spinner",
    completedText = attributes.completedText || attributes.text || buttonElt.textContent,
    completedIcon = attributes.completedIcon || attributes.icon
  } = attributes;
  const setState = (icon, text) => {
    let textElt = buttonElt.querySelector("[data-role='text']");
    if (!textElt) {
      textElt = document.createElement("span");
      textElt.dataset.role = "text";
      buttonElt.replaceChildren(textElt);
    }
    textElt.textContent = text;
    let iconElt = buttonElt.querySelector("[data-role='icon']");
    if (!iconElt) {
      iconElt = document.createElement("span");
      iconElt.dataset.role = "icon";
      iconElt.setAttribute("aria-hidden", "true");
      buttonElt.prepend(iconElt);
    }
    if (icon) {
      iconElt.replaceChildren(createIcon(icon));
      iconElt.dataset.visible = "true";
    } else {
      iconElt.replaceChildren();
      iconElt.dataset.visible = "false";
    }
  };
  setState(attributes.icon, defaultText);
  return {
    element: buttonElt,
    activate: (activeText = null, kind = null) => {
      buttonElt.disabled = true;
      const text = activeText || processingText || defaultText;
      if (kind) buttonElt.dataset.kind = kind;
      setState(processingIcon, text);
    },
    deactivate: (inactiveText = null, kind = null) => {
      buttonElt.disabled = false;
      const text = inactiveText || completedText || defaultText;
      if (kind) buttonElt.dataset.kind = kind;
      setState(completedIcon, text);
    }
  };
};
const buttons = {
  default: button,
  submit,
  active
};

export { buttons as b, formatting as f, primitives as p };
