#!/usr/bin/env python3
"""MapBiomas cross-confirmation per CAR (Collection 9, public COGs on GCS).
Windowed /vsicurl reads — no full download. Confirms nativa/consolidada/água and
tests whether 'área consolidada' really existed before 22/07/2008 (uses the 2008 layer)."""
from __future__ import annotations
import os, json, subprocess
import numpy as np

os.environ.setdefault("GDAL_DISABLE_READDIR_ON_OPEN", "EMPTY_DIR")
os.environ.setdefault("CPL_VSIL_CURL_ALLOWED_EXTENSIONS", ".tif")
import rasterio
from rasterio.mask import mask as rmask
from shapely.geometry import shape

BASE = ("/vsicurl/https://storage.googleapis.com/mapbiomas-public/initiatives/"
        "brasil/collection_9/lclu/coverage/brasil_coverage_{year}.tif")

# MapBiomas Collection 9 class groups
NATIVA = {1, 3, 4, 5, 6, 49, 10, 11, 12, 32, 29, 50, 13}
CONSOL = {14, 15, 18, 19, 39, 20, 40, 62, 41, 36, 46, 47, 35, 48, 9, 21}
AGUA = {26, 33, 31}
GROUP = {**{c: "nativa" for c in NATIVA}, **{c: "consolidada" for c in CONSOL},
         **{c: "agua" for c in AGUA}}

def _geom(cod, dsn):
    gj = subprocess.run(["psql", dsn, "-tAc",
        f"SELECT ST_AsGeoJSON(geom) FROM car_area_imovel WHERE cod_imovel='{cod}' LIMIT 1"],
        capture_output=True, text=True).stdout.strip()
    if not gj:
        raise ValueError(f"sem geom para {cod}")
    return shape(json.loads(gj))

def _fractions(geom, year):
    with rasterio.open(BASE.format(year=year)) as src:
        out, _ = rmask(src, [geom.__geo_interface__], crop=True)
    a = out[0]; a = a[a > 0]
    if a.size == 0:
        return {}, 0.0
    px_ha = 0.09  # 30 m pixel ≈ 0.09 ha
    g = {"nativa": 0, "consolidada": 0, "agua": 0, "outros": 0}
    vals, cnts = np.unique(a, return_counts=True)
    for v, c in zip(vals, cnts):
        g[GROUP.get(int(v), "outros")] += int(c)
    tot = sum(g.values())
    frac = {k: round(100 * v / tot, 1) for k, v in g.items()}
    return frac, round(a.size * px_ha, 1)

def cross(cod, dsn, years=(2008, 2023)) -> dict:
    geom = _geom(cod, dsn)
    out = {"anos": {}}
    for y in years:
        frac, ha = _fractions(geom, y)
        out["anos"][y] = {"frac_pct": frac, "area_ha": ha}
    y0, y1 = years[0], years[-1]
    c0 = out["anos"][y0]["frac_pct"].get("consolidada", 0)
    c1 = out["anos"][y1]["frac_pct"].get("consolidada", 0)
    n1 = out["anos"][y1]["frac_pct"].get("nativa", 0)
    area = out["anos"][y1]["area_ha"]
    out["nativa_pct"] = n1
    out["consolidada_pct"] = c1
    out["consolidada_2008_pct"] = c0
    out["expansao_pos2008_pct"] = round(max(0.0, c1 - c0), 1)
    out["expansao_pos2008_ha"] = round(area * max(0.0, c1 - c0) / 100, 1)
    lines = [f"MapBiomas confirma: {n1:.0f}% vegetação nativa, {c1:.0f}% uso consolidado"]
    if c1 < 2:
        lines.append("Área majoritariamente preservada — sem uso consolidado relevante a comprovar")
    elif out["expansao_pos2008_pct"] >= 2:
        lines.append(f"⚠ {out['expansao_pos2008_ha']} ha de uso surgiram DEPOIS de 2008 — "
                     f"não qualificam como área consolidada (eram nativa em {y0})")
    else:
        lines.append(f"✓ uso já existia em {y0} — qualifica como consolidada (pré-22/07/2008)")
    out["lines"] = lines
    return out

if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(); ap.add_argument("cod"); ap.add_argument("--dsn", required=True)
    a = ap.parse_args()
    r = cross(a.cod, a.dsn)
    print(json.dumps(r, ensure_ascii=False, indent=2))
