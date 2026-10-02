import io
import json
import zipfile

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("PIL")

from fastapi.testclient import TestClient  # noqa: E402

from ean_tools.catalog import load_catalog  # noqa: E402
from ean_tools.web.app import create_app  # noqa: E402


@pytest.fixture
def client(catalog_file):
    return TestClient(create_app(catalog_file), base_url="http://127.0.0.1:8765")


def test_index_and_static(client):
    assert "ean-tools" in client.get("/").text
    assert client.get("/static/app.js").status_code == 200
    assert client.get("/static/..%2F..%2Fapp.py").status_code == 404


def test_rejects_foreign_host(catalog_file):
    evil = TestClient(create_app(catalog_file), base_url="http://evil.example")
    assert evil.get("/api/catalog").status_code == 400


def test_get_catalog(client):
    data = client.get("/api/catalog").json()
    assert data["catalog"]["prefix"] == "200"
    assert data["images"] is True


def test_missing_catalog_starts_empty(tmp_path):
    client = TestClient(create_app(tmp_path / "nuevo.json"), base_url="http://127.0.0.1")
    assert client.get("/api/catalog").json()["catalog"]["products"] == []
    assert client.get("/api/items").json() == {"items": []}


def test_put_saves_and_returns_items(client, catalog_file):
    data = client.get("/api/catalog").json()["catalog"]
    data["products"].append({"category": "3", "code": "2", "name": "Gorra invierno", "variants": []})
    res = client.put("/api/catalog", json=data)
    assert res.status_code == 200, res.text
    assert res.json()["items"][-1]["ean"] == "2000300200009"
    saved = load_catalog(catalog_file)
    assert saved.products[-1].category == "03"


def test_put_invalid_keeps_file(client, catalog_file):
    before = catalog_file.read_bytes()
    res = client.put("/api/catalog", json={"categories": {"01": ""}, "products": []})
    assert res.status_code == 422
    assert any("falta el nombre" in e for e in res.json()["errors"])
    assert catalog_file.read_bytes() == before


def test_put_requires_json_content_type(client, catalog_file):
    before = catalog_file.read_bytes()
    body = json.dumps({"categories": {}, "products": []})
    res = client.put("/api/catalog", content=body, headers={"Content-Type": "text/plain"})
    assert res.status_code == 415
    assert catalog_file.read_bytes() == before


def test_layout(client):
    assert client.get("/api/layout").json()["module_mm"] == 0.339
    res = client.get("/api/layout", params={"width_mm": 5})
    assert res.status_code == 422 and "estrecho" in res.json()["errors"][0]


def test_downloads(client):
    csv_res = client.get("/download/csv")
    assert csv_res.content.startswith(b"\xef\xbb\xbfEAN-13;")
    assert "attachment" in csv_res.headers["content-disposition"]

    zip_res = client.get("/download/zip", params={"width_mm": 50, "height_mm": 30, "dpi": 600})
    assert zip_res.status_code == 200
    with zipfile.ZipFile(io.BytesIO(zip_res.content)) as zf:
        assert len(zf.namelist()) == 12


def test_preview(client):
    res = client.get("/preview/2000100100004.png")
    assert res.status_code == 200 and res.content.startswith(b"\x89PNG")
    assert client.get("/preview/4006381333931.png").status_code == 404
