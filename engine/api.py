#!/usr/bin/env python3
"""Raio-X CAR · API (FastAPI) — own thin service for the Desafio-2 prototype.
Open data only (no GEE/ArcGIS). No enterprise auth. Reuses the engine:
  /api/car/{cod}/analise        → confront() verdict JSON (declared × satellite)
  /api/car/{cod}/declared.geojson → declared SICAR layers + derived overlays (for the map)
  /api/car/{cod}/rgb?when=..     → real Sentinel-2 RGB PNG (before/after), cached
  /api/car/{cod}/sugestao.geojson|.kml → corrected geometry (job 2)
  /api/batch                     → MATOPIBA 800 precomputed results
Run: IAGRO_DSN=postgresql://... uvicorn api:app --host 127.0.0.1 --port 8091
"""
from __future__ import annotations
import os, sys, json, re
from pathlib import Path
from fastapi import FastAPI, HTTPException, Body
from fastapi.responses import JSONResponse, FileResponse, PlainTextResponse
from fastapi.middleware.cors import CORSMiddleware

sys.path.insert(0, os.path.join(os.path.dirname(__file__),"..","pipeline"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__),"..","pipeline"))
sys.path.insert(0, str(Path(__file__).parent))
import confront as _confront
import suggest as _suggest
import sentinel_rgb
import landsat_rgb
import crisp_rgb
import dossie as _dossie
import render_stack as _stack
import car_layer_pipeline as clp

DSN = os.environ.get("IAGRO_DSN",
    "postgresql://USER:SENHA@HOST:5432/iagro_sat")
CACHE = Path(os.environ.get("RAIOX_CACHE", str(Path(__file__).parent / "cache")))
CACHE.mkdir(parents=True, exist_ok=True)
BATCH = Path(__file__).parent / "batch_results.json"
WIN = {"before": "2018-01-01/2019-12-31", "after": "2025-04-01/2026-06-27"}

app = FastAPI(title="Raio-X CAR API", version="1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

def _safe(cod: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_.\-]{6,80}", cod or ""):
        raise HTTPException(400, "cod_imovel inválido")
    return cod

def _cdir(cod: str) -> Path:
    d = CACHE / cod; d.mkdir(parents=True, exist_ok=True); return d

@app.get("/health")
def health(): return {"ok": True, "dsn_set": bool(DSN), "batch": BATCH.exists()}

@app.get("/api/car/{cod}/analise")
def analise(cod: str):
    cod = _safe(cod); f = _cdir(cod) / "analise.json"
    if f.exists():
        return JSONResponse(json.loads(f.read_text()))
    try:
        r = _confront.confront(cod, DSN)
    except ValueError as e:
        raise HTTPException(404, str(e))
    except Exception as e:
        raise HTTPException(500, f"erro na análise: {e}")
    f.write_text(json.dumps(r, ensure_ascii=False))
    return JSONResponse(r)

@app.get("/api/car/{cod}/declared.geojson")
def declared(cod: str):
    cod = _safe(cod); f = _cdir(cod) / "declared.geojson"
    if f.exists():
        return JSONResponse(json.loads(f.read_text()))
    feats = []
    for table, color, alpha, label in clp.LAYER_SPECS:
        try:
            geoms = clp.load_layer_geoms(DSN, table, cod)
        except Exception:
            geoms = []
        for g in geoms or []:
            feats.append({"type": "Feature",
                          "properties": {"camada": label, "tabela": table, "color": color, "fonte": "declarado"},
                          "geometry": g})
    # derived overlays (observed/derived) from confront geo
    try:
        a = json.loads((_cdir(cod) / "analise.json").read_text()) if (_cdir(cod)/"analise.json").exists() \
            else _confront.confront(cod, DSN)
        geo = a.get("geo", {})
        if geo.get("perimetro"):
            feats.append({"type": "Feature", "properties": {"camada": "Perímetro CAR", "color": "#ff00ff", "fonte": "perimetro"}, "geometry": geo["perimetro"]})
        for rg in (geo.get("rios") or []):
            feats.append({"type": "Feature", "properties": {"camada": "Rio oficial (IBGE)", "color": "#1e90ff", "fonte": "derivado"}, "geometry": rg})
        if geo.get("app_devida"):
            feats.append({"type": "Feature", "properties": {"camada": "APP devida (satélite)", "color": "#ff2d2d", "fonte": "derivado"}, "geometry": geo["app_devida"]})
    except Exception:
        pass
    fc = {"type": "FeatureCollection", "features": feats}
    f.write_text(json.dumps(fc))
    return JSONResponse(fc)

@app.get("/api/car/{cod}/rgb")
def rgb(cod: str, when: str = "after"):
    cod = _safe(cod)
    if when not in ("before", "after"): raise HTTPException(400, "when=before|after")
    out = _cdir(cod) / f"rgb_{when}.png"
    if not out.exists():
        try:
            # CRISP cloud-free, gap-free composite (no black tile-edges) — open data only
            sensor = "landsat" if when == "before" else "s2"
            crisp_rgb.render(cod, DSN, str(out), sensor=sensor, perimeter=True)
        except Exception as e:
            raise HTTPException(502, f"sem cena ({when}): {e}")
    return FileResponse(out, media_type="image/png")

@app.get("/api/car/{cod}/sugestao.geojson")
def sug_geo(cod: str):
    cod = _safe(cod)
    try:
        return JSONResponse(_suggest.correction_featurecollection(cod, DSN))
    except ValueError as e:
        raise HTTPException(404, str(e))

@app.get("/api/car/{cod}/sugestao.kml")
def sug_kml(cod: str):
    cod = _safe(cod); out = _cdir(cod) / "sugestao.kml"
    if not out.exists():
        _suggest.correction_kml(cod, DSN, str(out))
    return FileResponse(out, media_type="application/vnd.google-earth.kml+xml", filename=f"{cod}_correcao.kml")

@app.get("/api/car/{cod}/stack")
def stack(cod: str):
    cod = _safe(cod); mf = _cdir(cod) / "stack.json"
    if mf.exists():
        return JSONResponse(json.loads(mf.read_text()))
    try:
        return JSONResponse(_stack.render_stack(cod, DSN))
    except ValueError as e:
        raise HTTPException(404, str(e))
    except Exception as e:
        raise HTTPException(500, f"erro no stack: {e}")

@app.get("/api/car/{cod}/stack/{layer}.png")
def stack_layer(cod: str, layer: str):
    cod = _safe(cod)
    if not re.fullmatch(r"[a-z0-9_]{3,30}", layer or ""): raise HTTPException(400, "layer")
    p = _cdir(cod) / "stack" / f"{layer}.png"
    if not p.exists():
        if not (_cdir(cod) / "stack.json").exists():
            try: _stack.render_stack(cod, DSN)
            except Exception as e: raise HTTPException(500, f"erro: {e}")
    if not p.exists(): raise HTTPException(404, "layer indisponível")
    return FileResponse(p, media_type="image/png")

@app.get("/api/car/{cod}/dossie.pdf")
def dossie(cod: str):
    cod = _safe(cod)
    try:
        out = _dossie.build(cod, DSN)
    except Exception as e:
        raise HTTPException(500, f"erro no dossiê: {e}")
    return FileResponse(out, media_type="application/pdf", filename=f"raiox_{cod}.pdf")

@app.get("/api/car/{cod}/dossie_preview.png")
def dossie_preview(cod: str):
    """Render the dossiê PDF pages to a single stitched PNG (visible inline/on video)."""
    cod = _safe(cod); cd = _cdir(cod); pdf = cd / "dossie.pdf"; png = cd / "dossie_preview.png"
    if png.exists():
        return FileResponse(png, media_type="image/png")
    try:
        if not pdf.exists(): _dossie.build(cod, DSN)
        import subprocess, glob
        subprocess.run(["pdftoppm", "-png", "-r", "95", str(pdf), str(cd / "dosp")], check=False)
        pages = sorted(glob.glob(str(cd / "dosp-*.png")))
        if not pages: raise RuntimeError("sem páginas")
        from PIL import Image
        ims = [Image.open(p).convert("RGB") for p in pages]
        w = max(i.width for i in ims)
        ims = [i if i.width == w else i.resize((w, int(i.height * w / i.width))) for i in ims]
        H = sum(i.height for i in ims) + 14 * (len(ims) - 1)
        canvas = Image.new("RGB", (w, H), (228, 234, 228)); y = 0
        for im in ims: canvas.paste(im, (0, y)); y += im.height + 14
        canvas.save(png)
    except Exception as e:
        raise HTTPException(500, f"erro no preview: {e}")
    return FileResponse(png, media_type="image/png")

@app.get("/api/batch")
def batch():
    if not BATCH.exists(): return JSONResponse({"gerado": False, "imoveis": []})
    return JSONResponse(json.loads(BATCH.read_text()))

# ── analyst case workflow (the workstation) ──
CASES = Path(__file__).parent / "cases.json"
STATUSES = ["a_triar", "exigir", "em_correcao", "aprovar", "concluido"]
def _cases():
    try: return json.loads(CASES.read_text())
    except Exception: return {}
def _save_cases(d): CASES.write_text(json.dumps(d, ensure_ascii=False))

@app.post("/api/case/{cod}")
def set_case(cod: str, payload: dict = Body(default={})):
    cod = _safe(cod)
    st = payload.get("status", "a_triar")
    if st not in STATUSES: raise HTTPException(400, f"status inválido (use {STATUSES})")
    d = _cases()
    prev = d.get(cod, {})
    # enrich from cached analise if present
    a = {}
    aj = _cdir(cod) / "analise.json"
    if aj.exists():
        try: a = json.loads(aj.read_text())
        except Exception: a = {}
    d[cod] = {"cod": cod, "status": st, "nota": payload.get("nota", prev.get("nota", "")),
              "uf": a.get("uf", prev.get("uf")), "municipio": a.get("municipio", prev.get("municipio")),
              "verdict": a.get("verdict", prev.get("verdict")), "area_ha": a.get("area_ha", prev.get("area_ha")),
              "atualizado": payload.get("ts", prev.get("atualizado", ""))}
    _save_cases(d)
    return JSONResponse({"ok": True, "case": d[cod]})

@app.get("/api/cases")
def list_cases():
    d = _cases()
    from collections import Counter
    return JSONResponse({"statuses": STATUSES, "por_status": dict(Counter(c.get("status") for c in d.values())),
                         "casos": list(d.values())})

@app.get("/api/uf/{uf}/rules")
def uf_rules(uf: str):
    f = Path(__file__).parent / "per_uf_rules.json"
    if not f.exists(): raise HTTPException(404, "regras não geradas")
    r = json.loads(f.read_text()).get("uf", {}).get((uf or "").upper())
    if not r: raise HTTPException(404, "UF não encontrada")
    return JSONResponse(r)

@app.get("/api/national")
def national():
    f = Path(__file__).parent / "national_54.json"
    if not f.exists(): return JSONResponse({"gerado": False, "imoveis": []})
    return JSONResponse(json.loads(f.read_text()))
