#!/usr/bin/env python3
"""Raio-X CAR · embargo_lookup — the polygon∩perímetro cross (ACTIVE only).

The embargo registries (IBAMA/ICMBio + state OEMAs) carry their OWN geometry and are
filed by auto-de-infração + CPF — *never* by cod_imovel. We reconcile them to the CAR
by SPATIAL overlap (embargo polygon ∩ perimeter, or embargo point ∈ perimeter). Tables:
  - car_embargo_active(cod_imovel, uf_car, emb_gid, fonte, tipo)   — the cross (active only)
  - emb_attr(gid, fonte, ... attributes ...)                       — per-embargo dissection
Key = (fonte, gid). tipo='embargo' is the headline; tipo='auto_infracao' (MS) is secondary.

This is a DIFFERENT, harder axis than the owner-CPF lens of the institutional product:
not "owner embargoed somewhere", but "an active embargo sits physically ON this declared
property". Source data is OPEN (transparência ambiental); no CPF/CNPJ is stored or shown.
"""
from __future__ import annotations
import json, subprocess

PONTO_FONTES = {"SEDAM-RO", "SEMACE-CE", "SEMARH-TO", "INEA-RJ"}


def _psql(dsn: str, sql: str) -> list[str]:
    out = subprocess.run(["psql", dsn, "-tAc", sql], capture_output=True, text=True, timeout=60)
    if out.returncode != 0:
        raise RuntimeError(out.stderr.strip()[:200])
    return [l for l in out.stdout.splitlines() if l != ""]


def for_car(cod: str, dsn: str) -> dict:
    """Per-CAR embargo verdict + full dissection list (fast — indexed on cod_imovel)."""
    cod = cod.replace("'", "''")
    # one row per embargo on this property, with its attributes (the click-through dissection)
    rows = _psql(dsn, f"""
      SELECT t.fonte, t.orgao, COALESCE(t.tipo,'embargo'), COALESCE(t.autuado,''),
             COALESCE(t.data_ref,''), COALESCE(t.infracao,''), COALESCE(t.area_decl,''),
             COALESCE(t.processo,''), COALESCE(t.status,'ATIVO'),
             COALESCE(t.area_geom_ha::text,'')
      FROM car_embargo_active a
      JOIN emb_attr t ON t.fonte=a.fonte AND t.gid=a.emb_gid
      WHERE a.cod_imovel='{cod}'
      ORDER BY (COALESCE(t.tipo,'embargo')='embargo') DESC, t.fonte;""")
    embargos, n_poly, n_point, n_auto = [], 0, 0, 0
    for r in rows:
        f = r.split("|")
        rec = {
            "fonte": f[0], "orgao": f[1] or f[0], "tipo": f[2],
            "autuado": f[3] or None, "data": f[4] or None,
            "infracao": f[5] or None, "area_declarada_ha": f[6] or None,
            "processo": f[7] or None, "status": f[8] or "ATIVO",
            "area_geom_ha": float(f[9]) if f[9] else None,
            "kind": "ponto" if f[0] in PONTO_FONTES else "poligono",
        }
        embargos.append(rec)
        if rec["tipo"] == "auto_infracao":
            n_auto += 1
        elif rec["kind"] == "ponto":
            n_point += 1
        else:
            n_poly += 1
    on_property = n_poly + n_point > 0
    fontes = sorted({e["fonte"] for e in embargos if e["tipo"] == "embargo"})
    return {
        "on_property": on_property,
        "n_embargos": n_poly + n_point,
        "n_area_overlap": n_poly,      # embargo polygon over the perimeter
        "n_point_inside": n_point,     # embargo point inside the perimeter
        "n_autos_infracao": n_auto,    # MS — secondary, not an embargo
        "fontes": fontes,
        "embargos": embargos,          # the full dissection list (click → profile)
        "prioridade": "alta" if on_property else None,   # embargo escalates the triage tier
        "resumo": (
            f"Embargo ambiental ATIVO sobre o imóvel — {len(fontes)} fonte(s): "
            + ", ".join(fontes) if on_property else
            "Sem embargo georreferenciado ativo sobre o perímetro (triagem espacial)."
        ),
    }


def uf_summary(dsn: str) -> dict:
    """Per-UF: distinct CARs with an ACTIVE embargo physically on them + per-fonte."""
    por_uf = []
    for r in _psql(dsn, """
        SELECT uf_car, count(DISTINCT cod_imovel) FROM car_embargo_active
        WHERE tipo='embargo' GROUP BY uf_car ORDER BY 2 DESC NULLS LAST;"""):
        uf, n = r.split("|")
        por_uf.append({"uf": uf or "?", "cars": int(n)})
    por_fonte = []
    for r in _psql(dsn, """
        SELECT fonte, count(DISTINCT cod_imovel) FROM car_embargo_active
        WHERE tipo='embargo' GROUP BY fonte ORDER BY 2 DESC;"""):
        f, n = r.split("|")
        por_fonte.append({"fonte": f, "cars": int(n)})
    total = int(_psql(dsn, "SELECT count(DISTINCT cod_imovel) FROM car_embargo_active WHERE tipo='embargo';")[0])
    pares = int(_psql(dsn, "SELECT count(*) FROM car_embargo_active WHERE tipo='embargo';")[0])
    return {"total_cars": total, "total_overlaps": pares, "por_uf": por_uf, "por_fonte": por_fonte}


if __name__ == "__main__":
    import sys, os
    DSN = os.environ["IAGRO_DSN"]  # ver .env.example
    if len(sys.argv) > 1:
        print(json.dumps(for_car(sys.argv[1], DSN), ensure_ascii=False, indent=2))
    else:
        print(json.dumps(uf_summary(DSN), ensure_ascii=False, indent=2))
