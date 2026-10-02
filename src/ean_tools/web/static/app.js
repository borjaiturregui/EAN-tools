"use strict";

// State lives in the DOM; read it back with collect() before saving.
const $ = (sel, root = document) => root.querySelector(sel);
let dirty = false;

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") node.className = v;
    else if (k in node) node[k] = v;
    else node.setAttribute(k, v);
  }
  node.append(...children);
  return node;
}

function setDirty(value) {
  dirty = value;
  $("#dirty").hidden = !value;
}

function showMessages(kind, lines) {
  const box = $("#messages");
  box.replaceChildren();
  if (!lines.length) return;
  const list = el("ul");
  lines.forEach((line) => list.append(el("li", {}, line)));
  box.append(el("div", { class: `msg ${kind}` }, list));
  box.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

async function api(method, url, body) {
  const res = await fetch(url, {
    method,
    headers: body ? { "Content-Type": "application/json" } : {},
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error((data.errors || [`Error ${res.status}`]).join("\n"));
  return data;
}

// --- Categories -------------------------------------------------------------

function categoryRow(code = "", name = "") {
  const row = el("tr", {},
    el("td", {}, el("input", { class: "c-code", value: code, maxLength: 2, size: 3, inputMode: "numeric" })),
    el("td", {}, el("input", { class: "c-name", value: name })),
    el("td", {}, el("button", { type: "button", class: "link danger", title: "Quitar categoría" }, "✕")),
  );
  $("button", row).onclick = () => { row.remove(); refreshCategorySelects(); setDirty(true); };
  $(".c-code", row).onchange = refreshCategorySelects;
  $(".c-name", row).onchange = refreshCategorySelects;
  return row;
}

function categoryOptions() {
  return [...document.querySelectorAll("#categories tr")].map((r) => ({
    code: $(".c-code", r).value.trim(),
    name: $(".c-name", r).value.trim(),
  }));
}

function fillSelect(select, selected) {
  const options = categoryOptions();
  select.replaceChildren(el("option", { value: "" }, "—"));
  for (const c of options) {
    if (c.code) select.append(el("option", { value: c.code }, `${c.code} · ${c.name}`));
  }
  if (selected && !options.some((c) => c.code === selected)) {
    select.append(el("option", { value: selected }, `${selected} (no existe)`));
  }
  select.value = selected || "";
}

function refreshCategorySelects() {
  document.querySelectorAll(".p-category").forEach((s) => fillSelect(s, s.value));
}

// --- Products -----------------------------------------------------------------

function variantRow(v = {}) {
  const node = $("#variant-row").content.firstElementChild.cloneNode(true);
  $(".v-code", node).value = v.code || "";
  $(".v-name", node).value = v.name || "";
  $(".v-label", node).value = v.label || "";
  $("button", node).onclick = () => { node.remove(); setDirty(true); };
  return node;
}

function productRow(p = { variants: [] }) {
  const select = el("select", { class: "p-category" });
  const variants = el("div", { class: "variants" });
  (p.variants || []).forEach((v) => variants.append(variantRow(v)));
  const addVariant = el("button", { type: "button", class: "link" }, "+ variante");
  addVariant.onclick = () => { variants.append(variantRow()); setDirty(true); };

  const row = el("tr", {},
    el("td", {}, select),
    el("td", {}, el("input", { class: "p-code", value: p.code || "", maxLength: 3, size: 4, inputMode: "numeric" })),
    el("td", {}, el("input", { class: "p-name", value: p.name || "" })),
    el("td", {}, el("input", { class: "p-label", value: p.label || "", placeholder: "(auto)", size: 12 })),
    el("td", {}, variants, addVariant),
    el("td", {}, el("button", { type: "button", class: "link danger", title: "Quitar producto" }, "✕")),
  );
  $("td:last-child button", row).onclick = () => {
    if (confirm(`¿Quitar "${$(".p-name", row).value || "producto"}" y sus variantes?`)) {
      row.remove();
      setDirty(true);
    }
  };
  fillSelect(select, p.category);
  return row;
}

// --- Load / save ---------------------------------------------------------------

function render(catalog) {
  $("#prefix").value = catalog.prefix;
  $("#categories").replaceChildren(
    ...Object.entries(catalog.categories).map(([code, name]) => categoryRow(code, name)),
  );
  $("#products").replaceChildren(...catalog.products.map(productRow));
  setDirty(false);
}

function collect() {
  const categories = {};
  for (const c of categoryOptions()) {
    if (c.code || c.name) categories[c.code] = c.name;
  }
  const products = [...document.querySelectorAll("#products > tr")].map((r) => ({
    category: $(".p-category", r).value,
    code: $(".p-code", r).value.trim(),
    name: $(".p-name", r).value.trim(),
    label: $(".p-label", r).value.trim(),
    variants: [...r.querySelectorAll(".variant")].map((v) => ({
      code: $(".v-code", v).value.trim(),
      name: $(".v-name", v).value.trim(),
      label: $(".v-label", v).value.trim(),
    })),
  }));
  return { format: 1, prefix: $("#prefix").value.trim(), categories, products };
}

function imageQuery() {
  return new URLSearchParams({
    width_mm: $("#width").value,
    height_mm: $("#height").value,
    dpi: $("#dpi").value,
    text: $("#text").checked,
  }).toString();
}

function renderItems(items, withImages) {
  const q = imageQuery();
  $("#items").replaceChildren(...items.map((it) => el("tr", {},
    el("td", {}, el("code", {}, it.ean)),
    el("td", {}, it.category),
    el("td", {}, it.product),
    el("td", {}, `${it.variant} · ${it.variant_name}`),
    el("td", {}, it.label),
    el("td", {}, withImages
      ? el("img", { src: `/preview/${it.ean}.png?${q}`, alt: it.ean, loading: "lazy", class: "preview" })
      : "—"),
  )));
  $("#dl-zip").href = `/download/zip?${q}`;
  $("#dl-zip").hidden = !withImages;
  $("#downloads").hidden = false;
}

async function updateLayout() {
  try {
    const info = await api("GET", `/api/layout?${imageQuery()}`);
    const warn = info.warnings.length ? ` ⚠ ${info.warnings.join(" ")}` : "";
    $("#layout-info").textContent =
      `Imagen de ${info.width_px}×${info.height_px} px; barra mínima ${info.module_mm} mm.${warn}`;
    $("#layout-info").classList.toggle("warn", Boolean(warn));
    return true;
  } catch (err) {
    $("#layout-info").textContent = `⚠ ${err.message}`;
    $("#layout-info").classList.add("warn");
    return false;
  }
}

async function generate() {
  const button = $("#generate");
  button.disabled = true;
  try {
    const data = await api("PUT", "/api/catalog", collect());
    render(data.catalog);
    const sizeOk = await updateLayout();
    renderItems(data.items, window.imagesAvailable && sizeOk);
    showMessages("ok", [`Guardado. ${data.items.length} códigos generados.`]);
  } catch (err) {
    showMessages("error", err.message.split("\n"));
  } finally {
    button.disabled = false;
  }
}

async function init() {
  try {
    const data = await api("GET", "/api/catalog");
    $("#catalog-path").textContent = data.path;
    window.imagesAvailable = data.images;
    render(data.catalog);
    if (!data.images) showMessages("warn", ["Pillow no está instalado: solo se puede descargar el CSV."]);
  } catch (err) {
    showMessages("error", ["No se pudo cargar el catálogo:", ...err.message.split("\n")]);
  }
  updateLayout();
}

$("#add-category").onclick = () => { $("#categories").append(categoryRow()); setDirty(true); };
$("#add-product").onclick = () => {
  $("#products").append(productRow());
  setDirty(true);
};
$("#generate").onclick = generate;
document.querySelector("main").addEventListener("input", (e) => {
  if (e.target.closest("#categories, #products") || e.target.id === "prefix") setDirty(true);
});
["#width", "#height", "#dpi", "#text"].forEach((id) => $(id).addEventListener("change", updateLayout));
window.addEventListener("beforeunload", (e) => { if (dirty) e.preventDefault(); });

init();
