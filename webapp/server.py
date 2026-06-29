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


def _chip_b64(geom, sensor):
    """Composição → PNG, com a MESMA radiometria do renderizador institucional (crisp_rgb):
    _stretch_fixed + _punch, janela com fallback de cobertura, e o perímetro desenhado por cima."""
    import matplotlib; matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import pyproj
    from datetime import datetime
    from shapely.ops import transform as stransform
    import crisp_rgb as cr

    grid = cr._target_grid(geom)
    if sensor == "landsat":
        rgb, valid, n = cr._composite_landsat(grid, "2005-06-01/2008-07-21"); date = "2005–2008"
    else:
        rgb, valid, n, date = cr._composite_s2(grid, cr._recent_window(150),
                                               prefer_recent=True, cloud_lt=25)
        if valid < 0.85:  # cobertura baixa → alarga a janela (igual ao render())
            rgb, valid, n, date = cr._composite_s2(
                grid, "2024-06-01/%s" % datetime.now().strftime("%Y-%m-%d"))
    rgb = cr._punch(cr._stretch_fixed(rgb, sensor))           # ← a radiometria que faltava
    ux0, uy0, ux1, uy1 = grid["bounds_utm"]
    fig, ax = plt.subplots(figsize=(5, 5), dpi=130); fig.patch.set_facecolor("#0a140f")
    ax.imshow(rgb, extent=[ux0, ux1, uy0, uy1], interpolation="bilinear", origin="upper")
    to = pyproj.Transformer.from_crs(4326, grid["epsg"], always_xy=True).transform
    gp = stransform(to, geom)
    for poly in (gp.geoms if gp.geom_type.startswith("Multi") else [gp]):
        xs, ys = poly.exterior.xy
        ax.plot(xs, ys, color="#000", lw=3.2, alpha=.55); ax.plot(xs, ys, color="#ffe000", lw=1.6)
    ax.set_xlim(ux0, ux1); ax.set_ylim(uy0, uy1); ax.set_aspect("equal"); ax.axis("off")
    buf = io.BytesIO()
    plt.savefig(buf, format="png", dpi=130, bbox_inches="tight", pad_inches=0, facecolor="#0a140f")
    plt.close(fig)
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode(), date, round(valid, 3)


@app.post("/api/chips")
def chips(body: dict = Body(...)):
    """Composição Sentinel-2 (hoje) × Landsat (pré-2008) p/ o polígono, com perímetro. Lento (~15-50s)."""
    try:
        geom = _geom_from_body(body)
    except Exception as e:
        raise HTTPException(400, f"geometria inválida: {e}")
    out = {}
    for key, sensor in (("pre2008", "landsat"), ("hoje", "s2")):
        try:
            png, date, valid = _chip_b64(geom, sensor)
            out[key] = {"png": png, "data": date, "cobertura": valid}
        except Exception as e:
            out[key] = {"erro": str(e)[:140]}
    return JSONResponse(out)


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
