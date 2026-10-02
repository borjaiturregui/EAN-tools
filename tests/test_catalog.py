import json

import pytest

from ean_tools.catalog import (
    Catalog,
    CatalogError,
    Product,
    Variant,
    catalog_from_csv,
    catalog_from_dict,
    catalog_to_csv,
    catalog_to_dict,
    iter_items,
    load_catalog,
    make_label,
    sanitize_label,
    save_catalog,
)
from ean_tools.core import validate_ean13

from .conftest import EXAMPLE_CSV, EXAMPLE_JSON


def minimal(**product):
    data = {"categories": {"01": "Calcetines"},
            "products": [{"category": "01", "code": "001", "name": "Calcetín", **product}]}
    return data


def test_example_files_are_equivalent(example_catalog):
    assert catalog_to_dict(load_catalog(EXAMPLE_CSV)) == catalog_to_dict(example_catalog)


def test_packaged_example_is_in_sync():
    from ean_tools.cli import EXAMPLE_CATALOG

    assert json.loads(EXAMPLE_CATALOG.read_text("utf-8")) == json.loads(EXAMPLE_JSON.read_text("utf-8"))


def test_items_expand_variants(example_catalog):
    items = iter_items(example_catalog)
    assert len(items) == 1 + 3 + 4 + 1 + 2
    assert len({it.ean for it in items}) == len(items)
    assert all(validate_ean13(it.ean).internal for it in items)
    plain = items[0]
    assert (plain.variant, plain.variant_name, plain.label) == ("0000", "Sin variante", "CALC-CORTO")
    assert plain.image_name == f"EAN_{plain.ean}_CALC-CORTO.png"


def test_short_numeric_codes_are_padded():
    # Excel drops leading zeros: "01" -> 1. Re-importing must still work.
    cat = catalog_from_dict({"categories": {"1": "A"},
                             "products": [{"category": 1, "code": 7, "name": "X",
                                           "variants": [{"code": 3, "name": "M"}]}]})
    assert iter_items(cat)[0].ean[:12] == "200010070003"


def test_labels_are_generated_and_sanitized():
    cat = catalog_from_dict(minimal(label="", variants=[{"code": "0001", "name": "Talla Ñ/L"},
                                                        {"code": "0002", "label": "a b/c"}]))
    items = iter_items(cat)
    assert items[0].label == "CALCETIN-TALLA-N-L"
    assert items[1].label == "a-b-c"
    assert make_label("Bidón", "750 ml") == "BIDON-750-ML"
    assert sanitize_label("../../etc") == "etc"


@pytest.mark.parametrize(
    "data, fragment",
    [
        ({"prefix": "840", **minimal()}, "rango interno"),
        ({"categories": {"01": ""}, "products": []}, "falta el nombre"),
        ({"categories": {"001": "A"}, "products": []}, "2 dígitos"),
        (minimal(category="02"), "no existe"),
        (minimal(code="ABC"), "3 dígitos"),
        (minimal(name=""), "falta el nombre"),
        (minimal(variants=[{"code": "T001"}]), "4 dígitos"),
        (minimal(variants=[{"code": "0001"}, {"code": "1"}]), "repetido"),
        ({"format": 99, "categories": {}, "products": []}, "versión"),
        ([], "objeto JSON"),
    ],
)
def test_invalid_catalogs(data, fragment):
    with pytest.raises(CatalogError) as exc:
        catalog_from_dict(data)
    assert any(fragment in e for e in exc.value.errors), exc.value.errors


def test_duplicate_product_codes_rejected():
    data = minimal()
    data["products"].append({"category": "01", "code": "001", "name": "Otro"})
    with pytest.raises(CatalogError, match="repetido"):
        catalog_from_dict(data)


def test_all_errors_reported_at_once():
    with pytest.raises(CatalogError) as exc:
        catalog_from_dict({"prefix": "999", "categories": {"01": ""},
                           "products": [{"category": "05", "code": "x", "name": ""}]})
    assert len(exc.value.errors) >= 4


def test_iter_items_validates():
    bad = Catalog(categories={"01": "A"}, products=[Product("01", "001", "P", variants=[Variant("x")])])
    with pytest.raises(CatalogError):
        iter_items(bad)


@pytest.mark.parametrize("suffix", [".json", ".csv"])
def test_save_load_roundtrip(tmp_path, example_catalog, suffix):
    example_catalog.categories["09"] = "Sin productos aún"
    path = tmp_path / f"cat{suffix}"
    save_catalog(example_catalog, path)
    assert catalog_to_dict(load_catalog(path)) == catalog_to_dict(example_catalog)


def test_csv_file_is_excel_friendly(tmp_path, example_catalog):
    path = tmp_path / "cat.csv"
    save_catalog(example_catalog, path)
    raw = path.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")
    assert b"\r\n" in raw and b";" in raw.splitlines()[0]


def test_save_refuses_invalid_and_keeps_old_file(tmp_path, example_catalog):
    path = tmp_path / "cat.json"
    save_catalog(example_catalog, path)
    before = path.read_bytes()
    example_catalog.products[0].code = "1234"
    with pytest.raises(CatalogError):
        save_catalog(example_catalog, path)
    assert path.read_bytes() == before
    assert [p.name for p in tmp_path.iterdir()] == ["cat.json"]


def test_load_invalid_json(tmp_path):
    path = tmp_path / "cat.json"
    path.write_text("{ no es json", encoding="utf-8")
    with pytest.raises(CatalogError, match="JSON no válido"):
        load_catalog(path)


def test_csv_comma_separated_and_prefix():
    text = catalog_to_csv(load_catalog(EXAMPLE_JSON)).replace(";", ",")
    cat = catalog_from_csv(text, prefix="210")
    assert iter_items(cat)[0].ean.startswith("210")


@pytest.mark.parametrize(
    "rows, fragment",
    [
        (["01;A;001;P;;;;", "01;B;002;Q;;;;"], "dos nombres"),
        (["01;A;001;P;;;;", "01;A;001;P;;0001;M;"], "mezcla"),
        (["01;A;001;P;;;;", "01;A;001;P;;;;"], "repetido"),
        (["01;A;001;P;;;;", "01;A;001;Otro;;;;"], "dos valores"),
        (["01;A;;Sin código;;;;"], "falta el código"),
    ],
)
def test_csv_errors(rows, fragment):
    header = "categoria;nombre_categoria;producto;nombre_producto;etiqueta_producto;variante;nombre_variante;etiqueta_variante"
    with pytest.raises(CatalogError) as exc:
        catalog_from_csv("\n".join([header, *rows]))
    assert any(fragment in e for e in exc.value.errors), exc.value.errors


def test_csv_missing_columns():
    with pytest.raises(CatalogError, match="faltan columnas"):
        catalog_from_csv("a;b\n1;2\n")
