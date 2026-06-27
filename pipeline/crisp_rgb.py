#!/usr/bin/env python3
"""Raio-X CAR · crisp_rgb — cloud-free, gap-free RGB composites for ANY parcel.
Fixes the two killers: (1) clouds, (2) black tile-edge / half-tile holes.
Method: query ALL scenes intersecting the parcel bbox in a date window, cloud-mask each,
reproject onto ONE fixed UTM grid, take the per-pixel median of valid pixels → no holes, no clouds.
Sources are open (no GEE/ArcGIS): Sentinel-2 (Element84 AWS) ; Landsat-4/5 (Planetary Computer)."""
import os, sys, json, subprocess, warnings, math
from datetime import datetime, timedelta
warnings.filterwarnings("ignore")
os.environ.update(AWS_NO_SIGN_REQUEST="YES", GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR",
                  VSI_CACHE="TRUE", GDAL_HTTP_TIMEOUT="30", GDAL_HTTP_MAX_RETRY="3", GDAL_HTTP_RETRY_DELAY="1")
import numpy as np
import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
import rasterio
from rasterio.warp import reproject, Resampling, transform_bounds
from rasterio.windows import from_bounds as winb, Window
from rasterio.transform import from_origin
import pyproj
from shapely.geometry import shape
from shapely.ops import transform as stransform

def _geom(cod, dsn):
    gj = subprocess.run(["psql", dsn, "-tAc",
        f"SELECT ST_AsGeoJSON(geom) FROM car_area_imovel WHERE cod_imovel='{cod}' LIMIT 1"],
        capture_output=True, text=True).stdout.strip()
    if not gj: raise ValueError(f"sem geom para {cod}")
    return shape(json.loads(gj))

def _utm_epsg(lon, lat):
    return (32600 if lat >= 0 else 32700) + int((lon + 180) // 6) + 1

def _target_grid(geom, pad_frac=0.18, res=10.0, max_px=1100):
    minx, miny, maxx, maxy = geom.bounds
    dx, dy = (maxx-minx)*pad_frac + 0.003, (maxy-miny)*pad_frac + 0.003
    bbox_ll = (minx-dx, miny-dy, maxx+dx, maxy+dy)
    cx, cy = (minx+maxx)/2, (miny+maxy)/2
    epsg = _utm_epsg(cx, cy)
    to_utm = pyproj.Transformer.from_crs(4326, epsg, always_xy=True).transform
    xs, ys = [], []
    for lon, lat in [(bbox_ll[0],bbox_ll[1]),(bbox_ll[2],bbox_ll[1]),(bbox_ll[2],bbox_ll[3]),(bbox_ll[0],bbox_ll[3])]:
        x, y = to_utm(lon, lat); xs.append(x); ys.append(y)
    ux0, ux1, uy0, uy1 = min(xs), max(xs), min(ys), max(ys)
    w_m, h_m = ux1-ux0, uy1-uy0
    res = max(res, w_m/max_px, h_m/max_px)   # coarsen for huge parcels
    W, H = max(2, math.ceil(w_m/res)), max(2, math.ceil(h_m/res))
    transform = from_origin(ux0, uy1, res, res)
    return dict(epsg=epsg, transform=transform, W=W, H=H, bbox_ll=bbox_ll,
                bounds_utm=(ux0, uy0, ux1, uy1))

def _stretch(rgb):
    # per-image percentile (legacy) — NOT consistent across parcels
    rgb = rgb.astype("float32")
    for c in range(3):
        ch = rgb[:, :, c]; m = np.isfinite(ch) & (ch > 0)
        if m.any():
            lo, hi = np.percentile(ch[m], (2, 98))
            if hi > lo: rgb[:, :, c] = np.clip((ch-lo)/(hi-lo), 0, 1)
    return np.clip(np.nan_to_num(rgb, nan=0.0) ** 0.88, 0, 1)

def _stretch_fixed(rgb, sensor):
    """CONSISTENT radiometry — same mapping everywhere → seamless, mosaic/planet-grade.
    No data-dependent percentiles, so two parcels (or two tiles) share identical color."""
    rgb = rgb.astype("float32")
    if sensor == "s2":
        # Sentinel-2 'visual'/TCI is already an ESA-balanced 8-bit true-color product
        out = np.clip(rgb / 255.0 * 1.08, 0, 1) ** 0.92
    else:
        # Landsat surface reflectance: fixed 0.00–0.30 window + mild gamma
        out = np.clip(rgb / 0.30, 0, 1) ** 0.90
    return np.nan_to_num(out, nan=0.0)

def _punch(rgb):
    """Per-parcel punch: gentle luminance-percentile contrast + saturation lift → crisp, not dull.
    Single lo/hi over luminance (not per-channel) so there's no color cast; same parcel before/after
    each read clearly. Applied only to the display chips, not the cross-parcel-consistent stack."""
    rgb = np.clip(np.nan_to_num(rgb, nan=0.0), 0, 1)
    lum = rgb.mean(2); m = lum > 0.001
    if m.any():
        lo, hi = np.percentile(lum[m], (1.5, 99.0))
        if hi > lo: rgb = np.clip((rgb - lo) / (hi - lo), 0, 1)
    g = rgb.mean(2, keepdims=True)
    rgb = np.clip(g + (rgb - g) * 1.18, 0, 1)   # saturation +18%
    return np.clip(rgb ** 0.94, 0, 1)            # mild brighten

def _reproj_to_grid(src_arr, src_transform, src_crs, g):
    dst = np.full((g["H"], g["W"]), np.nan, dtype="float32")
    reproject(src_arr, dst, src_transform=src_transform, src_crs=src_crs,
              dst_transform=g["transform"], dst_crs=f"EPSG:{g['epsg']}",
              resampling=Resampling.bilinear, src_nodata=np.nan, dst_nodata=np.nan)
    return dst

def _recent_window(days=150):
    today = datetime.now(); start = today - timedelta(days=days)
    return f"{start:%Y-%m-%d}/{today:%Y-%m-%d}"

def _composite_s2(g, window, max_scenes=12, prefer_recent=False, cloud_lt=60):
    """median composite. prefer_recent → sort by date desc (freshest clear scenes first) and
    return the newest contributing acquisition date. Returns (rgb, valid_frac, n, newest_date_iso)."""
    from pystac_client import Client
    cl = Client.open("https://earth-search.aws.element84.com/v1")
    sortby = ([{"field": "properties.datetime", "direction": "desc"}] if prefer_recent
              else [{"field": "properties.eo:cloud_cover", "direction": "asc"}])
    its = list(cl.search(collections=["sentinel-2-l2a"], bbox=g["bbox_ll"], datetime=window,
        query={"eo:cloud_cover": {"lt": cloud_lt}}, sortby=sortby).items())[:max_scenes]
    import scipy.ndimage as ndi
    stk = [[], [], []]; dates = []
    for it in its:
        try:
            with rasterio.open(it.assets["visual"].href) as ds:
                ll, bb, rr, tt = transform_bounds("EPSG:4326", ds.crs, *g["bbox_ll"], densify_pts=21)
                w = winb(ll, bb, rr, tt, transform=ds.transform).intersection(Window(0, 0, ds.width, ds.height))
                if w.width < 2 or w.height < 2: continue
                vis = ds.read(window=w).astype("float32"); wt = ds.window_transform(w); crs = ds.crs
            with rasterio.open(it.assets["scl"].href) as sd:
                ll, bb, rr, tt = transform_bounds("EPSG:4326", sd.crs, *g["bbox_ll"], densify_pts=21)
                w2 = winb(ll, bb, rr, tt, transform=sd.transform).intersection(Window(0, 0, sd.width, sd.height))
                scl = sd.read(1, window=w2).astype("int16")
            if scl.shape != vis.shape[1:]:
                scl = ndi.zoom(scl, (vis.shape[1]/scl.shape[0], vis.shape[2]/scl.shape[1]), order=0)[:vis.shape[1], :vis.shape[2]]
            bad = np.isin(scl, [0, 1, 3, 8, 9, 10, 11])
            for c in range(3):
                b = vis[c].copy(); b[bad] = np.nan; b[b == 0] = np.nan
                stk[c].append(_reproj_to_grid(b, wt, crs, g))
            dd = (it.properties or {}).get("datetime")
            if dd: dates.append(dd[:10])
        except Exception:
            continue
    if not stk[0]: raise RuntimeError("sem cena Sentinel utilizável")
    rgb = np.dstack([np.nanmedian(np.stack(stk[c]), axis=0) for c in range(3)])
    valid = np.isfinite(rgb).all(axis=2).mean()
    return rgb, float(valid), len(stk[0]), (max(dates) if dates else None)

def _composite_s2_ndvi(g, window, max_scenes=10, cloud_lt=40):
    """median NDVI from S2 red(B04)+nir(B08), SCL cloud-masked. Returns (ndvi_2d, valid, mean_val)."""
    from pystac_client import Client
    cl = Client.open("https://earth-search.aws.element84.com/v1")
    its = list(cl.search(collections=["sentinel-2-l2a"], bbox=g["bbox_ll"], datetime=window,
        query={"eo:cloud_cover": {"lt": cloud_lt}},
        sortby=[{"field": "properties.eo:cloud_cover", "direction": "asc"}]).items())[:max_scenes]
    red_s, nir_s = [], []
    for it in its:
        try:
            def rd(asset):
                with rasterio.open(it.assets[asset].href) as ds:
                    ll, bb, rr, tt = transform_bounds("EPSG:4326", ds.crs, *g["bbox_ll"], densify_pts=21)
                    w = winb(ll, bb, rr, tt, transform=ds.transform).intersection(Window(0, 0, ds.width, ds.height))
                    if w.width < 2 or w.height < 2: return None, None, None
                    return ds.read(1, window=w).astype("float32"), ds.window_transform(w), ds.crs
            red, wt, crs = rd("red"); nir, _, _ = rd("nir")
            if red is None or nir is None: continue
            with rasterio.open(it.assets["scl"].href) as sd:
                ll, bb, rr, tt = transform_bounds("EPSG:4326", sd.crs, *g["bbox_ll"], densify_pts=21)
                w2 = winb(ll, bb, rr, tt, transform=sd.transform).intersection(Window(0, 0, sd.width, sd.height))
                scl = sd.read(1, out_shape=red.shape, window=w2, resampling=Resampling.nearest).astype("int16")
            bad = np.isin(scl, [0, 1, 3, 8, 9, 10, 11])
            red[bad] = np.nan; nir[bad] = np.nan; red[red == 0] = np.nan; nir[nir == 0] = np.nan
            red_s.append(_reproj_to_grid(red, wt, crs, g)); nir_s.append(_reproj_to_grid(nir, wt, crs, g))
        except Exception:
            continue
    if not red_s: raise RuntimeError("sem cena NDVI utilizável")
    R = np.nanmedian(np.stack(red_s), axis=0); N = np.nanmedian(np.stack(nir_s), axis=0)
    ndvi = (N - R) / (N + R + 1e-6)
    return ndvi, float(np.isfinite(ndvi).mean()), round(float(np.nanmean(ndvi)), 3)

def _composite_landsat(g, window, max_scenes=14):
    import planetary_computer as pc, pystac_client
    cat = pystac_client.Client.open("https://planetarycomputer.microsoft.com/api/stac/v1", modifier=pc.sign_inplace)
    its = sorted(cat.search(collections=["landsat-c2-l2"], bbox=g["bbox_ll"], datetime=window,
        query={"platform": {"in": ["landsat-5", "landsat-4"]}, "eo:cloud_cover": {"lt": 60}}).items(),
        key=lambda i: i.properties.get("eo:cloud_cover", 99))[:max_scenes]
    stk = [[], [], []]
    for it in its:
        try:
            def rd(asset):
                with rasterio.open(it.assets[asset].href) as ds:
                    ll, bb, rr, tt = transform_bounds("EPSG:4326", ds.crs, *g["bbox_ll"], densify_pts=21)
                    w = winb(ll, bb, rr, tt, transform=ds.transform).intersection(Window(0, 0, ds.width, ds.height))
                    if w.width < 2 or w.height < 2: return None, None, None
                    return ds.read(1, window=w), ds.window_transform(w), ds.crs
            qa, wt, crs = rd("qa_pixel")
            if qa is None: continue
            cloud = (np.bitwise_and(qa, (1 << 1) | (1 << 3) | (1 << 4)) > 0) | (qa == 1)
            bands = {}
            ok = True
            for name in ("red", "green", "blue"):
                a, _, _ = rd(name)
                if a is None: ok = False; break
                bands[name] = a.astype("float32")
            if not ok: continue
            for i, name in enumerate(("red", "green", "blue")):
                sr = np.clip(bands[name]*2.75e-5 - 0.2, 0, 0.4)
                sr[cloud] = np.nan; sr[bands[name] == 0] = np.nan
                stk[i].append(_reproj_to_grid(sr, wt, crs, g))
        except Exception:
            continue
    if not stk[0]: raise RuntimeError("sem cena Landsat utilizável")
    rgb = np.dstack([np.nanmedian(np.stack(stk[c]), axis=0) for c in range(3)])
    valid = np.isfinite(rgb).all(axis=2).mean()
    return rgb, float(valid), len(stk[0])

def render(cod, dsn, out, sensor="s2", window=None, perimeter=True, consistent=True):
    g = _geom(cod, dsn); grid = _target_grid(g)
    date = None
    if sensor == "landsat":
        window = window or "2005-06-01/2008-07-21"
        rgb, valid, n = _composite_landsat(grid, window); title = "Landsat-5/4 · composição 2007–08 (pré-corte) · sem nuvem"
    else:
        if window:
            rgb, valid, n, date = _composite_s2(grid, window)
        else:  # freshest clear scene first, widen only if coverage is poor
            try:
                rgb, valid, n, date = _composite_s2(grid, _recent_window(150), prefer_recent=True, cloud_lt=25)
                if valid < 0.85: raise RuntimeError("cobertura baixa — alarga janela")
            except Exception:
                rgb, valid, n, date = _composite_s2(grid, "2024-06-01/%s" % datetime.now().strftime("%Y-%m-%d"))
        title = "Sentinel-2 · composição recente · sem nuvem"
    rgb = _stretch_fixed(rgb, sensor) if consistent else _stretch(rgb)
    rgb = _punch(rgb)
    ux0, uy0, ux1, uy1 = grid["bounds_utm"]; ext = [ux0, ux1, uy0, uy1]
    fig, ax = plt.subplots(figsize=(8, 8), dpi=170)
    fig.patch.set_facecolor("#0a140f")
    ax.imshow(rgb, extent=ext, interpolation="bilinear", origin="upper")
    if perimeter:
        to = pyproj.Transformer.from_crs(4326, grid["epsg"], always_xy=True).transform
        gp = stransform(to, g)
        for poly in (gp.geoms if gp.geom_type.startswith("Multi") else [gp]):
            xs, ys = poly.exterior.xy
            ax.plot(xs, ys, color="#000", lw=3.4, alpha=.55)       # halo for contrast
            ax.plot(xs, ys, color="#ffe000", lw=1.8)
    ax.set_xlim(ux0, ux1); ax.set_ylim(uy0, uy1); ax.set_aspect("equal")
    ax.axis("off")
    from pathlib import Path; Path(out).parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(out, dpi=170, bbox_inches="tight", pad_inches=0, facecolor="#0a140f"); plt.close(fig)
    return {"out": out, "sensor": sensor, "n_scenes": n, "valid_frac": round(valid, 3), "date": date}

if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(); ap.add_argument("cod"); ap.add_argument("--dsn", required=True)
    ap.add_argument("--out", required=True); ap.add_argument("--sensor", default="s2")
    a = ap.parse_args(); print(render(a.cod, a.dsn, a.out, sensor=a.sensor))
