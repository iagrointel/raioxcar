#!/usr/bin/env python3
"""Raio-X CAR · Investigador — mapa local de satélite, só dados públicos, SEM banco.

Sobe um mapa no navegador onde você DESENHA um polígono, IMPORTA um KML/GeoJSON ou BUSCA um
lugar — e roda o X-ray observado (MapBiomas nativa/consolidada/supressão pós-2008, RL pelo bioma,
APP via hidrografia pública) + composição Sentinel-2 (hoje) × Landsat (2008). Nada de chave,
nada de Google Earth Engine, nada de PostGIS. Analisa UM perímetro por vez (o que você traz) —
a base nacional montada é o serviço, não vai aqui.

Rodar:
    pip install -r requirements.txt fastapi uvicorn
    python -m webapp.server          # abre em http://127.0.0.1:8055
"""
from __future__ import annotations
import os, sys, io, base64, webbrowser, threading
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "pipeline"))
from fastapi import FastAPI, Body, HTTPException
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from shapely.geometry import shape

import aoi_analyze

HERE = Path(__file__).parent
app = FastAPI(title="Raio-X CAR · Investigador (open data)")


def _geom_from_body(body: dict):
    g = body.get("geometry") or body
    if g.get("type") == "FeatureCollection":
        from shapely.ops import unary_union
        return unary_union([shape(f["geometry"]) for f in g["features"]])
    if g.get("type") == "Feature":
        return shape(g["geometry"])
    return shape(g)


@app.post("/api/analyze")
def analyze(body: dict = Body(...)):
    """X-ray observado de um polígono (sem banco). body: {geometry, bioma?, rivers?}."""
    try:
        geom = _geom_from_body(body)
    except Exception as e:
        raise HTTPException(400, f"geometria inválida: {e}")
    if geom.is_empty or geom.area <= 0:
        raise HTTPException(400, "polígono vazio")
    try:
        return JSONResponse(aoi_analyze.analyze(
            geom, bioma=body.get("bioma"), rivers=bool(body.get("rivers", True))))
    except Exception as e:
        raise HTTPException(502, f"falha na análise (rede/COG público): {e}")


def _png_b64(rgb) -> str:
    import numpy as np
    from PIL import Image
    a = (np.clip(rgb, 0, 1) * 255).astype("uint8") if rgb.dtype != "uint8" else rgb
    buf = io.BytesIO(); Image.fromarray(a).save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


@app.post("/api/chips")
def chips(body: dict = Body(...)):
    """Composição Sentinel-2 (hoje) × Landsat (pré-2008) para o polígono. Lento (~10-40s)."""
    import crisp_rgb as cr
    try:
        geom = _geom_from_body(body)
        grid = cr._target_grid(geom)
        out = {}
        try:
            rgb, _, _, date = cr._composite_s2(grid, cr._recent_window(180),
                                               prefer_recent=True, cloud_lt=35)
            out["hoje"] = {"png": _png_b64(rgb), "data": date}
        except Exception as e:
            out["hoje"] = {"erro": str(e)[:120]}
        try:
            rgb8, _, _ = cr._composite_landsat(grid, "2005-06-01/2008-07-21")
            out["pre2008"] = {"png": _png_b64(rgb8), "data": "2005–2008"}
        except Exception as e:
            out["pre2008"] = {"erro": str(e)[:120]}
        return JSONResponse(out)
    except Exception as e:
        raise HTTPException(502, f"falha nas composições: {e}")


app.mount("/", StaticFiles(directory=str(HERE), html=True), name="static")


def main():
    import uvicorn
    port = int(os.environ.get("PORT", "8055"))
    url = f"http://127.0.0.1:{port}"
    print(f"\n  Raio-X CAR · Investigador  →  {url}\n  (dados públicos, sem banco; Ctrl+C p/ sair)\n")
    threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    main()
