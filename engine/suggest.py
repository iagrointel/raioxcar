#!/usr/bin/env python3
"""Raio-X CAR · suggest.py — job 2: propor a geometria corrigida.
Deterministic corrections derivable from open data: the would-be APP (rio buffer ∩ perímetro),
the crossing official river, and the perimeter — packaged as GeoJSON + KML for the analyst/produtor
to adopt. (RL placement is a producer choice → we output the déficit number, not a polygon.)"""
from __future__ import annotations
import sys, json, argparse
sys.path.insert(0, os.path.join(os.path.dirname(__file__),"..","pipeline"))
import fix_my_car


def correction_featurecollection(cod_imovel: str, dsn: str, diag: dict | None = None) -> dict:
    diag = diag or fix_my_car.compute_diagnosis(cod_imovel, dsn)
    feats = []
    if diag.get("perimetro_geojson"):
        feats.append({"type": "Feature", "properties": {"camada": "imovel", "nome": "Perímetro do imóvel"},
                      "geometry": diag["perimetro_geojson"]})
    if diag.get("app_geojson"):
        feats.append({"type": "Feature",
                      "properties": {"camada": "app_sugerida", "nome": f"APP devida (~{diag.get('app_omitida_ha')} ha)"},
                      "geometry": diag["app_geojson"]})
    for rg in (diag.get("rios_geojson") or []):
        feats.append({"type": "Feature", "properties": {"camada": "hidrografia", "nome": "Rio oficial (ANA/IBGE)"},
                      "geometry": rg})
    return {"type": "FeatureCollection",
            "properties": {"cod_imovel": cod_imovel,
                           "rl_deficit_ha": diag.get("rl_deficit_ha"),
                           "rl_min_pct": diag.get("rl_min_pct"),
                           "obs": "Correções derivadas de dado aberto (apoio à decisão). "
                                  "RL: ajustar a localização é escolha do produtor."},
            "features": feats}


def correction_kml(cod_imovel: str, dsn: str, out_path: str, diag: dict | None = None) -> str:
    diag = diag or fix_my_car.compute_diagnosis(cod_imovel, dsn)
    return fix_my_car.export_kml(cod_imovel, diag, out_path)


def main():
    ap = argparse.ArgumentParser(description="Geometria corrigida do CAR (GeoJSON/KML).")
    ap.add_argument("cod_imovel"); ap.add_argument("--dsn", required=True)
    ap.add_argument("--kml")
    a = ap.parse_args()
    fc = correction_featurecollection(a.cod_imovel, a.dsn)
    if a.kml:
        correction_kml(a.cod_imovel, a.dsn, a.kml)
        print("KML:", a.kml)
    print(json.dumps({"n_features": len(fc["features"]),
                      "rl_deficit_ha": fc["properties"]["rl_deficit_ha"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
