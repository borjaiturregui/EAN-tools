"""Command line interface: ``ean-tools generate | validate | export | init | web``."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import click

from . import __version__
from .catalog import CatalogError, iter_items, load_catalog, save_catalog
from .core import DEFAULT_PREFIX, validate_ean13
from .export import CSV_NAME, generate_to_dir, write_results_csv
from .images import ImageError, ImageOptions, compute_layout, pillow_available

EXAMPLE_CATALOG = Path(__file__).parent / "data" / "catalogo_ejemplo.json"
INTERNAL_NOTICE = (
    "Aviso: códigos de USO INTERNO (prefijo 2xx). No sirven para marketplaces "
    "ni para vender a través de terceros."
)

catalog_option = click.option(
    "--catalog", "-c",
    type=click.Path(dir_okay=False, path_type=Path),
    default="catalogo.json", show_default=True,
    help="Catálogo en JSON o CSV.",
)
prefix_option = click.option(
    "--prefix", default=DEFAULT_PREFIX, show_default=True,
    help="Prefijo interno (200-299). Solo se usa con catálogos CSV.",
)


def _load(path: Path, prefix: str):
    if not path.exists():
        raise click.ClickException(
            f"No existe {path}. Crea uno con: ean-tools init {path}"
        )
    try:
        return load_catalog(path, csv_prefix=prefix)
    except CatalogError as exc:
        raise click.ClickException(str(exc)) from exc


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.version_option(__version__, prog_name="ean-tools")
def main() -> None:
    """Genera y gestiona códigos EAN-13 de uso interno (prefijo 200-299)."""


@main.command()
@catalog_option
@prefix_option
@click.option("--output", "-o", type=click.Path(file_okay=False, path_type=Path),
              default="salida", show_default=True, help="Carpeta de salida.")
@click.option("--width-mm", type=float, default=40.0, show_default=True, help="Ancho de la imagen (mm).")
@click.option("--height-mm", type=float, default=25.0, show_default=True, help="Alto de la imagen (mm).")
@click.option("--dpi", type=int, default=300, show_default=True,
              help="Resolución de la impresora (203, 300, 600...).")
@click.option("--no-text", is_flag=True, help="No imprimir los dígitos bajo las barras.")
@click.option("--no-images", is_flag=True, help="Generar solo el CSV.")
def generate(catalog: Path, prefix: str, output: Path, width_mm: float, height_mm: float,
             dpi: int, no_text: bool, no_images: bool) -> None:
    """Genera el CSV y una imagen PNG por código."""
    cat = _load(catalog, prefix)
    options = None
    if not no_images:
        options = ImageOptions(width_mm, height_mm, dpi, show_text=not no_text)
        try:
            compute_layout(options)
        except ImageError as exc:
            raise click.ClickException(str(exc)) from exc
        if not pillow_available():
            raise click.ClickException(
                "Para generar imágenes instala Pillow: pip install \"ean-tools[images]\" "
                "(o usa --no-images)"
            )
    report = generate_to_dir(cat, output, options)

    for it in report.items:
        click.echo(f"  {it.ean}  {it.product_name}  {it.variant_name}")
    for w in report.warnings:
        click.secho(f"Atención: {w}", fg="yellow", err=True)
    click.echo(f"\n{len(report.items)} códigos -> {report.csv_path}")
    if report.image_paths:
        click.echo(f"Imágenes en {report.image_paths[0].parent}")
    click.echo(INTERNAL_NOTICE)


@main.command()
@click.argument("codes", nargs=-1, required=True)
def validate(codes: tuple[str, ...]) -> None:
    """Valida uno o varios EAN-13 (sale con código 1 si alguno falla)."""
    all_ok = True
    for code in codes:
        result = validate_ean13(code)
        if result:
            scope = "interno" if result.internal else "NO interno (prefijo GS1 asignado)"
            click.echo(f"OK      {result.code}  ({scope})")
        else:
            all_ok = False
            click.echo(f"ERROR   {result.code}  {result.reason}")
    sys.exit(0 if all_ok else 1)


@main.command()
@catalog_option
@prefix_option
@click.option("--output", "-o", type=click.Path(dir_okay=False, path_type=Path),
              default=CSV_NAME, show_default=True, help="Archivo CSV de salida.")
@click.option("--catalog-csv", is_flag=True,
              help="Exportar el catálogo editable (una fila por variante) en vez del listado de códigos.")
def export(catalog: Path, prefix: str, output: Path, catalog_csv: bool) -> None:
    """Exporta a CSV (separador ';' y BOM, se abre bien en Excel)."""
    cat = _load(catalog, prefix)
    if catalog_csv:
        if output.suffix.lower() != ".csv":
            raise click.ClickException("El archivo de salida debe terminar en .csv")
        save_catalog(cat, output)
    else:
        write_results_csv(iter_items(cat), output, with_images=False)
    click.echo(f"Exportado: {output}")


@main.command()
@click.argument("path", type=click.Path(dir_okay=False, path_type=Path), default="catalogo.json")
@click.option("--force", is_flag=True, help="Sobrescribir si ya existe.")
def init(path: Path, force: bool) -> None:
    """Crea un catálogo de ejemplo para empezar."""
    if path.exists() and not force:
        raise click.ClickException(f"{path} ya existe (usa --force para sobrescribir)")
    if path.suffix.lower() == ".csv":
        save_catalog(load_catalog(EXAMPLE_CATALOG), path)
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(EXAMPLE_CATALOG, path)
    click.echo(f"Catálogo de ejemplo creado: {path}")


@main.command()
@click.option("--catalog", "-c", type=click.Path(dir_okay=False, path_type=Path),
              default="catalogo.json", show_default=True,
              help="Catálogo JSON (se crea vacío si no existe).")
@click.option("--port", "-p", type=int, default=8765, show_default=True)
@click.option("--no-browser", is_flag=True, help="No abrir el navegador automáticamente.")
def web(catalog: Path, port: int, no_browser: bool) -> None:
    """Abre la interfaz web local (solo accesible desde este equipo)."""
    if catalog.suffix.lower() != ".json":
        raise click.ClickException("La interfaz web trabaja con catálogos .json")
    try:
        from .web.app import serve
    except ImportError as exc:
        raise click.ClickException(
            "Faltan dependencias de la web: pip install \"ean-tools[web]\""
        ) from exc
    serve(catalog, port=port, open_browser=not no_browser)


if __name__ == "__main__":  # pragma: no cover
    main()
