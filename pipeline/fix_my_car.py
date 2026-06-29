#!/usr/bin/env python3
"""
fix_my_car — "Conserta o meu CAR" diagnosis engine (haCARthon).

Input: a CAR code (cod_imovel). Output:
  1) a WhatsApp-ready diagnosis card PNG (ESRI sub-meter basemap for small plots /
     Sentinel for large), with SICAR layers + the *would-be APP* (omitted) drawn in red
     and the crossing official river in blue;
  2) a JSON verdict (area, biome, Reserva Legal minimum %, APP omitted ha, status).

Reuses primitives from pipeline/car_layer_pipeline.py.
Open method; the assembled national base (PostGIS iagro_sat) is the moat.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from shapely.geometry import shape

sys.path.insert(0, os.path.join(os.path.dirname(__file__),"..","pipeline"))
from car_layer_pipeline import (  # noqa: E402
    _run_psql, _sql_literal, get_car_boundary_geom,
    build_esri_basemap, draw_geometries, project_geometry,
    load_layer_geoms, clamp_lat, MERCATOR, LAYER_SPECS,
)

# UF -> (biome label [proxy], Reserva Legal minimum %, note). Código Florestal art. 12.
# Amazônia Legal forest states = 80%; rest of Brazil = 20% (cerrado in Amaz. Legal = 35%).
UF_RL = {
    "AC": ("Amazônia", 80, "Amazônia Legal (floresta) — art. 12, I, a"),
    "AM": ("Amazônia", 80, "Amazônia Legal (floresta) — art. 12, I, a"),
    "AP": ("Amazônia", 80, "Amazônia Legal (floresta) — art. 12, I, a"),
    "PA": ("Amazônia", 80, "Amazônia Legal (floresta) — art. 12, I, a"),
    "RO": ("Amazônia", 80, "Amazônia Legal (floresta) — art. 12, I, a"),
    "RR": ("Amazônia", 80, "Amazônia Legal (floresta) — art. 12, I, a"),
    "MT": ("Amazônia/Cerrado", 80, "Amazônia Legal — 80% floresta / 35% cerrado / 20% campos"),
    "TO": ("Cerrado", 35, "Amazônia Legal (cerrado) — art. 12, I, b"),
    "MA": ("Cerrado/Amazônia", 35, "parte em Amazônia Legal — 35% cerrado / 80% floresta"),
}
# everything else: 20%
def biome_rl(uf: str) -> tuple[str, int, str]:
    return UF_RL.get(uf, ("demais regiões", 20, "demais regiões do País — art. 12, II"))


def compute_diagnosis(cod_imovel: str, dsn: str) -> dict:
    """All numbers in one PostGIS round-trip + the omitted-APP geometry as GeoJSON."""
    cod = _sql_literal(cod_imovel)
    sql = f"""
    WITH c AS (
      SELECT cod_imovel, cod_estado, num_area, mod_fiscal, municipio, geom
      FROM car_area_imovel WHERE cod_imovel='{cod}' LIMIT 1
    ),
    rios AS (
      SELECT h.geom FROM hidro_nacional_bc250 h, c WHERE ST_Intersects(h.geom, c.geom)
    ),
    riosu AS (
      SELECT ST_Union(ST_Buffer(geom::geography,30)::geometry) AS gbuf FROM rios
    ),
    appbuf AS (
      SELECT ST_Intersection(riosu.gbuf, c.geom) AS g FROM riosu, c WHERE riosu.gbuf IS NOT NULL
    )
    SELECT json_build_object(
      'cod_imovel', c.cod_imovel,
      'uf', c.cod_estado,
      'municipio', c.municipio,
      'area_ha', round(c.num_area::numeric,2),
      'mod_fiscal', round(c.mod_fiscal::numeric,2),
      'rios_cruzam', (SELECT count(*) FROM rios),
      'app_omitida_ha', round(COALESCE(ST_Area((SELECT g FROM appbuf)::geography)/10000.0,0)::numeric,2),
      'has_app', p.has_app, 'has_rl', p.has_rl, 'has_consol', p.has_consol,
      'has_nativa', p.has_nativa, 'has_hidro', p.has_hidro,
      'has_servidao', (SELECT EXISTS(SELECT 1 FROM car_servidao_administrativa WHERE cod_imovel='{cod}')),
      'rl_declarada_ha', round(COALESCE((SELECT sum(num_area) FROM car_reserva_legal WHERE cod_imovel='{cod}'),0)::numeric,2),
      'rios_geojson', (SELECT COALESCE(json_agg(ST_AsGeoJSON(geom)::json),'[]') FROM rios),
      'app_geojson', (SELECT CASE WHEN g IS NULL OR ST_IsEmpty(g) THEN NULL ELSE ST_AsGeoJSON(g)::json END FROM appbuf),
      'perimetro_geojson', (SELECT ST_AsGeoJSON(geom)::json FROM c)
    )
    FROM c JOIN _layers_present p USING(cod_imovel) LIMIT 1;
    """
    raw = _run_psql(dsn, sql)
    if not raw:
        raise ValueError(f"CAR não encontrado: {cod_imovel}")
    d = json.loads(raw)

    biome, rl_min, rl_note = biome_rl(d["uf"])
    d["biome"] = biome
    d["rl_min_pct"] = rl_min
    d["rl_note"] = rl_note
    area = d["area_ha"] or 0
    rl_pct = round(100.0 * (d["rl_declarada_ha"] or 0) / area, 1) if area else 0
    d["rl_pct"] = rl_pct
    d["rl_deficit_ha"] = round(max(0.0, rl_min/100.0*area - (d["rl_declarada_ha"] or 0)), 2)

    # status
    declared_any = any(d[k] for k in ("has_app","has_rl","has_consol","has_nativa"))
    if not declared_any:
        d["status"] = "só perímetro"
    elif d["has_app"] and d["has_rl"]:
        d["status"] = "completo"
    else:
        d["status"] = "incompleto"

    # módulos fiscais → size class (drives RL rules; SICAR asks for it)
    mf = d.get("mod_fiscal") or 0
    d["mf_classe"] = ("pequena propriedade (≤4 MF)" if mf <= 4
                      else "média propriedade (4–15 MF)" if mf <= 15
                      else "grande propriedade (>15 MF)")

    # plain-PT verdict lines
    lines = [f"Imóvel: {area} ha · {mf} módulos fiscais · {d['municipio']}/{d['uf']} · bioma {biome}"]
    if not d["has_app"] and d["rios_cruzam"] > 0:
        lines.append(f"⚠ APP do rio NÃO declarada: ~{d['app_omitida_ha']} ha (rio oficial cruza o imóvel)")
    if not d["has_rl"]:
        lines.append(f"⚠ Reserva Legal não declarada (mínimo {rl_min}% = {round(rl_min/100.0*area,1)} ha)")
    elif d["rl_deficit_ha"] > 0:
        lines.append(f"⚠ Reserva Legal abaixo do mínimo: faltam {d['rl_deficit_ha']} ha (mín. {rl_min}%)")
    if not d["has_servidao"]:
        lines.append("• Servidão administrativa: confira estradas/linhas e a área líquida do imóvel")
    if d["status"] == "completo":
        lines.append("✓ Camadas principais declaradas")
    d["verdict_lines"] = lines
    return d


def render_card(cod_imovel: str, dsn: str, out_path: str, diag: dict | None = None) -> str:
    diag = diag or compute_diagnosis(cod_imovel, dsn)
    car_geom_json = get_car_boundary_geom(cod_imovel, dsn)
    car_ll = shape(car_geom_json)
    car_m = project_geometry(car_geom_json)
    minx, miny, maxx, maxy = car_m.bounds

    # SQUARE the bbox so small/sliver plots get a crisp, high zoom (fixes thin-strip render)
    cx, cy = (minx+maxx)/2, (miny+maxy)/2
    half = max(maxx-minx, maxy-miny) / 2 * 1.6  # 60% padding around the larger side
    half = max(half, 150.0)  # never tighter than ~300 m window
    minx, maxx, miny, maxy = cx-half, cx+half, cy-half, cy+half
    extent = [minx, maxx, miny, maxy]
    minlon, miny_ll = MERCATOR.transform(minx, miny, direction="INVERSE")
    maxlon, maxy_ll = MERCATOR.transform(maxx, maxy, direction="INVERSE")
    extent_lonlat = (max(-180.0,minlon), clamp_lat(miny_ll), min(180.0,maxlon), clamp_lat(maxy_ll))
    basemap, basemap_extent, zoom = build_esri_basemap(extent_lonlat, tuple(extent))

    fig, ax = plt.subplots(1, 1, figsize=(8, 9), dpi=150)
    ax.imshow(basemap, extent=basemap_extent, interpolation="bilinear", zorder=0)
    ax.set_xlim(extent[0], extent[1]); ax.set_ylim(extent[2], extent[3])
    ax.set_aspect("equal"); ax.set_facecolor("#d9e3ea")

    legend_items: list = []
    # declared SICAR layers (if any)
    for table_name, color, alpha, label in LAYER_SPECS:
        geoms = load_layer_geoms(dsn, table_name, cod_imovel)
        if geoms:
            draw_geometries(ax, geoms, color, alpha, legend_items, label, fill=True, linewidth=0.6)
    # crossing official river (blue) — independent truth
    if diag.get("rios_geojson"):
        draw_geometries(ax, diag["rios_geojson"], "#1e90ff", 0.95, legend_items,
                        "Rio oficial (ANA/IBGE)", fill=False, linewidth=1.8)
    # the WOULD-BE APP (omitted) in red — the headline of the diagnosis
    if diag.get("app_geojson"):
        draw_geometries(ax, [diag["app_geojson"]], "#ff2d2d", 0.45, legend_items,
                        f"APP devida (~{diag['app_omitida_ha']} ha)", fill=True, linewidth=0.8)
    # perimeter (magenta)
    draw_geometries(ax, [car_geom_json], "#FF00FF", 1.0, legend_items, "Perímetro CAR",
                    fill=False, linewidth=2.4)

    if legend_items:
        ax.legend(handles=legend_items, loc="upper right", fontsize=8, framealpha=0.95, facecolor="white")
    ax.set_title(f"CAR Fácil · diagnóstico  ·  {cod_imovel[:25]}…", fontsize=11, fontweight="bold")
    ax.axis("off")

    # verdict band (plain PT) under the map
    band = "\n".join(diag["verdict_lines"])
    fig.subplots_adjust(bottom=0.20)
    fig.text(0.5, 0.015, band, ha="center", va="bottom", fontsize=10.5,
             bbox={"facecolor": "#0b3d2e", "alpha": 0.92, "pad": 10, "edgecolor": "none"},
             color="white")

    out_file = Path(out_path); out_file.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(out_file, dpi=150, bbox_inches="tight", pad_inches=0.10, facecolor="white")
    plt.close(fig)
    return str(out_file)


def export_kml(cod_imovel: str, diag: dict, out_path: str) -> str:
    """Write an importable KML (perímetro + APP devida + rio oficial) for the auditor /
    official module. Built via a GeoJSON FeatureCollection → ogr2ogr."""
    import subprocess, tempfile, os
    feats = []
    if diag.get("perimetro_geojson"):
        feats.append({"type": "Feature", "properties": {"name": "Perímetro do imóvel", "camada": "imovel"},
                      "geometry": diag["perimetro_geojson"]})
    if diag.get("app_geojson"):
        feats.append({"type": "Feature", "properties": {"name": f"APP devida (~{diag.get('app_omitida_ha')} ha)", "camada": "app"},
                      "geometry": diag["app_geojson"]})
    for i, rg in enumerate(diag.get("rios_geojson") or []):
        feats.append({"type": "Feature", "properties": {"name": "Rio oficial (ANA/IBGE)", "camada": "hidrografia"},
                      "geometry": rg})
    fc = {"type": "FeatureCollection", "features": feats}
    with tempfile.NamedTemporaryFile("w", suffix=".geojson", delete=False) as tf:
        json.dump(fc, tf); gj = tf.name
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ogr2ogr", "-f", "KML", out_path, gj, "-nln", cod_imovel],
                   capture_output=True, check=False)
    os.unlink(gj)
    return out_path


def diagnose(cod_imovel: str, dsn: str, out_dir: str = "/tmp/carfacil") -> dict:
    diag = compute_diagnosis(cod_imovel, dsn)
    png = render_card(cod_imovel, dsn, f"{out_dir}/{cod_imovel}.png", diag)
    kml = export_kml(cod_imovel, diag, f"{out_dir}/{cod_imovel}.kml")
    return {"verdict": diag, "png_path": png, "kml_path": kml}


def main() -> None:
    ap = argparse.ArgumentParser(description="Conserta o meu CAR — diagnóstico de um imóvel.")
    ap.add_argument("cod_imovel")
    ap.add_argument("--dsn", required=True)
    ap.add_argument("--out-dir", default="/tmp/carfacil")
    args = ap.parse_args()
    res = diagnose(args.cod_imovel, args.dsn, args.out_dir)
    v = res["verdict"]
    print(json.dumps({k: v[k] for k in v if not k.endswith("geojson")}, ensure_ascii=False, indent=2))
    print("PNG:", res["png_path"])


if __name__ == "__main__":
    main()
