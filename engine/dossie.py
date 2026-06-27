#!/usr/bin/env python3
"""Raio-X CAR · dossie — per-property PDF (weasyprint, no browser).
Timestamp + SHA-256 hash, verdict, divergences, APP/RL calculation, before/after composites."""
from __future__ import annotations
import os, sys, json, hashlib, base64
from datetime import datetime, timezone
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent)); sys.path.insert(0, os.path.join(os.path.dirname(__file__),"..","pipeline"))
import confront as _confront
from weasyprint import HTML

CACHE = Path(os.environ.get("RAIOX_CACHE", str(Path(__file__).parent / "cache")))
PAPER="#F4F1E9"; INK="#16261D"; GREEN="#2E6B45"; GOLD="#9A6B1E"; RED="#9c2b2b"; LINE="rgba(22,38,29,.16)"
VCOL={"conforme":GREEN,"divergente":GOLD,"grave":RED}

def _img(p):
    return ("data:image/png;base64,"+base64.b64encode(Path(p).read_bytes()).decode()) if Path(p).exists() else ""

def _decl_over(cdir):
    """Composite the declared SICAR overlay on top of the recent RGB (registered, same grid)."""
    base = cdir/"stack"/"rgb_recente.png"; ov = cdir/"stack"/"declarado.png"
    if not base.exists(): return ""
    try:
        from PIL import Image
        b = Image.open(base).convert("RGBA")
        if ov.exists():
            o = Image.open(ov).convert("RGBA").resize(b.size)
            b = Image.alpha_composite(b, o)
        out = cdir/"stack"/"_decl_over.png"; b.convert("RGB").save(out)
        return _img(out)
    except Exception:
        return _img(base)

def build(cod: str, dsn: str) -> str:
    cdir = CACHE / cod; cdir.mkdir(parents=True, exist_ok=True)
    aj = cdir / "analise.json"
    A = json.loads(aj.read_text()) if aj.exists() else _confront.confront(cod, dsn)
    if not aj.exists(): aj.write_text(json.dumps(A, ensure_ascii=False))
    o = A.get("observado") or {}; d = A.get("declarado") or {}; c = A.get("calc") or {}
    man = {}
    mj = cdir / "stack.json"
    if mj.exists():
        try: man = json.loads(mj.read_text())
        except Exception: man = {}
    recent_date = man.get("recent_date"); ndvi_val = man.get("ndvi")
    ts = datetime.now(timezone.utc).astimezone().strftime("%d/%m/%Y %H:%M:%S %Z")
    h = hashlib.sha256(f"{cod}|{ts}|{A.get('verdict')}|{c.get('app_devida_ha')}|{c.get('rl_deficit_ha')}|{o.get('expansao_pos2008_ha')}|{recent_date}|{ndvi_val}".encode()).hexdigest()
    vcol = VCOL.get(A.get("verdict"), INK)
    before, after = _img(cdir/"rgb_before.png"), _img(cdir/"rgb_after.png")
    divs = "".join(
        f"<tr><td><b>{x['tipo']}</b>{(' · '+str(x['ha'])+' ha') if x.get('ha') else ''}</td><td>{x['detalhe']}</td></tr>"
        for x in A.get("divergencias", [])) or "<tr><td colspan=2>Sem divergências relevantes — declaração compatível com o satélite.</td></tr>"
    imgs = ""
    if before or after:
        imgs = f"""<div class='sec'>Mudança no tempo — corte de 22/07/2008</div><div class='ba'>
          {f"<figure><img src='{before}'><figcaption>2008 · pré-corte (Landsat, sem nuvem)</figcaption></figure>" if before else ""}
          {f"<figure><img src='{after}'><figcaption>hoje (Sentinel-2, sem nuvem)</figcaption></figure>" if after else ""}
        </div>"""
    # full registered-layer gallery (all the evidence images inside the PDF)
    g_2008 = _img(cdir/"stack"/"rgb_2008.png"); g_decl = _decl_over(cdir)
    g_mb = _img(cdir/"stack"/"mapbiomas.png"); g_mb08 = _img(cdir/"stack"/"mapbiomas_2008.png"); g_ndvi = _img(cdir/"stack"/"ndvi.png")
    cells = []
    if g_decl: cells.append((g_decl, "Declarado (SICAR) sobre satélite"))
    if g_2008: cells.append((g_2008, "Pré-2008 (Landsat 30 m)"))
    if g_mb08: cells.append((g_mb08, "MapBiomas 2008 — uso do solo"))
    if g_mb:   cells.append((g_mb,   "MapBiomas 2023 — uso do solo"))
    if g_ndvi: cells.append((g_ndvi, f"NDVI — vigor{(' · médio ' + str(ndvi_val)) if ndvi_val is not None else ''}"))
    gallery = ""
    if cells:
        figs = "".join(f"<figure><img src='{src}'><figcaption>{cap}</figcaption></figure>" for src, cap in cells)
        gallery = f"<div class='sec'>Camadas analisadas{(' · RGB atual ' + recent_date) if recent_date else ''}</div><div class='gal'>{figs}</div>"
    html = f"""<html><head><meta charset='utf-8'><style>
    @page{{size:A4;margin:16mm 15mm}}*{{margin:0;box-sizing:border-box}}
    body{{font-family:'DejaVu Sans',Arial,sans-serif;color:{INK};font-size:10.5pt}}
    .mast{{display:flex;justify-content:space-between;border-bottom:1.5pt solid {INK};padding-bottom:6pt;font-family:'DejaVu Sans Mono',monospace;font-size:8pt;letter-spacing:1px;color:{GREEN}}}
    h1{{font-family:'DejaVu Serif',Georgia,serif;font-size:20pt;margin:10pt 0 2pt}}
    .loc{{color:rgba(22,38,29,.6);font-size:10pt;margin-bottom:8pt}}
    .badge{{display:inline-block;padding:4pt 12pt;border-radius:14pt;background:{vcol};color:#fff;font-weight:bold;font-size:11pt}}
    .sec{{font-family:'DejaVu Sans Mono',monospace;font-size:8.5pt;letter-spacing:1.5px;text-transform:uppercase;color:{GOLD};margin:14pt 0 5pt}}
    .kpis{{display:flex;gap:8pt}}.kpis .k{{flex:1;background:#FBFAF5;border:1pt solid {LINE};border-radius:3mm;padding:7pt}}
    .k .n{{font-size:15pt;font-weight:bold}}.k .l{{font-size:7.5pt;color:rgba(22,38,29,.6)}}
    table{{width:100%;border-collapse:collapse;font-size:9.5pt}}td{{border-bottom:1pt solid {LINE};padding:4pt 5pt;vertical-align:top}}
    .calc td:first-child{{color:rgba(22,38,29,.65);width:55%}}.calc td:last-child{{text-align:right;font-weight:bold}}
    .ba{{display:flex;gap:8pt;margin-top:4pt}}.ba figure{{flex:1;margin:0}}.ba img{{width:100%;border:1pt solid {LINE};border-radius:2mm}}
    .ba figcaption{{font-size:8pt;color:rgba(22,38,29,.6);text-align:center;margin-top:2pt}}
    .gal{{display:flex;flex-wrap:wrap;gap:8pt;margin-top:4pt}}.gal figure{{width:48%;margin:0}}
    .gal img{{width:100%;border:1pt solid {LINE};border-radius:2mm}}.gal figcaption{{font-size:8pt;color:rgba(22,38,29,.6);text-align:center;margin-top:2pt}}
    .foot{{margin-top:14pt;border-top:1pt solid {LINE};padding-top:6pt;font-family:'DejaVu Sans Mono',monospace;font-size:7pt;color:rgba(22,38,29,.55);line-height:1.5}}
    </style></head><body>
    <div class='mast'><span>RAIO-X CAR · VERIFICAÇÃO DE IMÓVEL</span><span>{ts}</span></div>
    <h1>{cod}</h1><div class='loc'>{A.get('municipio','')} / {A.get('uf','')} · {A.get('area_ha')} ha · {A.get('mf_classe','')} · bioma {A.get('bioma','')}</div>
    <span class='badge'>{(A.get('verdict') or '').upper()}</span> &nbsp; <span style='color:rgba(22,38,29,.6)'>grade: {A.get('grade','')} — {A.get('resumo','')}</span>
    <div class='sec'>Declarado × Observado (satélite)</div>
    <div class='kpis'><div class='k'><div class='n'>{d.get('rl_pct','—')}%</div><div class='l'>RL declarada (mín. {A.get('rl_min_pct','—')}%)</div></div>
     <div class='k'><div class='n'>{o.get('nativa_pct','—')}%</div><div class='l'>nativa observada</div></div>
     <div class='k'><div class='n'>{o.get('consolidada_pct','—')}%</div><div class='l'>uso consolidado obs.</div></div>
     <div class='k'><div class='n'>{o.get('expansao_pos2008_ha','—')}</div><div class='l'>ha de uso pós-2008</div></div></div>
    <div class='sec'>Divergências</div><table>{divs}</table>
    <div class='sec'>Cálculo APP &amp; Reserva Legal</div>
    <table class='calc'>
     <tr><td>Rios oficiais cruzando ({c.get('fonte_rios','IBGE BC250')})</td><td>{c.get('rios_cruzam','—')}</td></tr>
     <tr><td>APP devida = buffer {c.get('app_regra_m',30)} m ∩ perímetro</td><td>{c.get('app_devida_ha','—')} ha</td></tr>
     <tr><td>RL mínima ({A.get('bioma','')}, {c.get('rl_min_pct','—')}%)</td><td>{c.get('rl_min_ha','—')} ha</td></tr>
     <tr><td>RL declarada</td><td>{c.get('rl_declarada_ha','—')} ha</td></tr>
     <tr><td>Déficit de RL</td><td>{c.get('rl_deficit_ha','—')} ha</td></tr></table>
    {imgs}
    {gallery}
    <div class='foot'>Dado aberto: Sentinel-2 (AWS) · Landsat-5 (Planetary Computer) · MapBiomas Col.9 (2023) · hidrografia IBGE BC250 · SICAR.
    Composição multi-cena sem nuvem. Apoio à decisão / triagem — não constitui base oficial certificada nem auto de infração.
    Identidade do proprietário não exibida (LGPD).<br>SHA-256: {h}<br>Gerado por Raio-X CAR · iAgroSat × iAgroIntel · {ts}</div>
    </body></html>"""
    out = cdir / "dossie.pdf"; HTML(string=html).write_pdf(out)
    return str(out)

if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(); ap.add_argument("cod"); ap.add_argument("--dsn", required=True)
    a = ap.parse_args(); print(build(a.cod, a.dsn))
