import pytest
from click.testing import CliRunner

from ean_tools.cli import main


@pytest.fixture
def run():
    runner = CliRunner()

    def _run(*args):
        return runner.invoke(main, [str(a) for a in args])

    return _run


def test_validate(run):
    ok = run("validate", "2000100100004", "4006381333931")
    assert ok.exit_code == 0
    assert "interno" in ok.output and "NO interno" in ok.output
    bad = run("validate", "2000100100004", "2000100100005")
    assert bad.exit_code == 1 and "debería ser 4" in bad.output


def test_init_and_generate(run, tmp_path):
    pytest.importorskip("PIL")
    cat = tmp_path / "catalogo.json"
    assert run("init", cat).exit_code == 0
    again = run("init", cat)
    assert again.exit_code != 0 and "ya existe" in again.output

    out = tmp_path / "salida"
    result = run("generate", "-c", cat, "-o", out, "--width-mm", 30, "--height-mm", 20, "--dpi", 203)
    assert result.exit_code == 0, result.output
    assert "11 códigos" in result.output
    assert "Atención" in result.output  # 0.25 mm module at 203 DPI
    assert len(list((out / "barcodes").glob("*.png"))) == 11


def test_generate_csv_only(run, tmp_path):
    cat = tmp_path / "c.csv"
    run("init", cat)
    out = tmp_path / "o"
    result = run("generate", "-c", cat, "-o", out, "--no-images", "--prefix", "201")
    assert result.exit_code == 0, result.output
    assert "2010100100003" in result.output
    assert not (out / "barcodes").exists()


def test_generate_bad_size(run, tmp_path, catalog_file):
    result = run("generate", "-c", catalog_file, "-o", tmp_path / "o", "--width-mm", 5)
    assert result.exit_code != 0 and "estrecho" in result.output


def test_missing_and_invalid_catalog(run, tmp_path):
    result = run("generate", "-c", tmp_path / "nada.json")
    assert result.exit_code != 0 and "ean-tools init" in result.output
    bad = tmp_path / "bad.json"
    bad.write_text('{"categories": {"01": ""}, "products": []}', encoding="utf-8")
    result = run("export", "-c", bad)
    assert result.exit_code != 0 and "falta el nombre" in result.output


def test_export(run, tmp_path, catalog_file):
    out = tmp_path / "codigos.csv"
    assert run("export", "-c", catalog_file, "-o", out).exit_code == 0
    assert out.read_text(encoding="utf-8-sig").startswith("EAN-13;")

    cat_csv = tmp_path / "catalogo.csv"
    assert run("export", "-c", catalog_file, "-o", cat_csv, "--catalog-csv").exit_code == 0
    assert cat_csv.read_text(encoding="utf-8-sig").startswith("categoria;")


def test_web_requires_json(run, tmp_path):
    result = run("web", "-c", tmp_path / "c.csv", "--no-browser")
    assert result.exit_code != 0 and ".json" in result.output
