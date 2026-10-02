"""Catalog model and JSON / CSV persistence.

A catalog holds categories, products and their variants. A product without
variants gets a single code with variant ``0000``.

JSON format (``catalogo.json``)::

    {
      "format": 1,
      "prefix": "200",
      "categories": {"01": "Calcetines"},
      "products": [
        {"category": "01", "code": "001", "name": "Calcetín básico",
         "label": "CALC-BASICO",
         "variants": [{"code": "0002", "name": "Talla S", "label": "CALC-S"}]}
      ]
    }
"""

from __future__ import annotations

import csv
import io
import json
import os
import re
import tempfile
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .core import (
    CATEGORY_LEN,
    DEFAULT_PREFIX,
    NO_VARIANT,
    PRODUCT_LEN,
    VARIANT_LEN,
    EANError,
    build_ean13,
    validate_prefix,
)

FORMAT_VERSION = 1
NO_VARIANT_NAME = "Sin variante"

# Columns of the flat catalog CSV (import / export of the catalog itself).
CATALOG_CSV_COLUMNS = [
    "categoria",
    "nombre_categoria",
    "producto",
    "nombre_producto",
    "etiqueta_producto",
    "variante",
    "nombre_variante",
    "etiqueta_variante",
]


class CatalogError(ValueError):
    """The catalog is malformed. ``errors`` lists every problem found."""

    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__("Catálogo no válido:\n- " + "\n- ".join(errors))


@dataclass
class Variant:
    code: str
    name: str = ""
    label: str = ""


@dataclass
class Product:
    category: str
    code: str
    name: str
    label: str = ""
    variants: list[Variant] = field(default_factory=list)


@dataclass
class Catalog:
    prefix: str = DEFAULT_PREFIX
    categories: dict[str, str] = field(default_factory=dict)
    products: list[Product] = field(default_factory=list)


@dataclass(frozen=True)
class Item:
    """One printable code: a product variant (or a product without variants)."""

    ean: str
    category: str
    category_name: str
    product: str
    product_name: str
    variant: str
    variant_name: str
    label: str

    @property
    def image_name(self) -> str:
        return f"EAN_{self.ean}_{self.label}.png"


# --- Normalisation -----------------------------------------------------------


def normalize_code(value: Any, length: int) -> str:
    """Trim and left-pad numeric codes ("1" -> "01"). Non-numeric values pass
    through unchanged so validation can report them."""
    text = "" if value is None else str(value).strip()
    if text.isdigit() and len(text) < length:
        text = text.zfill(length)
    return text


def make_label(*parts: str) -> str:
    """Filename-safe short label: ASCII, uppercase, words joined by '-'."""
    text = " ".join(p for p in parts if p)
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^A-Za-z0-9]+", "-", text).strip("-")
    return text.upper()


def sanitize_label(label: str) -> str:
    """Keep user labels as typed but safe as part of a file name."""
    text = unicodedata.normalize("NFKD", label).encode("ascii", "ignore").decode()
    text = re.sub(r"[^A-Za-z0-9_-]+", "-", text).strip("-")
    return text


# --- Dict conversion -----------------------------------------------------------


def catalog_from_dict(data: Any) -> Catalog:
    """Build and validate a catalog from parsed JSON. Raises CatalogError."""
    if not isinstance(data, dict):
        raise CatalogError(["el catálogo debe ser un objeto JSON"])

    errors: list[str] = []
    fmt = data.get("format", FORMAT_VERSION)
    if fmt != FORMAT_VERSION:
        errors.append(f"versión de formato no soportada: {fmt!r}")

    raw_categories = data.get("categories", {})
    if not isinstance(raw_categories, dict):
        errors.append("'categories' debe ser un objeto {código: nombre}")
        raw_categories = {}
    categories = {
        normalize_code(code, CATEGORY_LEN): str(name).strip()
        for code, name in raw_categories.items()
    }

    raw_products = data.get("products", [])
    if not isinstance(raw_products, list):
        errors.append("'products' debe ser una lista")
        raw_products = []

    products: list[Product] = []
    for i, raw in enumerate(raw_products, start=1):
        if not isinstance(raw, dict):
            errors.append(f"producto #{i}: debe ser un objeto")
            continue
        raw_variants = raw.get("variants") or []
        if not isinstance(raw_variants, list):
            errors.append(f"producto #{i}: 'variants' debe ser una lista")
            raw_variants = []
        variants = []
        for j, rv in enumerate(raw_variants, start=1):
            if not isinstance(rv, dict):
                errors.append(f"producto #{i}, variante #{j}: debe ser un objeto")
                continue
            variants.append(
                Variant(
                    code=normalize_code(rv.get("code"), VARIANT_LEN),
                    name=str(rv.get("name") or "").strip(),
                    label=str(rv.get("label") or "").strip(),
                )
            )
        products.append(
            Product(
                category=normalize_code(raw.get("category"), CATEGORY_LEN),
                code=normalize_code(raw.get("code"), PRODUCT_LEN),
                name=str(raw.get("name") or "").strip(),
                label=str(raw.get("label") or "").strip(),
                variants=variants,
            )
        )

    catalog = Catalog(
        prefix=normalize_code(data.get("prefix", DEFAULT_PREFIX), 3),
        categories=categories,
        products=products,
    )
    errors.extend(validate_catalog(catalog))
    if errors:
        raise CatalogError(errors)
    return catalog


def catalog_to_dict(catalog: Catalog) -> dict[str, Any]:
    return {
        "format": FORMAT_VERSION,
        "prefix": catalog.prefix,
        "categories": dict(sorted(catalog.categories.items())),
        "products": [
            {
                "category": p.category,
                "code": p.code,
                "name": p.name,
                "label": p.label,
                "variants": [
                    {"code": v.code, "name": v.name, "label": v.label}
                    for v in p.variants
                ],
            }
            for p in catalog.products
        ],
    }


# --- Validation ----------------------------------------------------------------


def _check_digits(value: str, length: int) -> bool:
    return len(value) == length and value.isdigit()


def validate_catalog(catalog: Catalog) -> list[str]:
    """Return every problem found (empty list = valid)."""
    errors: list[str] = []
    try:
        validate_prefix(catalog.prefix)
    except EANError as exc:
        errors.append(str(exc))

    for code, name in catalog.categories.items():
        if not _check_digits(code, CATEGORY_LEN):
            errors.append(f"categoría {code!r}: el código debe tener {CATEGORY_LEN} dígitos")
        if not name:
            errors.append(f"categoría {code!r}: falta el nombre")

    seen_products: dict[tuple[str, str], str] = {}
    for i, p in enumerate(catalog.products, start=1):
        where = f"producto #{i} ({p.name or 'sin nombre'})"
        if not p.name:
            errors.append(f"{where}: falta el nombre")
        if not _check_digits(p.category, CATEGORY_LEN):
            errors.append(f"{where}: categoría {p.category!r} debe tener {CATEGORY_LEN} dígitos")
        elif p.category not in catalog.categories:
            errors.append(f"{where}: la categoría {p.category} no existe")
        if not _check_digits(p.code, PRODUCT_LEN):
            errors.append(f"{where}: código {p.code!r} debe tener {PRODUCT_LEN} dígitos")

        key = (p.category, p.code)
        if key in seen_products:
            errors.append(
                f"{where}: código {p.category}-{p.code} repetido "
                f"(ya usado por {seen_products[key]!r})"
            )
        else:
            seen_products[key] = p.name

        seen_variants: set[str] = set()
        for j, v in enumerate(p.variants, start=1):
            vwhere = f"{where}, variante #{j} ({v.name or v.code})"
            if not _check_digits(v.code, VARIANT_LEN):
                errors.append(f"{vwhere}: código {v.code!r} debe tener {VARIANT_LEN} dígitos")
            elif v.code in seen_variants:
                errors.append(f"{vwhere}: código de variante {v.code} repetido")
            seen_variants.add(v.code)
    return errors


# --- Expansion to printable items --------------------------------------------------


def iter_items(catalog: Catalog) -> list[Item]:
    """Expand the catalog into one item per code. The catalog must be valid."""
    errors = validate_catalog(catalog)
    if errors:
        raise CatalogError(errors)

    items: list[Item] = []
    for p in catalog.products:
        cat_name = catalog.categories[p.category]
        base_label = sanitize_label(p.label) or make_label(p.name)
        if not p.variants:
            items.append(
                Item(
                    ean=build_ean13(p.category, p.code, NO_VARIANT, catalog.prefix),
                    category=p.category,
                    category_name=cat_name,
                    product=p.code,
                    product_name=p.name,
                    variant=NO_VARIANT,
                    variant_name=NO_VARIANT_NAME,
                    label=base_label,
                )
            )
            continue
        for v in p.variants:
            label = sanitize_label(v.label) or make_label(base_label, v.name or v.code)
            items.append(
                Item(
                    ean=build_ean13(p.category, p.code, v.code, catalog.prefix),
                    category=p.category,
                    category_name=cat_name,
                    product=p.code,
                    product_name=p.name,
                    variant=v.code,
                    variant_name=v.name,
                    label=label,
                )
            )
    return items


# --- Files ---------------------------------------------------------------------------


def load_catalog(path: str | os.PathLike[str], csv_prefix: str = DEFAULT_PREFIX) -> Catalog:
    """Load a catalog from ``.json`` or ``.csv`` (by extension). ``csv_prefix``
    applies only to CSV, which cannot store the prefix."""
    path = Path(path)
    if path.suffix.lower() == ".csv":
        return catalog_from_csv(path.read_text(encoding="utf-8-sig"), csv_prefix)
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise CatalogError([f"{path.name}: JSON no válido ({exc})"]) from exc
    return catalog_from_dict(data)


def save_catalog(catalog: Catalog, path: str | os.PathLike[str]) -> None:
    """Save as JSON or CSV (by extension). Atomic: never leaves a half-written file."""
    errors = validate_catalog(catalog)
    if errors:
        raise CatalogError(errors)
    path = Path(path)
    if path.suffix.lower() == ".csv":
        content = catalog_to_csv(catalog)
        encoding = "utf-8-sig"
    else:
        content = json.dumps(catalog_to_dict(catalog), indent=2, ensure_ascii=False) + "\n"
        encoding = "utf-8"
    _atomic_write(path, content, encoding)


def _atomic_write(path: Path, content: str, encoding: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding=encoding, newline="") as f:
            f.write(content)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


# --- Flat CSV for the catalog ----------------------------------------------------------


def catalog_to_csv(catalog: Catalog) -> str:
    """One row per variant. Products without variants leave 'variante' empty;
    categories without products get a row with only the category columns."""
    buf = io.StringIO()
    writer = csv.writer(buf, delimiter=";", lineterminator="\r\n")
    writer.writerow(CATALOG_CSV_COLUMNS)
    used = {p.category for p in catalog.products}
    for code, name in sorted(catalog.categories.items()):
        if code not in used:
            writer.writerow([code, name, "", "", "", "", "", ""])
    for p in catalog.products:
        head = [p.category, catalog.categories.get(p.category, ""), p.code, p.name, p.label]
        if not p.variants:
            writer.writerow(head + ["", "", ""])
        for v in p.variants:
            writer.writerow(head + [v.code, v.name, v.label])
    return buf.getvalue()


def catalog_from_csv(text: str, prefix: str = DEFAULT_PREFIX) -> Catalog:
    """Parse the flat catalog CSV (';' or ',' separated). The CSV has no room
    for the prefix, so it is passed separately."""
    text = text.lstrip("\ufeff")
    first_line = text.splitlines()[0] if text else ""
    delimiter = ";" if first_line.count(";") >= first_line.count(",") else ","
    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    missing = [c for c in CATALOG_CSV_COLUMNS if c not in (reader.fieldnames or [])]
    if missing:
        raise CatalogError([f"faltan columnas en el CSV: {', '.join(missing)}"])

    errors: list[str] = []
    categories: dict[str, str] = {}
    products: dict[tuple[str, str], dict[str, Any]] = {}
    plain: set[tuple[str, str]] = set()
    for line_no, raw in enumerate(reader, start=2):
        row = {k: (raw.get(k) or "").strip() for k in CATALOG_CSV_COLUMNS}
        if not any(row.values()):
            continue
        cat = normalize_code(row["categoria"], CATEGORY_LEN)
        if row["nombre_categoria"]:
            prev = categories.setdefault(cat, row["nombre_categoria"])
            if prev != row["nombre_categoria"]:
                errors.append(f"línea {line_no}: categoría {cat} con dos nombres distintos")
        if not row["producto"]:
            if row["nombre_producto"] or row["variante"]:
                errors.append(f"línea {line_no}: falta el código de producto")
            continue

        key = (cat, normalize_code(row["producto"], PRODUCT_LEN))
        product = products.get(key)
        if product is None:
            product = products[key] = {
                "category": cat,
                "code": key[1],
                "name": row["nombre_producto"],
                "label": row["etiqueta_producto"],
                "variants": [],
            }
        else:
            for field_name, col in (("name", "nombre_producto"), ("label", "etiqueta_producto")):
                if row[col] and row[col] != product[field_name]:
                    errors.append(
                        f"línea {line_no}: producto {cat}-{key[1]} con dos valores de {col}"
                    )

        if row["variante"]:
            product["variants"].append(
                {"code": row["variante"], "name": row["nombre_variante"],
                 "label": row["etiqueta_variante"]}
            )
        elif key in plain:
            errors.append(f"línea {line_no}: producto {cat}-{key[1]} sin variante repetido")
        else:
            plain.add(key)

    for key in plain:
        if products[key]["variants"]:
            errors.append(f"producto {key[0]}-{key[1]}: mezcla filas con y sin variante")
    if errors:
        raise CatalogError(errors)
    return catalog_from_dict(
        {
            "format": FORMAT_VERSION,
            "prefix": prefix,
            "categories": categories,
            "products": list(products.values()),
        }
    )
