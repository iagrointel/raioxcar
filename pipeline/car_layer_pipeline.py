#!/usr/bin/env python3
from __future__ import annotations

import argparse
import math
import json
import subprocess
from functools import lru_cache
from io import BytesIO
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.collections import PatchCollection
from matplotlib.lines import Line2D
from matplotlib.patches import Patch, Polygon as MplPolygon
from PIL import Image
import requests
from pyproj import Transformer
from shapely.geometry import shape
from shapely.ops import transform as shapely_transform

try:
    from imagery_pipeline import _run_psql, _sql_literal, get_car_boundary_geom, get_prodes_alert_geoms
except Exception:
    def _run_psql(dsn: str, sql: str) -> str:
        proc = subprocess.run(
            ["psql", dsn, "-A", "-t", "-v", "ON_ERROR_STOP=1", "-c", sql],
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr.strip() or proc.stdout.strip())
        return proc.stdout.strip()

    def _sql_literal(value: str) -> str:
        return value.replace("'", "''")

    def get_car_boundary_geom(cod_imovel: str, dsn: str) -> dict:
        cod = _sql_literal(cod_imovel)
        raw = _run_psql(
            dsn,
            f"SELECT ST_AsGeoJSON(geom) FROM car_area_imovel WHERE cod_imovel='{cod}'",
        )
        if not raw:
            raise ValueError(f"Nenhuma geometria CAR encontrada para {cod_imovel}")
        return json.loads(raw)

    def get_prodes_alert_geoms(cod_imovel: str, dsn: str) -> list[dict]:
        cod = _sql_literal(cod_imovel)
        sql = f"""
            SELECT COALESCE(json_agg(ST_AsGeoJSON(ST_Transform(p.prodes_geom, 4326))::json), '[]'::json)
            FROM prodes_post2019_all p
            WHERE p.alert_year >= 2019
              AND p.prodes_geom && ST_Transform((SELECT geom FROM car_area_imovel WHERE cod_imovel='{cod}'), 4674)
              AND ST_Intersects(
                    p.prodes_geom,
                    ST_Transform((SELECT geom FROM car_area_imovel WHERE cod_imovel='{cod}'), 4674)
              )
        """
        raw = _run_psql(dsn, sql)
        return json.loads(raw) if raw else []


LAYER_SPECS = [
    ("car_area_consolidada", "#90EE90", 0.35, "Consolidada"),
    ("car_reserva_legal", "#006400", 0.30, "Reserva Legal"),
    ("car_vegetacao_nativa", "#228B22", 0.25, "Veg. nativa"),
    ("car_apps", "#FF6B6B", 0.35, "APP"),
    ("car_hidrografia", "#4169E1", 0.40, "Hidrografia"),
    ("car_area_pousio", "#FFD700", 0.30, "Pousio"),
    ("car_uso_restrito", "#FF8C00", 0.30, "Uso restrito"),
    ("car_servidao_administrativa", "#808080", 0.25, "Servidão adm."),
]

ESRI_WORLD_IMAGERY = "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
MERCATOR = Transformer.from_crs("EPSG:4326", "EPSG:3857", always_xy=True)
WORLD_RESOLUTION = 156543.03392804097
MAX_TILES = 64


@lru_cache(maxsize=64)
def table_exists(dsn: str, table_name: str) -> bool:
    raw = _run_psql(dsn, f"SELECT to_regclass('public.{table_name}')::text")
    return bool(raw and raw.strip() and raw.strip() != "null")


def load_layer_geoms(dsn: str, table_name: str, cod_imovel: str) -> list[dict]:
    if not table_exists(dsn, table_name):
        return []
    cod = _sql_literal(cod_imovel)
    sql = f"""
        SELECT COALESCE(json_agg(ST_AsGeoJSON(geom)::json), '[]'::json)
        FROM public.{table_name}
        WHERE cod_imovel='{cod}'
    """
    raw = _run_psql(dsn, sql)
    return json.loads(raw) if raw else []


def project_geometry(geom_json: dict):
    return shapely_transform(MERCATOR.transform, shape(geom_json))


def clamp_lat(lat: float) -> float:
    return max(min(lat, 85.05112878), -85.05112878)


def lonlat_to_tile(lon: float, lat: float, zoom: int) -> tuple[float, float]:
    lat = clamp_lat(lat)
    n = 2**zoom
    xtile = (lon + 180.0) / 360.0 * n
    lat_rad = math.radians(lat)
    ytile = (1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n
    return xtile, ytile


def tile_to_lonlat(x: int, y: int, zoom: int) -> tuple[float, float]:
    n = 2**zoom
    lon = x / n * 360.0 - 180.0
    lat = math.degrees(math.atan(math.sinh(math.pi * (1.0 - 2.0 * y / n))))
    return lon, lat


def choose_zoom(bounds_merc: tuple[float, float, float, float], target_pixels: int = 1500) -> int:
    minx, miny, maxx, maxy = bounds_merc
    span = max(maxx - minx, maxy - miny, 1.0)
    resolution = span / max(target_pixels, 1)
    zoom = round(math.log2(WORLD_RESOLUTION / resolution))
    return max(10, min(17, zoom))


@lru_cache(maxsize=2048)
def fetch_tile(z: int, x: int, y: int) -> Image.Image:
    url = ESRI_WORLD_IMAGERY.format(z=z, x=x, y=y)
    try:
        response = requests.get(
            url,
            timeout=20,
            headers={"User-Agent": "iAgroIntel-Static-Renderer/1.0"},
        )
        response.raise_for_status()
        return Image.open(BytesIO(response.content)).convert("RGB")
    except Exception:
        return Image.new("RGB", (256, 256), "#d9e3ea")


def build_esri_basemap(extent_lonlat: tuple[float, float, float, float], bounds_merc: tuple[float, float, float, float]):
    minlon, minlat, maxlon, maxlat = extent_lonlat
    zoom = choose_zoom(bounds_merc)

    while True:
        x0, y0 = lonlat_to_tile(minlon, maxlat, zoom)
        x1, y1 = lonlat_to_tile(maxlon, minlat, zoom)
        x_start, x_end = math.floor(x0), math.floor(x1)
        y_start, y_end = math.floor(y0), math.floor(y1)
        tiles = (x_end - x_start + 1) * (y_end - y_start + 1)
        if tiles <= MAX_TILES or zoom <= 10:
            break
        zoom -= 1

    cols = x_end - x_start + 1
    rows = y_end - y_start + 1
    canvas = Image.new("RGB", (cols * 256, rows * 256))
    for x in range(x_start, x_end + 1):
        for y in range(y_start, y_end + 1):
            tile = fetch_tile(zoom, x, y)
            canvas.paste(tile, ((x - x_start) * 256, (y - y_start) * 256))

    lon_left, lat_top = tile_to_lonlat(x_start, y_start, zoom)
    lon_right, lat_bottom = tile_to_lonlat(x_end + 1, y_end + 1, zoom)
    left, bottom = MERCATOR.transform(lon_left, lat_bottom)
    right, top = MERCATOR.transform(lon_right, lat_top)
    return canvas, (left, right, bottom, top), zoom


def draw_geometries(
    ax,
    geoms: list[dict],
    color: str,
    alpha: float,
    legend_items: list,
    label: str,
    *,
    fill: bool = True,
    linewidth: float = 0.8,
):
    poly_patches = []
    added_line = False
    added_point = False

    for geom_json in geoms:
        geom = project_geometry(geom_json)
        geom_type = geom.geom_type

        if geom_type == "Polygon":
            poly_patches.append(MplPolygon(np.asarray(geom.exterior.coords), closed=True))
        elif geom_type == "MultiPolygon":
            for polygon in geom.geoms:
                poly_patches.append(MplPolygon(np.asarray(polygon.exterior.coords), closed=True))
        elif geom_type == "LineString":
            coords = np.asarray(geom.coords)
            ax.plot(coords[:, 0], coords[:, 1], color=color, linewidth=linewidth, alpha=max(alpha, 0.85))
            added_line = True
        elif geom_type == "MultiLineString":
            for line in geom.geoms:
                coords = np.asarray(line.coords)
                ax.plot(coords[:, 0], coords[:, 1], color=color, linewidth=linewidth, alpha=max(alpha, 0.85))
            added_line = True
        elif geom_type == "Point":
            ax.scatter([geom.x], [geom.y], s=14, c=color, alpha=max(alpha, 0.85), edgecolors="none")
            added_point = True
        elif geom_type == "MultiPoint":
            xs = [point.x for point in geom.geoms]
            ys = [point.y for point in geom.geoms]
            ax.scatter(xs, ys, s=14, c=color, alpha=max(alpha, 0.85), edgecolors="none")
            added_point = True

    if poly_patches:
        collection = PatchCollection(
            poly_patches,
            facecolor=color if fill else "none",
            edgecolor=color,
            alpha=alpha if fill else 1.0,
            linewidth=linewidth,
        )
        ax.add_collection(collection)
        legend_items.append(
            Patch(facecolor=color if fill else "none", edgecolor=color, alpha=alpha if fill else 1.0, label=label)
        )
    elif added_line:
        legend_items.append(Line2D([0], [0], color=color, linewidth=2, label=label))
    elif added_point:
        legend_items.append(
            Line2D([0], [0], marker="o", markersize=5, linestyle="none", markerfacecolor=color, markeredgecolor=color, label=label)
        )


def build_car_layer_image(
    cod_imovel: str,
    dsn: str,
    out_path: str,
    title: str | None = None,
    prodes_label_count: int | None = None,
) -> str:
    car_geom_json = get_car_boundary_geom(cod_imovel, dsn)
    car_shape_ll = shape(car_geom_json)
    car_shape = project_geometry(car_geom_json)
    minlon, minlat, maxlon, maxlat = car_shape_ll.bounds
    minx, miny, maxx, maxy = car_shape.bounds

    dx = (maxx - minx) * 0.20
    dy = (maxy - miny) * 0.20
    extent = [minx - dx, maxx + dx, miny - dy, maxy + dy]

    dlon = (maxlon - minlon) * 0.20
    dlat = (maxlat - minlat) * 0.20
    extent_lonlat = (
        max(-180.0, minlon - dlon),
        clamp_lat(minlat - dlat),
        min(180.0, maxlon + dlon),
        clamp_lat(maxlat + dlat),
    )
    basemap, basemap_extent, zoom = build_esri_basemap(extent_lonlat, tuple(extent))

    fig, ax = plt.subplots(1, 1, figsize=(10, 10), dpi=150)
    ax.imshow(basemap, extent=basemap_extent, interpolation="bilinear", zorder=0)
    ax.set_xlim(extent[0], extent[1])
    ax.set_ylim(extent[2], extent[3])
    ax.set_aspect("equal")
    ax.set_facecolor("#d9e3ea")

    legend_items: list = []
    for table_name, color, alpha, label in LAYER_SPECS:
        geoms = load_layer_geoms(dsn, table_name, cod_imovel)
        if geoms:
            draw_geometries(ax, geoms, color, alpha, legend_items, label, fill=True, linewidth=0.6)

    draw_geometries(
        ax,
        [car_geom_json],
        "#FF00FF",
        1.0,
        legend_items,
        "Perímetro CAR",
        fill=False,
        linewidth=2.2,
    )

    prodes_geoms = get_prodes_alert_geoms(cod_imovel, dsn)
    if prodes_geoms:
        prodes_count = prodes_label_count if prodes_label_count is not None else len(prodes_geoms)
        draw_geometries(
            ax,
            prodes_geoms,
            "#d11f1f",
            0.40,
            legend_items,
            f"PRODES ({prodes_count} alertas)",
            fill=True,
            linewidth=0.9,
        )

    if legend_items:
        ax.legend(handles=legend_items, loc="upper right", fontsize=8, framealpha=0.96, facecolor="white")

    ax.set_title(title or f"{cod_imovel}\nBase ESRI World Imagery + camadas SICAR + PRODES", fontsize=11)
    ax.text(
        0.01,
        0.01,
        f"Base cartográfica: Esri World Imagery · zoom {zoom}",
        transform=ax.transAxes,
        fontsize=7,
        color="white",
        bbox={"facecolor": "black", "alpha": 0.55, "pad": 3, "edgecolor": "none"},
        zorder=5,
    )
    ax.axis("off")

    out_file = Path(out_path)
    out_file.parent.mkdir(parents=True, exist_ok=True)
    plt.tight_layout()
    plt.savefig(out_file, dpi=150, bbox_inches="tight", pad_inches=0.08, facecolor="white")
    plt.close(fig)
    return str(out_file)


def main() -> None:
    parser = argparse.ArgumentParser(description="Renderiza camadas SICAR + PRODES para um CAR.")
    parser.add_argument("--cod-imovel", required=True, help="Código CAR completo")
    parser.add_argument("--dsn", required=True, help="DSN PostgreSQL")
    parser.add_argument("--out", required=True, help="PNG de saída")
    parser.add_argument("--title", help="Título opcional da imagem")
    parser.add_argument("--prodes-label-count", type=int, help="Contagem de alertas usada apenas na legenda do mapa")
    args = parser.parse_args()

    out_file = build_car_layer_image(
        args.cod_imovel,
        args.dsn,
        args.out,
        args.title,
        prodes_label_count=args.prodes_label_count,
    )
    print(f"Saved: {out_file}")


if __name__ == "__main__":
    main()
