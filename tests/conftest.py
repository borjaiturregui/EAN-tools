from pathlib import Path

import pytest

from ean_tools.catalog import load_catalog

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_JSON = ROOT / "examples" / "catalogo_ejemplo.json"
EXAMPLE_CSV = ROOT / "examples" / "catalogo_ejemplo.csv"


@pytest.fixture
def example_catalog():
    return load_catalog(EXAMPLE_JSON)


@pytest.fixture
def catalog_file(tmp_path):
    path = tmp_path / "catalogo.json"
    path.write_bytes(EXAMPLE_JSON.read_bytes())
    return path
