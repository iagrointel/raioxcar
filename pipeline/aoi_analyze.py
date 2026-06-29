#!/usr/bin/env python3
"""Raio-X CAR · aoi_analyze — X-ray de QUALQUER perímetro a partir de dados públicos.

Diferente do fluxo institucional (que confronta as camadas DECLARADAS no SICAR, exigindo a
base em PostGIS), este módulo recebe **só uma geometria** (um polígono que você traz) e roda
o lado OBSERVADO por satélite — sem banco, sem credencial, sem Google Earth Engine:

  • MapBiomas (COG público)  → % nativa, % uso consolidado, e o que surgiu DEPOIS de 22/07/2008
  • Reserva Legal (regra)    → mínimo do bioma × nativa observada (há vegetação p/ cumprir a RL?)
  • APP (best-effort)        → hidrografia pública (OSM/Overpass) ∩ faixa de 30 m, se disponível

Veredito pela MESMA régua do núcleo institucional (confront.py): "grave" exige DANO observado
(supressão pós-2008 ≥ 5 ha e ≥ 5%); pendências apenas cadastrais ficam em "divergente".

NÃO é base oficial certificada nem auto de infração. Não usa nem expõe dados do proprietário.
A base nacional montada e o cruzamento declarado×satélite em escala são o serviço (open-core).
"""
from __future__ import annotations
import json, sys, math, urllib.request, urllib.parse
from shapely.geometry import shape, mapping
from shapely.ops import unary_union, transform as shp_transform

import mapbiomas_cross as mc

# Reserva Legal mínima pelo bioma (Código Florestal, Lei 12.651/2012, art. 12)
RL_MIN_BIOMA = {
    "amazonia_floresta": 80, "amazonia_cerrado": 35, "amazonia_campos": 20,
    "cerrado": 20, "caatinga": 20, "mata_atlantica": 20, "pampa": 20, "pantanal": 20,
}
EXP_GRAVE_HA, EXP_GRAVE_PCT, APP_MIN_HA = 5.0, 5.0, 1.0


def load_geom(path: str):
    """Aceita GeoJSON (.json/.geojson) ou KML (.kml, via fiona se instalado)."""
    if path.lower().endswith(".kml"):
        try:
            import fiona
            fiona.drvsupport.supported_drivers["KML"] = "rw"
            with fiona.open(path) as src:
                return unary_union([shape(f["geometry"]) for f in src])
        except Exception as e:
            raise SystemExit(f"para ler KML instale 'fiona' (pip install fiona) — {e}")
    d = json.load(open(path))
    t = d.get("type")
    if t == "FeatureCollection":
        return unary_union([shape(f["geometry"]) for f in d["features"]])
    if t == "Feature":
        return shape(d["geometry"])
    return shape(d)


def _utm_epsg(lon, lat):
    return (32700 if lat < 0 else 32600) + int((lon + 180) / 6) + 1


def _to_m(geom):
    import pyproj
    c = geom.centroid
    tr = pyproj.Transformer.from_crs("EPSG:4326", f"EPSG:{_utm_epsg(c.x, c.y)}", always_xy=True)
    return shp_transform(lambda x, y, z=None: tr.transform(x, y), geom)


def _osm_rivers(bounds, timeout=25):
    """Hidrografia pública via Overpass (best-effort, sem chave). Produção usa IBGE BC250."""
    s, w, n, e = bounds[1], bounds[0], bounds[3], bounds[2]
    q = (f'[out:json][timeout:{timeout}];(way["waterway"~"river|stream|canal"]'
         f'({s},{w},{n},{e}););out geom;')
    try:
        req = urllib.request.Request("https://overpass-api.de/api/interpreter",
                                     data=urllib.parse.urlencode({"data": q}).encode(),
                                     headers={"User-Agent": "raio-x-car/openpublic"})
        d = json.loads(urllib.request.urlopen(req, timeout=timeout + 5).read())
    except Exception:
        return None
    from shapely.geometry import LineString
    lines = [LineString([(p["lon"], p["lat"]) for p in el["geometry"]])
             for el in d.get("elements", []) if len(el.get("geometry", [])) >= 2]
    return unary_union(lines) if lines else None


def embargo_cross(geom, embargos_path: str) -> dict:
    """Cruza o perímetro com polígonos de embargo ATIVO que VOCÊ traz (transparência pública
    IBAMA/ICMBio/OEMA). Saída deliberadamente MÍNIMA — só se há embargo e de qual órgão.
    Sem auto, sem CPF, sem área, sem data: a dissecação por auto é o produto institucional.
    O método é o aberto; a base nacional montada (95 mil CARs) é o serviço."""
    d = json.load(open(embargos_path))
    feats = d["features"] if d.get("type") == "FeatureCollection" else [d]
    orgaos, hit = set(), False
    for f in feats:
        try:
            g = shape(f.get("geometry") or f)
        except Exception:
            continue
        if g.is_valid and g.intersects(geom):
            hit = True
            p = f.get("properties", {}) if isinstance(f, dict) else {}
            o = (p.get("orgao") or p.get("fonte") or p.get("agency")
                 or p.get("instituicao") or "órgão ambiental")
            orgaos.add(str(o).strip())
    return {"on_property": hit, "orgaos": sorted(orgaos)}


def analyze(geom, bioma: str | None = None, recent_year: int = 2023, rivers=True,
            embargos: str | None = None) -> dict:
    """X-ray observado de um polígono. `bioma` ∈ RL_MIN_BIOMA (opcional, p/ a régua de RL)."""
    # roda o cruzamento MapBiomas direto na geometria (sem o _geom que exige banco)
    out = {"anos": {}}
    for y in (2008, recent_year):
        frac, ha = mc._fractions(geom, y)
        out["anos"][y] = {"frac_pct": frac, "area_ha": ha}
    area = out["anos"][recent_year]["area_ha"]
    c0 = out["anos"][2008]["frac_pct"].get("consolidada", 0)
    c1 = out["anos"][recent_year]["frac_pct"].get("consolidada", 0)
    n1 = out["anos"][recent_year]["frac_pct"].get("nativa", 0)
    exp_pct = round(max(0.0, c1 - c0), 1)
    exp_ha = round(area * exp_pct / 100, 1)

    res = {
        "area_ha": area, "bioma": bioma,
        "observado": {"nativa_pct": n1, "consolidada_pct": c1,
                      "consolidada_2008_pct": c0,
                      "expansao_pos2008_ha": exp_ha, "expansao_pos2008_pct": exp_pct,
                      "anos": [2008, recent_year]},
        "divergencias": [],
    }
    div = res["divergencias"]

    # supressão pós-2008 (consolidada que não qualifica) — o eixo de DANO
    if exp_ha >= EXP_GRAVE_HA or exp_pct >= EXP_GRAVE_PCT:
        sev = "grave" if (exp_ha >= EXP_GRAVE_HA and exp_pct >= EXP_GRAVE_PCT) else "media"
        div.append({"tipo": "Consolidada pós-2008 (não qualifica)", "severidade": sev,
                    "ha": exp_ha,
                    "detalhe": f"{exp_ha} ha de uso surgiram DEPOIS de 22/07/2008 — eram "
                               f"vegetação nativa em 2008; não qualificam como consolidada."})

    # Reserva Legal — régua do bioma × nativa observada (apoio; não é a RL averbada)
    if bioma in RL_MIN_BIOMA:
        rl_min = RL_MIN_BIOMA[bioma]
        res["rl_min_pct"] = rl_min
        if n1 < rl_min:
            div.append({"tipo": "Vegetação nativa abaixo do mínimo de Reserva Legal",
                        "severidade": "media", "ha": round(area * (rl_min - n1) / 100, 1),
                        "detalhe": f"Nativa observada {n1:.0f}% < mínimo do bioma {rl_min}% — "
                                   f"déficit aparente de vegetação (a RL averbada confirma no SICAR)."})

    # APP — hidrografia pública ∩ faixa de 30 m (best-effort)
    if rivers:
        riv = _osm_rivers(geom.bounds)
        if riv is not None and not riv.is_empty:
            gm, rm = _to_m(geom), _to_m(riv)
            app = rm.buffer(30).intersection(gm)
            app_ha = round(app.area / 10000, 2)
            res["app_devida_ha"] = app_ha
            res["app_fonte"] = "OpenStreetMap waterways (proxy público; produção: IBGE BC250)"
            if app_ha >= APP_MIN_HA:
                div.append({"tipo": "APP sobre hidrografia (verificar averbação)",
                            "severidade": "media" if app_ha >= 3 else "baixa", "ha": app_ha,
                            "detalhe": f"~{app_ha} ha de faixa de 30 m sobre cursos d'água — "
                                       f"verificar se está averbada como APP no SICAR."})
        else:
            res["app_devida_ha"] = None
            res["app_fonte"] = "hidrografia pública indisponível para o recorte (APP não avaliada)"

    # Embargo × perímetro (traga seus polígonos públicos) — a camada distinta do Raio-X.
    # Saída mínima: só on_property + órgão. Embargo ativo escala a triagem a grave.
    emb_on = False
    if embargos:
        emb = embargo_cross(geom, embargos)
        res["embargo"] = emb
        emb_on = emb["on_property"]
        if emb_on:
            div.append({"tipo": "Embargo ambiental ativo sobre o imóvel", "severidade": "grave",
                        "ha": None,
                        "detalhe": "Polígono de embargo ativo cruza o perímetro"
                                   + (f" (origem: {', '.join(emb['orgaos'])})" if emb["orgaos"] else "")
                                   + ". Dissecação por auto = produto institucional."})

    # ── veredito (mesma régua do núcleo): grave só com DANO observado ──
    dano = (exp_ha >= EXP_GRAVE_HA and exp_pct >= EXP_GRAVE_PCT) or emb_on
    has_div = bool(div)
    res["verdict"] = "grave" if dano else ("divergente" if has_div else "conforme")
    if dano:
        res["grade"] = "grave"
    elif exp_ha >= 2.0 and exp_pct >= 2.0:
        res["grade"] = "degradando"
    elif c1 >= 50:
        res["grade"] = "consolidado"
    else:
        res["grade"] = "bom"
    res["resumo"] = (
        "Declaração compatível com o satélite — sem divergências relevantes na triagem."
        if not has_div else
        f"{len(div)} divergência(s): " + "; ".join(d["tipo"] for d in div[:3]) + ".")
    res["aviso"] = ("Apoio à decisão / triagem sobre dados públicos — NÃO é base oficial "
                    "certificada nem auto de infração. Sem dados do proprietário (LGPD).")
    return res


def main():
    args = [a for a in sys.argv[1:]]
    embargos = None
    if "--embargos" in args:
        i = args.index("--embargos"); embargos = args[i + 1]; del args[i:i + 2]
    if not args:
        print("uso: python examples/analyze_aoi.py <perimetro.geojson|.kml> [bioma] "
              "[--embargos <embargos_publicos.geojson>]\n"
              f"     bioma ∈ {sorted(RL_MIN_BIOMA)}")
        sys.exit(1)
    geom = load_geom(args[0])
    bioma = args[1] if len(args) > 1 else None
    print(json.dumps(analyze(geom, bioma=bioma, embargos=embargos), ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
