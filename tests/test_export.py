import csv
import io
import zipfile

import pytest

from ean_tools.catalog import iter_items
from ean_tools.export import CSV_COLUMNS, CSV_NAME, IMAGES_DIR, build_zip, generate_to_dir, results_csv
from ean_tools.images import ImageError, ImageOptions


def parse(text):
    return list(csv.reader(io.StringIO(text.lstrip("﻿")), delimiter=";"))


def test_results_csv(example_catalog):
    rows = parse(results_csv(iter_items(example_catalog)))
    assert rows[0] == CSV_COLUMNS
    assert len(rows) == 12
    assert rows[1][0] == "2000100100004"
    assert rows[1][-1] == f"{IMAGES_DIR}/EAN_2000100100004_CALC-CORTO.png"
    assert parse(results_csv(iter_items(example_catalog), with_images=False))[1][-1] == ""


def test_generate_csv_only(tmp_path, example_catalog):
    report = generate_to_dir(example_catalog, tmp_path, None)
    assert report.image_paths == []
    assert report.csv_path.read_bytes().startswith(b"\xef\xbb\xbf")
    assert not (tmp_path / IMAGES_DIR).exists()


def test_generate_with_images(tmp_path, example_catalog):
    pytest.importorskip("PIL")
    keep = tmp_path / "notas.txt"
    keep.write_text("no tocar")
    report = generate_to_dir(example_catalog, tmp_path, ImageOptions())
    assert len(report.image_paths) == len(report.items) == 11
    assert all(p.exists() for p in report.image_paths)
    assert keep.read_text() == "no tocar"
    # Regenerating is idempotent.
    again = generate_to_dir(example_catalog, tmp_path, ImageOptions())
    assert again.csv_path.read_bytes() == report.csv_path.read_bytes()


def test_zip(example_catalog):
    pytest.importorskip("PIL")
    with zipfile.ZipFile(io.BytesIO(build_zip(example_catalog))) as zf:
        names = zf.namelist()
        assert names[0] == CSV_NAME
        assert len([n for n in names if n.startswith(f"{IMAGES_DIR}/")]) == 11
        assert zf.read(CSV_NAME).startswith(b"\xef\xbb\xbf")


def test_zip_rejects_bad_size(example_catalog):
    with pytest.raises(ImageError):
        build_zip(example_catalog, ImageOptions(5, 5, 100))
