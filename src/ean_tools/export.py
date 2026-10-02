"""Output generation: Excel-friendly CSV, PNG images and ZIP bundle.

Shared by the CLI and the web interface so both produce identical files.
"""

from __future__ import annotations

import csv
import io
import os
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from .catalog import Catalog, Item, iter_items
from .images import ImageOptions, compute_layout, png_bytes

CSV_NAME = "productos_ean.csv"
IMAGES_DIR = "barcodes"
CSV_COLUMNS = [
    "EAN-13",
    "Categoria",
    "Producto",
    "Variante_Codigo",
    "Variante_Descripcion",
    "Etiqueta",
    "Imagen",
]


@dataclass
class GenerationReport:
    items: list[Item]
    csv_path: Path | None = None
    image_paths: list[Path] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def results_csv(items: list[Item], with_images: bool = True) -> str:
    """CSV with ';' separator (Excel in Spanish locale). Encode with
    ``utf-8-sig`` so Excel detects UTF-8 (see write_results_csv)."""
    buf = io.StringIO()
    writer = csv.writer(buf, delimiter=";", lineterminator="\r\n")
    writer.writerow(CSV_COLUMNS)
    for it in items:
        image = f"{IMAGES_DIR}/{it.image_name}" if with_images else ""
        writer.writerow(
            [it.ean, it.category_name, it.product_name, it.variant,
             it.variant_name, it.label, image]
        )
    return buf.getvalue()


def write_results_csv(items: list[Item], path: str | os.PathLike[str], with_images: bool = True) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(results_csv(items, with_images), encoding="utf-8-sig", newline="")
    return path


def generate_to_dir(
    catalog: Catalog,
    output_dir: str | os.PathLike[str],
    image_options: ImageOptions | None = ImageOptions(),
) -> GenerationReport:
    """Write the CSV and (unless image_options is None) one PNG per code.

    Existing files with the same name are overwritten; nothing else in the
    folder is touched.
    """
    output_dir = Path(output_dir)
    items = iter_items(catalog)
    report = GenerationReport(items=items)
    if image_options is not None:
        report.warnings.extend(compute_layout(image_options).warnings)
        images_dir = output_dir / IMAGES_DIR
        images_dir.mkdir(parents=True, exist_ok=True)
        for it in items:
            path = images_dir / it.image_name
            path.write_bytes(png_bytes(it.ean, image_options))
            report.image_paths.append(path)
    report.csv_path = write_results_csv(
        items, output_dir / CSV_NAME, with_images=image_options is not None
    )
    return report


def build_zip(catalog: Catalog, image_options: ImageOptions = ImageOptions()) -> bytes:
    """In-memory ZIP with the CSV and every PNG (used by the web download)."""
    items = iter_items(catalog)
    compute_layout(image_options)  # fail early on impossible sizes
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(CSV_NAME, results_csv(items).encode("utf-8-sig"))
        for it in items:
            zf.writestr(f"{IMAGES_DIR}/{it.image_name}", png_bytes(it.ean, image_options))
    return buf.getvalue()
