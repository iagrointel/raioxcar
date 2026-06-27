#!/usr/bin/env python3
"""Raio-X CAR · confront.py — "a declaração bate com o satélite?"
Confronts the DECLARED SICAR layers against OBSERVED satellite reality (open data only:
MapBiomas Collection-9 COG + IBGE hydrography), per CAR, and emits a structured verdict.

Reuses the open pipeline (NO GEE / NO ArcGIS):
  - fix_my_car.compute_diagnosis  → declared layers, APP omitida (rio×perímetro), déficit de RL
  - mapbiomas_cross.cross         → observed nativa/consolidada %, expansão pós-2008 (consolidada falsa)

Verdict = conforme | divergente | grave ; grade = bom | consolidado | degradando | grave.
Framing: triagem / apoio à decisão — não é a base oficial certificada.
"""
from __future__ import annotations
import sys, json, argparse
sys.path.insert(0, os.path.join(os.path.dirname(__file__),"..","pipeline"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__),"..","pipeline"))

import fix_my_car
import mapbiomas_cross

# thresholds (ha / pct) — conservative, precision-first (apoio à decisão)
APP_MIN_HA = 1.0          # ignore slivers
RL_DEF_MIN_HA = 1.0
EXP_GRAVE_HA = 5.0        # consolidada surgida pós-2008 que pesa
EXP_GRAVE_PCT = 5.0


def confront(cod_imovel: str, dsn: str, years=(2008, 2023)) -> dict:
    diag = fix_my_car.compute_diagnosis(cod_imovel, dsn)   # 1 PostGIS round-trip
    area = diag.get("area_ha") or 0.0

    out = {
        "cod_imovel": cod_imovel,
        "uf": diag.get("uf"), "municipio": diag.get("municipio"),
        "area_ha": area, "mod_fiscal": diag.get("mod_fiscal"),
        "mf_classe": diag.get("mf_classe"), "bioma": diag.get("biome"),
        "rl_min_pct": diag.get("rl_min_pct"),
        "declarado": {
            "has_app": diag.get("has_app"), "has_rl": diag.get("has_rl"),
            "has_consolidada": diag.get("has_consol"), "has_nativa": diag.get("has_nativa"),
            "has_hidro": diag.get("has_hidro"),
            "rl_declarada_ha": diag.get("rl_declarada_ha"), "rl_pct": diag.get("rl_pct"),
            "status": diag.get("status"),
        },
        "divergencias": [],
        "geo": {  # for the map overlays
            "perimetro": diag.get("perimetro_geojson"),
            "rios": diag.get("rios_geojson"),
            "app_devida": diag.get("app_geojson"),
        },
        "observado": None, "observado_erro": None,
    }
    div = out["divergencias"]

    # transparent APP/RL calculation (rios IBGE BC250 → buffer 30 m ∩ perímetro)
    out["calc"] = {
        "rios_cruzam": diag.get("rios_cruzam"),
        "app_regra_m": 30,
        "app_devida_ha": diag.get("app_omitida_ha"),
        "fonte_rios": "Hidrografia oficial IBGE BC250",
        "rl_min_pct": diag.get("rl_min_pct"),
        "rl_min_ha": round((diag.get("rl_min_pct") or 0)/100.0*area, 2),
        "rl_declarada_ha": diag.get("rl_declarada_ha"),
        "rl_deficit_ha": diag.get("rl_deficit_ha"),
        "rl_nota": diag.get("rl_note"),
    }

    # ── declared-side divergences (already computed, deterministic) ──
    if not diag.get("has_app") and (diag.get("rios_cruzam") or 0) > 0 \
            and (diag.get("app_omitida_ha") or 0) >= APP_MIN_HA:
        div.append({"tipo": "APP omitida", "severidade": "grave",
                    "ha": diag["app_omitida_ha"],
                    "detalhe": f"Rio oficial cruza o imóvel mas NÃO há APP declarada "
                               f"(~{diag['app_omitida_ha']} ha pela regra dos 30 m)."})
    if (diag.get("rl_deficit_ha") or 0) >= RL_DEF_MIN_HA:
        div.append({"tipo": "Déficit de Reserva Legal", "severidade": "media",
                    "ha": diag["rl_deficit_ha"],
                    "detalhe": f"RL declarada {diag.get('rl_pct')}% — faltam "
                               f"{diag['rl_deficit_ha']} ha p/ o mínimo de {diag.get('rl_min_pct')}%."})

    # ── observed-side (satellite) confrontation — open MapBiomas COG ──
    try:
        mb = mapbiomas_cross.cross(cod_imovel, dsn, years=years)
        out["observado"] = {
            "nativa_pct": mb.get("nativa_pct"),
            "consolidada_pct": mb.get("consolidada_pct"),
            "consolidada_2008_pct": mb.get("consolidada_2008_pct"),
            "expansao_pos2008_ha": mb.get("expansao_pos2008_ha"),
            "expansao_pos2008_pct": mb.get("expansao_pos2008_pct"),
            "anos": mb.get("anos"),
        }
        exp_ha = mb.get("expansao_pos2008_ha") or 0.0
        exp_pct = mb.get("expansao_pos2008_pct") or 0.0
        # consolidada falsa / desmatamento pós-2008
        if exp_ha >= EXP_GRAVE_HA or exp_pct >= EXP_GRAVE_PCT:
            sev = "grave" if (exp_ha >= EXP_GRAVE_HA and exp_pct >= EXP_GRAVE_PCT) else "media"
            div.append({"tipo": "Consolidada pós-2008 (não qualifica)", "severidade": sev,
                        "ha": exp_ha,
                        "detalhe": f"{exp_ha} ha de uso surgiram DEPOIS de 22/07/2008 — eram "
                                   f"vegetação nativa em {years[0]}; não qualificam como área consolidada."})
        # declarou consolidada mas satélite vê majoritariamente nativa (uso super-declarado)
        if diag.get("has_consol") and (mb.get("nativa_pct") or 0) >= 70 \
                and (mb.get("consolidada_pct") or 0) <= 20:
            div.append({"tipo": "Consolidada declarada × nativa observada", "severidade": "media",
                        "ha": None,
                        "detalhe": f"Imóvel declara área consolidada, mas o satélite vê "
                                   f"{mb.get('nativa_pct'):.0f}% de vegetação nativa hoje."})
        # CAR desatualizado: não declara consolidada mas satélite vê uso dominante
        if not diag.get("has_consol") and (mb.get("consolidada_pct") or 0) >= 50:
            div.append({"tipo": "Uso observado não declarado (CAR desatualizado)", "severidade": "baixa",
                        "ha": None,
                        "detalhe": f"Satélite vê {mb.get('consolidada_pct'):.0f}% de uso consolidado "
                                   f"não refletido nas camadas declaradas."})
    except Exception as e:  # COG/network hiccup → degrade to declared-only, honest flag
        out["observado_erro"] = str(e)[:160]

    # ── verdict + grade ──
    sev_rank = {"grave": 3, "media": 2, "baixa": 1}
    worst = max([sev_rank.get(d["severidade"], 0) for d in div], default=0)
    if worst >= 3:
        out["verdict"] = "grave"
    elif worst >= 1:
        out["verdict"] = "divergente"
    else:
        out["verdict"] = "conforme"

    obs = out["observado"] or {}
    exp_ha = obs.get("expansao_pos2008_ha") or 0.0
    if worst >= 3 or exp_ha >= EXP_GRAVE_HA:
        out["grade"] = "grave"
    elif exp_ha >= 2.0:
        out["grade"] = "degradando"
    elif (obs.get("consolidada_pct") or 0) >= 50:
        out["grade"] = "consolidado"
    else:
        out["grade"] = "bom"

    # human resumo (≤ a couple lines)
    if out["verdict"] == "conforme":
        out["resumo"] = "Declaração compatível com o satélite — sem divergências relevantes na triagem."
    else:
        tips = "; ".join(d["tipo"] for d in div[:3])
        out["resumo"] = f"{len(div)} divergência(s): {tips}."
    return out


def main():
    ap = argparse.ArgumentParser(description="Confronta CAR declarado × satélite (open data).")
    ap.add_argument("cod_imovel")
    ap.add_argument("--dsn", required=True)
    ap.add_argument("--years", default="2008,2023")
    a = ap.parse_args()
    yrs = tuple(int(x) for x in a.years.split(","))
    r = confront(a.cod_imovel, a.dsn, years=yrs)
    slim = {k: v for k, v in r.items() if k != "geo"}
    print(json.dumps(slim, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
