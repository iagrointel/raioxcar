# Raio-X CAR — núcleo aberto (open-core)

**A declaração do CAR bate com o satélite?**

Raio-X CAR confronta, **imóvel a imóvel**, o que o produtor **declarou no SICAR**
(APP, Reserva Legal, vegetação nativa, uso consolidado, hidrografia) com o que o
**satélite mostra hoje** — e emite um veredito (`conforme` · `divergente` · `grave`)
com o cálculo de APP/RL, a régua do estado e o **cruzamento embargo × perímetro**.

Tudo a partir de **dados abertos** — **sem Google Earth Engine e sem ArcGIS**.

> 🇧🇷 haCARthon · **Desafio 2** (dados geoespaciais do CAR) · iAgroIntel
> Apoio à decisão / **triagem institucional** — **não** é base oficial certificada nem auto de
> infração. Identidade do proprietário **não** é exibida (LGPD, sem CPF/CNPJ).

> 🇬🇧 **In one line:** X-ray *any* rural perimeter in Brazil against open satellite data — native
> vs. consolidated cover, post-2008 clearing, riparian buffers, and an **active-embargo overlay** —
> with **no account, no API key, and no Earth Engine**. Decision-support triage, not an official
> certificate.

---

## ⚡ Comece em 30 s — X-ray de qualquer perímetro (sem banco, sem chave)

Você traz **um polígono** (GeoJSON ou KML — baixe o perímetro de um CAR na
[consulta pública do SICAR](https://consultapublica.car.gov.br/publico/imoveis/index),
exporte um AOI do seu SIG, ou desenhe a área que quer investigar):

```bash
pip install -r requirements.txt
python examples/analyze_aoi.py examples/car_exemplo.geojson amazonia_floresta
```

Saída (veja [`examples/saida_exemplo.json`](examples/saida_exemplo.json) — perímetro real em Viseu/PA):

```jsonc
{
 "area_ha": 1270.2,
 "observado": { "nativa_pct": 30.8, "consolidada_pct": 69.2,
                "expansao_pos2008_ha": 649.1, "expansao_pos2008_pct": 51.1 },
 "verdict": "grave", "grade": "grave",
 "resumo": "3 divergência(s): Consolidada pós-2008 (não qualifica); ..."
}
```

> 🇬🇧 **No database required.** `analyze_aoi.py` takes a polygon and runs the *observed* side from
> public data only (MapBiomas COG + OpenStreetMap hydrography). The *declared* side at national
> scale is the service (below).

### Cruzamento Embargo × perímetro (a camada distinta do Raio-X)

O embargo do IBAMA/ICMBio/OEMAs é arquivado por auto e CPF — **nunca** pelo código do CAR.
Ligamos os dois por **sobreposição espacial**: a camada que nenhum sistema nacional conecta.

**Os polígonos de embargo são públicos** — você mesmo baixa e roda o cruzamento. Não dependem
da nossa base:

- IBAMA — **Áreas Embargadas**: <https://servicos.ibama.gov.br/ctf/publico/areasembargadas/> (shapefile/CSV)
- ICMBio e OEMAs — portais de transparência ambiental estaduais

Converta a camada pública para GeoJSON e passe em `--embargos` (saída **mínima e moat-safe**,
só *se há embargo* e *de qual órgão* — sem auto, sem CPF, sem área):

```bash
# baixe os polígonos públicos reais e aponte para eles:
python examples/analyze_aoi.py examples/car_exemplo.geojson amazonia_floresta \
       --embargos areas_embargadas_ibama.geojson
# → "embargo": { "on_property": true, "orgaos": ["IBAMA"] }

# (examples/embargos_exemplo.geojson é só ILUSTRATIVO, p/ ver o formato — não é dado real)
```

**Onde fica o nosso diferencial (não está neste repo):** o *método* é aberto e roda com dado
público; o que é o serviço é a **base nacional já cruzada** (~95 mil CARs com embargo ativo,
deduplicada e mantida atual), a **dissecação por auto** (data, infração, área, situação) e a
vinculação por CPF — o produto institucional. Método em **[docs/EMBARGO_X_CAR.md](docs/EMBARGO_X_CAR.md)**.

---

## Open-core: o que é aberto, o que é o diferencial

Este repositório abre o **método, o código e a documentação** — o suficiente para rodar
o fluxo sobre **um perímetro** a partir de dados públicos. Alinhado aos princípios de
**código aberto / Bem Público Digital** do edital.

| Aberto (este repo) | Diferencial da equipe (privado) |
|---|---|
| X-ray observado de **um** perímetro (MapBiomas, supressão pós-2008, APP, RL) | a **base nacional montada** (perímetros do CAR em PostGIS, 27 UFs) |
| **método** do cruzamento embargo × perímetro | a **base embargo×CAR montada** (~95 mil CARs com embargo ativo) |
| confronto declarado × observado, dossiê, régua de RL das 27 UFs | a **operação** contínua com SLA + ingestão das bases estaduais |

A reprodução do método é pública; o **ativo montado e a operação** são o serviço (B2G).

## Dois fluxos

| | `examples/analyze_aoi.py` (BYO-perímetro) | `examples/run_one.py` (institucional) |
|---|---|---|
| entrada | um polígono (GeoJSON/KML) que você traz | um `cod_imovel` do CAR |
| precisa de banco? | **não** | sim (`IAGRO_DSN` com perímetros + camadas SICAR) |
| confronta o **declarado** no SICAR? | não (só o observado) | **sim** |
| para quem | jornalista, MPF, ONG, pesquisador, qualquer dev | órgão ambiental com a base montada |

```bash
# fluxo institucional (precisa da base PostGIS):
cp .env.example .env        # preencha IAGRO_DSN — NÃO comite o .env
export $(grep -v '^#' .env | xargs)
python examples/run_one.py PA-1508308-8684020B3E93495987669D0F44B57C6E
```

## Como funciona (resumo)

Para cada perímetro, no **mesmo recorte** (registro perfeito):

1. **RGB atual** — composição multi-cena de Sentinel-2, céu limpo, com a data da cena.
2. **Pré-2008** — Landsat 30 m: prova o que já existia **antes do corte legal de 22/07/2008**.
3. **MapBiomas** — % nativa × % consolidada e o que surgiu **depois** de 2008 (consolidada falsa).
4. **APP** — hidrografia → faixa de 30 m ∩ perímetro.
5. **Embargo × perímetro** — sobreposição com embargos ativos (se você trouxer os polígonos).

**Régua de severidade (recalibrada):** `grave` exige **dano observado** — supressão pós-2008
(≥ 5 ha **e** ≥ 5%) **ou** embargo ativo. Pendências apenas **cadastrais** (APP/RL não averbada,
"consolidada onde há nativa") ficam em `divergente`. **Um imóvel preservado nunca é `grave` só por
papelada.** Detalhes em [`docs/METODO.md`](docs/METODO.md).

## Fontes de dados (abertas)

| Camada | Fonte |
|---|---|
| RGB atual | Sentinel-2 L2A · AWS / Element84 STAC |
| Pré-2008 | Landsat 4/5 C2 L2 · Microsoft Planetary Computer |
| Uso do solo / supressão | MapBiomas Coleção 9 (COG público) |
| Hidrografia → APP | IBGE BC250 (institucional) · OpenStreetMap (BYO, proxy público) |
| Embargo | transparência IBAMA / ICMBio / OEMAs (você traz os polígonos) |
| Regra de APP/RL | Código Florestal (Lei 12.651/2012) + legislação estadual por UF |

## Estrutura

```
engine/
  confront.py        # confronto declarado × observado → veredito (núcleo institucional)
  embargo_lookup.py  # cruzamento embargo × perímetro (helper)
  suggest.py         # geometria corrigida sugerida (KML/GeoJSON)
  render_stack.py    # camadas registradas (RGB/pré-2008/NDVI/MapBiomas/declarado)
  dossie.py          # dossiê por imóvel em PDF (hash SHA-256)
  api.py             # serviço FastAPI (endpoints por imóvel)
  per_uf_rules.json  # regras de RL/PRA/PRADA/CRA-PSA das 27 UFs, com citações
pipeline/
  aoi_analyze.py     # ★ X-ray BYO-perímetro, só dados públicos (sem banco)
  mapbiomas_cross.py # cruzamento MapBiomas (nativa/consolidada/pós-2008)
  crisp_rgb.py       # composição Sentinel-2 / Landsat sem nuvem
  fix_my_car.py      # diagnóstico de APP/RL (institucional)
examples/
  analyze_aoi.py     # ★ roda o X-ray sobre um polígono que você traz
  car_exemplo.geojson    # perímetro público de exemplo (Viseu/PA)
  embargos_exemplo.geojson
  saida_exemplo.json     # saída de exemplo (não precisa rodar p/ ver)
  run_one.py         # fluxo institucional (precisa de IAGRO_DSN)
docs/METODO.md  docs/EMBARGO_X_CAR.md
```

## Aviso

Os hectares agregados são **ordem de grandeza** (triagem); casos individuais são calculados pela
ferramenta. A acurácia certificada (Kappa 85–95%) é a etapa de piloto/validação de campo — não é
reivindicada aqui. **Sem CPF/CNPJ; sem dados do proprietário.**
