# Raio-X CAR — open core

[🇧🇷 Português](README.md) · **🇬🇧 English**

**Does the rural land registry (CAR) declaration match the satellite?**

Raio-X CAR confronts, **property by property**, what the landholder **declared in SICAR**
(riparian buffers/APP, Legal Reserve, native vegetation, consolidated use, hydrography) with
what the **satellite shows today** — and issues a verdict (`conforme` · `divergente` · `grave`,
i.e. compliant · divergent · serious) together with the APP/Legal-Reserve calculation, the
state rule, and the **embargo × perimeter** overlay.

All from **open data** — **no Google Earth Engine, no ArcGIS**.

> 🇧🇷 haCARthon · **Challenge 2** (CAR geospatial data) · iAgroIntel
> Decision support / **institutional triage** — **not** an official certificate nor an
> infraction notice. The owner's identity is **never** shown (LGPD: no CPF/CNPJ / personal IDs).

*(CAR = Cadastro Ambiental Rural, Brazil's Rural Environmental Registry. SICAR is its official
system. APP = Área de Preservação Permanente, legally protected riparian/hillside buffers.
Legal Reserve = a % of native vegetation each property must keep, by biome.)*

---

## 🛰️ Map mode — clone, **one command**, investigate in your browser

```bash
pip install -r requirements.txt
python -m webapp.server          # opens http://127.0.0.1:8055
```

A **satellite map of Brazil** (Esri · Sentinel-2 cloudless · OSM) where you **✏️ draw** a polygon,
**📂 import** a KML/GeoJSON, or **🔍 search** a place → click **Analisar** → verdict + % native/
consolidated + **post-2008 clearing** + APP + **before × after satellite (2008 × today)**.
All open data, **no database and no key** — analyzes **one perimeter at a time** (the one you bring).

---

## ⚡ Or via command line — X-ray any perimeter (no database, no key)

You bring **one polygon** (GeoJSON or KML — download a CAR perimeter from the
[SICAR public consultation](https://consultapublica.car.gov.br/publico/imoveis/index),
export an AOI from your GIS, or draw the area you want to investigate):

```bash
pip install -r requirements.txt
python examples/analyze_aoi.py examples/car_exemplo.geojson amazonia_floresta
```

Output (see [`examples/saida_exemplo.json`](examples/saida_exemplo.json) — a real perimeter in Viseu/PA):

```jsonc
{
 "area_ha": 1270.2,
 "observado": { "nativa_pct": 30.8, "consolidada_pct": 69.2,
                "expansao_pos2008_ha": 649.1, "expansao_pos2008_pct": 51.1 },
 "verdict": "grave", "grade": "grave",
 "resumo": "3 divergência(s): post-2008 consolidated use (does not qualify); ..."
}
```

**No database required.** `analyze_aoi.py` takes a polygon and runs the *observed* side from
public data only (MapBiomas COG + OpenStreetMap hydrography). The *declared* side at national
scale is the service (below).

### Embargo × perimeter overlay (Raio-X's distinctive layer)

IBAMA/ICMBio/state-agency embargoes are filed by infraction notice and CPF — **never** by the
CAR code. We connect the two by **spatial overlap**: the layer no national system links.

**The embargo polygons are public** — you download them and run the cross yourself. They do not
depend on our base:

- IBAMA — **Embargoed Areas**: <https://servicos.ibama.gov.br/ctf/publico/areasembargadas/> (shapefile/CSV)
- ICMBio and state environmental agencies — public transparency portals

Convert the public layer to GeoJSON and pass it to `--embargos` (output is **minimal and
moat-safe** — only *whether* there is an embargo and *which agency*; no notice number, no CPF, no area):

```bash
python examples/analyze_aoi.py examples/car_exemplo.geojson amazonia_floresta \
       --embargos areas_embargadas_ibama.geojson
# → "embargo": { "on_property": true, "orgaos": ["IBAMA"] }
# (examples/embargos_exemplo.geojson is ILLUSTRATIVE only — not real data)
```

**Where our edge is (not in this repo):** the *method* is open and runs on public data; the
*service* is the **already-assembled national cross** (~95k CARs with an active embargo,
deduplicated and kept current), the **per-notice dissection** (date, infraction, area, status)
and the CPF linkage — the institutional product. Method in [docs/EMBARGO_X_CAR.md](docs/EMBARGO_X_CAR.md).

---

## Open core: what is open, what is the edge

This repository opens the **method, the code and the documentation** — enough to run the flow on
**one perimeter** from public data. Aligned with the call's **open-source / Digital Public Good** principles.

| Open (this repo) | Team's edge (private) |
|---|---|
| Observed X-ray of **one** perimeter (MapBiomas, post-2008 clearing, APP, Legal Reserve) | the **assembled national base** (CAR perimeters in PostGIS, 27 states) |
| the **method** of the embargo × perimeter cross | the **assembled embargo×CAR base** (~95k CARs with active embargo) |
| declared × observed confront, dossier, 27-state Legal-Reserve ruleset | the continuous **operation** with SLA + state-base ingestion |

The method is reproducible publicly; the **assembled asset and the operation** are the service (B2G).

## Two flows

| | `examples/analyze_aoi.py` (bring-your-own perimeter) | `examples/run_one.py` (institutional) |
|---|---|---|
| input | a polygon (GeoJSON/KML) you bring | a CAR property code (`cod_imovel`) |
| needs a database? | **no** | yes (`IAGRO_DSN` with perimeters + SICAR layers) |
| confronts the **declared** SICAR layers? | no (observed only) | **yes** |
| for whom | journalists, prosecutors, NGOs, researchers, any dev | an environmental agency with the assembled base |

```bash
# institutional flow (needs the PostGIS base):
cp .env.example .env        # fill IAGRO_DSN — do NOT commit .env
export $(grep -v '^#' .env | xargs)
python examples/run_one.py PA-1508308-8684020B3E93495987669D0F44B57C6E
```

## How it works (summary)

For each perimeter, in the **same footprint** (perfect registration):

1. **Current RGB** — multi-scene Sentinel-2 composite, clear sky, with the scene date.
2. **Pre-2008** — Landsat 30 m: proves what already existed **before the 22 Jul 2008 legal cutoff**.
3. **MapBiomas** — % native vs % consolidated, and what appeared **after** 2008 (false "consolidated").
4. **APP** — hydrography → 30 m buffer ∩ perimeter.
5. **Embargo × perimeter** — overlap with active embargoes (if you bring the polygons).

**Severity rule (recalibrated):** `grave` requires **observed damage** — post-2008 clearing
(≥ 5 ha **and** ≥ 5%) **or** an active embargo. Purely **cadastral** pendencies (un-registered
APP/Legal Reserve, "consolidated where native vegetation stands") stay at `divergente`.
**A well-preserved property is never `grave` over paperwork alone.** Details in [docs/METODO.md](docs/METODO.md).

## Data sources (all open)

| Layer | Source |
|---|---|
| Current RGB | Sentinel-2 L2A · AWS / Element84 STAC |
| Pre-2008 | Landsat 4/5 C2 L2 · Microsoft Planetary Computer |
| Land use / clearing | MapBiomas Collection 9 (public COG) |
| Hydrography → APP | IBGE BC250 (institutional) · OpenStreetMap (BYO, public proxy) |
| Embargo | IBAMA / ICMBio / state agencies transparency (you bring the polygons) |
| APP/Legal-Reserve rule | Forest Code (Law 12.651/2012) + per-state legislation |

## Disclaimer

Aggregate hectares are **order-of-magnitude** (triage); individual cases are computed by the tool.
Certified accuracy (Kappa 85–95% via confusion matrix) is the pilot / field-validation stage —
not claimed here. **No CPF/CNPJ; no owner data.**
