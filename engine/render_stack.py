#!/usr/bin/env python3
"""Raio-X CAR · render_stack — aligned layer stack for the analyst workstation.
Every layer is rendered to the SAME UTM grid (identical W×H) so they overlay pixel-perfect
and NEVER drift. Bases: RGB recente (Sentinel), RGB 2008 (Landsat), MapBiomas uso-do-solo.
Overlays (transparent): camadas DECLARADAS (SICAR) and the SUGESTÃO (APP devida + rios).
Output: cache/{cod}/stack/*.png (same size) + stack.json. All open data."""
from __future__ import annotations
import os, sys, json, warnings
from pathlib import Path
warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.join(os.path.dirname(__file__),"..","pipeline")); sys.path.insert(0, os.path.join(os.path.dirname(__file__),"..","pipeline"))
sys.path.insert(0, str(Path(__file__).parent))
import numpy as np
import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
import rasterio
from rasterio.warp import reproject, Resampling, transform_bounds
from rasterio.windows import from_bounds as winb, Window
import rasterio.features as rfeat
import pyproj
from shapely.geometry import shape, mapping
from shapely.ops import transform as stransform
import crisp_rgb as C
import mapbiomas_cross as MB
import fix_my_car
import car_layer_pipeline as clp

CACHE = Path(os.environ.get("RAIOX_CACHE", str(Path(__file__).parent / "cache")))
# MapBiomas group → color (uso-do-solo, classes do Código Florestal)
GCOL = {"nativa": (31, 122, 58), "consolidada": (216, 193, 122), "agua": (65, 105, 225), "outros": (120, 120, 120)}

def _to_grid_crs(geom_ll, epsg):
    tr = pyproj.Transformer.from_crs(4326, epsg, always_xy=True).transform
    return stransform(tr, geom_ll)

def _rasterize(geoms_ll, grid, fill_rgba, line=False, outline_rgba=None, lw=2):
    """Burn lat/lon geoms onto a W×H RGBA at the grid (perfect registration)."""
    out = np.zeros((grid["H"], grid["W"], 4), "uint8")
    shp = [mapping(_to_grid_crs(shape(g), grid["epsg"])) for g in geoms_ll if g]
    if not shp: return out
    mask = rfeat.rasterize(shp, out_shape=(grid["H"], grid["W"]), transform=grid["transform"],
                           fill=0, default_value=1, all_touched=line, dtype="uint8")
    for c in range(4): out[:, :, c] = np.where(mask == 1, fill_rgba[c], out[:, :, c])
    if outline_rgba is not None and not line:
        import scipy.ndimage as ndi
        edge = mask ^ ndi.binary_erosion(mask, iterations=max(1, lw))
        for c in range(4): out[:, :, c] = np.where(edge == 1, outline_rgba[c], out[:, :, c])
    return out

def _mapbiomas(grid, year=2023):
    dst = np.full((grid["H"], grid["W"]), 0, "uint8")
    try:
        with rasterio.open(MB.BASE.format(year=year)) as src:
            ll, bb, rr, tt = transform_bounds("EPSG:4326", src.crs, *grid["bbox_ll"], densify_pts=21)
            w = winb(ll, bb, rr, tt, transform=src.transform).intersection(Window(0, 0, src.width, src.height))
            a = src.read(1, window=w); wt = src.window_transform(w)
        reproject(a, dst, src_transform=wt, src_crs=src.crs, dst_transform=grid["transform"],
                  dst_crs=f"EPSG:{grid['epsg']}", resampling=Resampling.nearest)
    except Exception:
        pass
    rgba = np.zeros((grid["H"], grid["W"], 4), "uint8")
    for v in np.unique(dst):
        if v == 0: continue
        col = GCOL.get(MB.GROUP.get(int(v), "outros"), GCOL["outros"])
        m = dst == v
        for c in range(3): rgba[:, :, c][m] = col[c]
        rgba[:, :, 3][m] = 235
    return rgba

MB_YEAR = 2023  # MapBiomas Coleção 9 (último ano disponível)

def _peri_overlay(grid, g):
    """Perímetro do imóvel como contorno amarelo (RGBA) — para marcar a propriedade em toda base."""
    return _rasterize([mapping(g)], grid, (0, 0, 0, 0), outline_rgba=(255, 224, 0, 255), lw=4)

def _with_peri(img, peri):
    """Composita o contorno do imóvel sobre uma base (float HxWx3 0–1 ou uint8 HxWx4)."""
    a = np.asarray(img)
    if a.dtype != np.uint8:
        a = (np.clip(a, 0, 1) * 255).astype("uint8")
    if a.shape[2] == 3:
        a = np.dstack([a, np.full(a.shape[:2], 255, "uint8")])
    else:
        a = a.copy()
    m = peri[:, :, 3] > 0
    for c in range(4): a[:, :, c][m] = peri[:, :, c][m]
    return a

def render_stack(cod: str, dsn: str) -> dict:
    g = C._geom(cod, dsn); grid = C._target_grid(g)
    d = CACHE / cod / "stack"; d.mkdir(parents=True, exist_ok=True)
    W, H = grid["W"], grid["H"]; layers = {}
    peri = _peri_overlay(grid, g)   # contorno do imóvel para todas as bases
    # --- bases ---
    recent_date = None
    try:
        try:  # freshest clear scene first
            rgb, vf, n, recent_date = C._composite_s2(grid, C._recent_window(150), prefer_recent=True, cloud_lt=25)
            if vf < 0.85: raise RuntimeError("baixa cobertura")
        except Exception:
            from datetime import datetime as _dt
            rgb, vf, n, recent_date = C._composite_s2(grid, "2024-06-01/%s" % _dt.now().strftime("%Y-%m-%d"))
        plt.imsave(d / "rgb_recente.png", _with_peri(C._punch(C._stretch_fixed(rgb, "s2")), peri))
        layers["rgb_recente"] = {"label": "RGB recente (Sentinel-2)", "base": True, "date": recent_date}
    except Exception as e: layers["rgb_recente"] = {"erro": str(e)[:60]}
    try:
        rgb, _, n = C._composite_landsat(grid, "2005-06-01/2008-07-21")
        plt.imsave(d / "rgb_2008.png", _with_peri(C._punch(C._stretch_fixed(rgb, "landsat")), peri)); layers["rgb_2008"] = {"label": "RGB 2008 (Landsat, pré-corte)", "base": True}
    except Exception as e: layers["rgb_2008"] = {"erro": str(e)[:60]}
    # MapBiomas em dois tempos: pré-2008 (2008) e atual (2023) — mostra a mudança de uso
    for yr, fn in [(2008, "mapbiomas_2008"), (MB_YEAR, "mapbiomas")]:
        try:
            plt.imsave(d / f"{fn}.png", _with_peri(_mapbiomas(grid, yr), peri))
            layers[fn] = {"label": f"MapBiomas {yr}", "base": True, "ano": yr}
        except Exception as e:
            layers[fn] = {"erro": str(e)[:60]}
    # NDVI (vigor da vegetação) — S2 red/nir, cloud-masked median, RdYlGn colormap
    ndvi_val = None
    try:
        nd, _, ndvi_val = C._composite_s2_ndvi(grid, C._recent_window(365))
        norm = np.clip((nd - 0.20) / 0.45, 0, 1)  # 0.20→vermelho · 0.65→verde (realça áreas abertas)
        rgba = (plt.get_cmap("RdYlGn")(norm) * 255).astype("uint8")
        rgba[..., 3] = np.where(np.isfinite(nd), 255, 0)
        plt.imsave(d / "ndvi.png", _with_peri(rgba, peri))
        layers["ndvi"] = {"label": "NDVI — vigor da vegetação", "base": True, "valor_medio": ndvi_val}
    except Exception as e: layers["ndvi"] = {"erro": str(e)[:60]}
    # --- overlays (transparent, registered) ---
    diag = fix_my_car.compute_diagnosis(cod, dsn)
    # declared SICAR camadas (each table its color)
    decl = np.zeros((H, W, 4), "uint8")
    COLS = {"car_apps": (255, 107, 107), "car_reserva_legal": (31, 174, 90), "car_vegetacao_nativa": (31, 122, 58),
            "car_area_consolidada": (216, 193, 122), "car_hidrografia": (65, 163, 255)}
    for table, color in COLS.items():
        try:
            geoms = clp.load_layer_geoms(dsn, table, cod)
        except Exception: geoms = []
        if geoms:
            lay = _rasterize(geoms, grid, (*color, 150), outline_rgba=(*color, 255), lw=2)
            m = lay[:, :, 3] > 0
            for c in range(4): decl[:, :, c][m] = lay[:, :, c][m]
    # perimeter outline (magenta) on declared
    if diag.get("perimetro_geojson"):
        per = _rasterize([diag["perimetro_geojson"]], grid, (0, 0, 0, 0), outline_rgba=(255, 0, 240, 255), lw=3)
        m = per[:, :, 3] > 0
        for c in range(4): decl[:, :, c][m] = per[:, :, c][m]
    plt.imsave(d / "declarado.png", decl); layers["declarado"] = {"label": "Declarado no SICAR", "overlay": True}
    # suggested: APP devida (red fill) + rios (blue) + perimeter
    sug = np.zeros((H, W, 4), "uint8")
    if diag.get("rios_geojson"):
        r = _rasterize(diag["rios_geojson"], grid, (30, 144, 255, 255), line=True)
        m = r[:, :, 3] > 0
        for c in range(4): sug[:, :, c][m] = r[:, :, c][m]
    if diag.get("app_geojson"):
        a = _rasterize([diag["app_geojson"]], grid, (255, 45, 45, 150), outline_rgba=(255, 45, 45, 255), lw=2)
        m = a[:, :, 3] > 0
        for c in range(4): sug[:, :, c][m] = a[:, :, c][m]
    if diag.get("perimetro_geojson"):
        per = _rasterize([diag["perimetro_geojson"]], grid, (0, 0, 0, 0), outline_rgba=(255, 224, 0, 255), lw=3)
        m = per[:, :, 3] > 0
        for c in range(4): sug[:, :, c][m] = per[:, :, c][m]
    plt.imsave(d / "sugerido.png", sug); layers["sugerido"] = {"label": "Sugestão (APP devida + rios)", "overlay": True}
    man = {"cod": cod, "W": W, "H": H, "layers": layers,
           "recent_date": recent_date, "ndvi": ndvi_val,
           "app_devida_ha": diag.get("app_omitida_ha"), "rl_deficit_ha": diag.get("rl_deficit_ha"),
           "rl_min_pct": diag.get("rl_min_pct")}
    (CACHE / cod / "stack.json").write_text(json.dumps(man, ensure_ascii=False))
    return man

if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(); ap.add_argument("cod"); ap.add_argument("--dsn", required=True)
    a = ap.parse_args(); print(json.dumps(render_stack(a.cod, a.dsn), ensure_ascii=False, indent=1))
