"""Local web interface. A thin layer over catalog/export: no logic of its own.

Listens only on 127.0.0.1 and rejects requests whose Host header is not
local (protection against DNS rebinding from a malicious web page).
"""

from __future__ import annotations

import threading
import webbrowser
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response

from ..catalog import (
    Catalog,
    CatalogError,
    catalog_from_dict,
    catalog_to_dict,
    iter_items,
    load_catalog,
    save_catalog,
)
from ..export import CSV_NAME, build_zip, results_csv
from ..images import ImageError, ImageOptions, compute_layout, pillow_available

HOST = "127.0.0.1"
STATIC_DIR = Path(__file__).parent / "static"


def create_app(catalog_path: str | Path) -> FastAPI:
    catalog_path = Path(catalog_path)
    app = FastAPI(title="ean-tools", docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost"])

    def current() -> Catalog:
        if not catalog_path.exists():
            return Catalog()
        try:
            return load_catalog(catalog_path)
        except CatalogError as exc:
            raise HTTPException(422, {"errors": exc.errors}) from exc

    def image_options(width_mm: float, height_mm: float, dpi: int, text: bool) -> ImageOptions:
        options = ImageOptions(width_mm, height_mm, dpi, show_text=text)
        try:
            compute_layout(options)
        except ImageError as exc:
            raise HTTPException(422, {"errors": [str(exc)]}) from exc
        return options

    @app.exception_handler(HTTPException)
    async def _errors(_: Request, exc: HTTPException) -> JSONResponse:
        detail = exc.detail if isinstance(exc.detail, dict) else {"errors": [str(exc.detail)]}
        return JSONResponse(detail, status_code=exc.status_code)

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/static/{name}")
    def static(name: str) -> FileResponse:
        path = (STATIC_DIR / name).resolve()
        if path.parent != STATIC_DIR.resolve() or not path.is_file():
            raise HTTPException(404, "no encontrado")
        return FileResponse(path)

    @app.get("/api/catalog")
    def get_catalog() -> dict[str, Any]:
        return {
            "path": str(catalog_path.resolve()),
            "catalog": catalog_to_dict(current()),
            "images": pillow_available(),
        }

    @app.put("/api/catalog")
    async def put_catalog(request: Request) -> dict[str, Any]:
        # Requiring JSON forces a CORS preflight for cross-site requests,
        # so another web page cannot overwrite the catalog.
        if request.headers.get("content-type", "").split(";")[0].strip() != "application/json":
            raise HTTPException(415, "se esperaba application/json")
        try:
            data = await request.json()
        except ValueError as exc:
            raise HTTPException(400, "JSON no válido") from exc
        try:
            catalog = catalog_from_dict(data)
            save_catalog(catalog, catalog_path)
        except CatalogError as exc:
            raise HTTPException(422, {"errors": exc.errors}) from exc
        return {"catalog": catalog_to_dict(catalog), "items": _items(catalog)}

    @app.get("/api/items")
    def get_items() -> dict[str, Any]:
        return {"items": _items(current())}

    @app.get("/api/layout")
    def layout(
        width_mm: float = Query(40.0), height_mm: float = Query(25.0),
        dpi: int = Query(300), text: bool = Query(True),
    ) -> dict[str, Any]:
        result = compute_layout(image_options(width_mm, height_mm, dpi, text))
        return {"width_px": result.width_px, "height_px": result.height_px,
                "module_mm": round(result.module_mm, 3), "warnings": result.warnings}

    @app.get("/download/csv")
    def download_csv() -> Response:
        content = results_csv(iter_items(current()), with_images=False)
        return Response(
            content.encode("utf-8-sig"),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{CSV_NAME}"'},
        )

    @app.get("/download/zip")
    def download_zip(
        width_mm: float = Query(40.0), height_mm: float = Query(25.0),
        dpi: int = Query(300), text: bool = Query(True),
    ) -> Response:
        if not pillow_available():
            raise HTTPException(503, "Pillow no está instalado: pip install \"ean-tools[images]\"")
        options = image_options(width_mm, height_mm, dpi, text)
        return Response(
            build_zip(current(), options),
            media_type="application/zip",
            headers={"Content-Disposition": 'attachment; filename="codigos_ean.zip"'},
        )

    @app.get("/preview/{ean}.png")
    def preview(
        ean: str, width_mm: float = Query(40.0), height_mm: float = Query(25.0),
        dpi: int = Query(300), text: bool = Query(True),
    ) -> Response:
        from ..images import png_bytes

        if not pillow_available():
            raise HTTPException(503, "Pillow no está instalado")
        if ean not in {it.ean for it in iter_items(current())}:
            raise HTTPException(404, "código no está en el catálogo")
        return Response(png_bytes(ean, image_options(width_mm, height_mm, dpi, text)),
                        media_type="image/png")

    return app


def _items(catalog: Catalog) -> list[dict[str, str]]:
    return [
        {
            "ean": it.ean,
            "category": it.category_name,
            "product": it.product_name,
            "variant": it.variant,
            "variant_name": it.variant_name,
            "label": it.label,
            "image": it.image_name,
        }
        for it in iter_items(catalog)
    ]


def serve(catalog_path: str | Path, port: int = 8765, open_browser: bool = True) -> None:
    import uvicorn

    url = f"http://{HOST}:{port}/"
    print(f"ean-tools web en {url}  (catálogo: {Path(catalog_path).resolve()})")
    print("Ctrl+C para salir.")
    if open_browser:
        threading.Timer(1.0, webbrowser.open, args=(url,)).start()
    uvicorn.run(create_app(catalog_path), host=HOST, port=port, log_level="warning")
