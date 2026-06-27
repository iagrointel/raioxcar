#!/usr/bin/env python3
"""Landsat-5 TM true-color for the PRE-2008 cutoff (22/07/2008) — open data, no GEE/CNES.
Source: Microsoft Planetary Computer (landsat-c2-l2 surface reflectance). True blue band → natural
color, no synth. This is the PRODUCTION 'antes (pré-corte)' layer; SPOT-5 5m is the escalation."""
import os, sys, json, subprocess, warnings
warnings.filterwarnings("ignore")
os.environ.update(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR", VSI_CACHE="TRUE",
                  GDAL_HTTP_TIMEOUT="30", GDAL_HTTP_MAX_RETRY="3", GDAL_HTTP_RETRY_DELAY="1")
import numpy as np
import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
import rasterio
from rasterio.windows import from_bounds as winb, Window
from rasterio.warp import transform_bounds
import pystac_client, planetary_computer as pc
from shapely.geometry import shape
from shapely.ops import transform as stransform
import pyproj

def _geom(cod, dsn):
    gj = subprocess.run(["psql", dsn, "-tAc",
        f"SELECT ST_AsGeoJSON(geom) FROM car_area_imovel WHERE cod_imovel='{cod}' LIMIT 1"],
        capture_output=True, text=True).stdout.strip()
    if not gj: raise ValueError(f"sem geom para {cod}")
    return shape(json.loads(gj))

def render(cod, dsn, out, window="2005-06-01/2008-07-21", perimeter=True):
    g = _geom(cod, dsn)
    minx, miny, maxx, maxy = g.bounds
    dx, dy = (maxx-minx)*0.25+0.01, (maxy-miny)*0.25+0.01
    bbox = [minx-dx, miny-dy, maxx+dx, maxy+dy]
    cat = pystac_client.Client.open("https://planetarycomputer.microsoft.com/api/stac/v1",
                                    modifier=pc.sign_inplace)
    cands = sorted(cat.search(collections=["landsat-c2-l2"], bbox=bbox, datetime=window,
        query={"platform": {"in": ["landsat-5", "landsat-4"]}, "eo:cloud_cover": {"lt": 40}}).items(),
        key=lambda i: i.properties.get("eo:cloud_cover", 99))
    if not cands: raise RuntimeError("sem cena Landsat pré-2008")
    def rd(it, asset):
        with rasterio.open(it.assets[asset].href) as ds:
            ll, bb, rr, tt = transform_bounds("EPSG:4326", ds.crs, *bbox, densify_pts=21)
            w = winb(ll, bb, rr, tt, transform=ds.transform).intersection(Window(0, 0, ds.width, ds.height))
            return ds.read(1, window=w).astype("float32"), ds.window_transform(w), ds.crs
    # pick the lowest-cloud scene that ACTUALLY COVERS the parcel (not an edge sliver)
    chosen, best = None, (-1.0, None)
    for it in cands[:10]:
        try:
            r0, tr0, crs0 = rd(it, "red")
        except Exception:
            continue
        cov = float((r0 > 0).mean()) if r0.size else 0.0
        if cov > best[0]:
            best = (cov, (it, r0, tr0, crs0))
        if cov >= 0.7:
            chosen = (it, r0, tr0, crs0); break
    if chosen is None:
        chosen = best[1]
    if chosen is None:
        raise RuntimeError("sem cena Landsat utilizável")
    it, r, tr, crs = chosen
    date = str(it.datetime.date())
    gg, _, _ = rd(it, "green"); b, _, _ = rd(it, "blue")
    # C2L2 surface reflectance scaling
    def sr(a): return np.clip(a*2.75e-5 - 0.2, 0, 0.4)
    rgb = np.dstack([sr(r), sr(gg), sr(b)])
    for c in range(3):
        ch = rgb[:, :, c]; m = ch > 0
        if m.any():
            lo, hi = np.percentile(ch[m], (2, 98))
            if hi > lo: rgb[:, :, c] = np.clip((ch-lo)/(hi-lo), 0, 1)
    rgb = np.clip(rgb ** 0.9, 0, 1)
    H, W = rgb.shape[0], rgb.shape[1]
    ext = [tr.c, tr.c+tr.a*W, tr.f+tr.e*H, tr.f]
    fig, ax = plt.subplots(figsize=(8, 8), dpi=150)
    ax.imshow(rgb, extent=ext, interpolation="bilinear")
    if perimeter:
        to = pyproj.Transformer.from_crs("EPSG:4326", crs, always_xy=True).transform
        gp = stransform(to, g)
        for poly in (gp.geoms if gp.geom_type.startswith("Multi") else [gp]):
            xs, ys = poly.exterior.xy; ax.plot(xs, ys, color="#ffe000", lw=3)
    ax.set_xlim(ext[0], ext[1]); ax.set_ylim(ext[2], ext[3]); ax.set_aspect("equal")
    ax.set_title(f"Landsat-5 · {date} (pré-corte 22/07/2008)", fontsize=13, fontweight="bold", color="#0b3d2e")
    ax.axis("off")
    from pathlib import Path; Path(out).parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(out, dpi=150, bbox_inches="tight", pad_inches=0.06, facecolor="white"); plt.close(fig)
    return {"out": out, "date": date, "cloud": it.properties.get("eo:cloud_cover")}

if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(); ap.add_argument("cod"); ap.add_argument("--dsn", required=True); ap.add_argument("--out", required=True)
    a = ap.parse_args(); print(render(a.cod, a.dsn, a.out))
