# Raio-X CAR — núcleo aberto (open-core)

**A declaração do CAR bate com o satélite?**

Raio-X CAR é um verificador que confronta, **imóvel a imóvel**, o que o produtor
**declarou no SICAR** (APP, Reserva Legal, vegetação nativa, uso consolidado, hidrografia)
com o que o **satélite mostra hoje** — e emite um veredito (`conforme` · `divergente` · `grave`)
com o cálculo de APP/RL e a regra do estado.

Tudo a partir de **dados abertos** — **sem Google Earth Engine e sem ArcGIS** — portanto
reproduzível de ponta a ponta a partir de fontes públicas.

> haCARthon · Desafio 2 (dados geoespaciais do CAR) · Equipe 201 · iAgroIntel
> Apoio à decisão / triagem — **não** constitui base oficial certificada nem auto de infração.
> Identidade do proprietário não é exibida (LGPD).

---

## Open-core: o que é aberto, o que é o diferencial

Este repositório abre o **método, o código e a documentação** — o suficiente para rodar
o fluxo sobre **um imóvel** a partir de dados públicos. Alinhado aos princípios de
**código aberto / Bem Público Digital** do edital.

| Aberto (este repo) | Diferencial da equipe (privado) |
|---|---|
| método de confronto declarado × observado | a **base nacional montada** (perímetros do CAR em PostGIS) |
| código do núcleo (confronto, APP/RL, dossiê, camadas) | a **operação** contínua com SLA e cobertura das 27 UFs |
| regras de Reserva Legal dos 27 estados (`engine/per_uf_rules.json`) | ingestão/curadoria das bases estaduais |

A reprodução do método é pública; o **ativo montado e a operação** são o serviço (B2G).

---

## Como funciona (resumo)

Para cada imóvel, no **mesmo recorte** (registro perfeito, sem desalinhar):

1. **RGB atual** — composição multi-cena de Sentinel-2, céu limpo, **com a data** da cena mais recente.
2. **Pré-2008** — Landsat 30 m: prova o que já existia **antes do corte legal de 22/07/2008**.
3. **NDVI** — vigor da vegetação (separa floresta de pasto/cultivo).
4. **Declarado (SICAR)** — camadas do imóvel sobrepostas.

O confronto cruza o observado com o declarado + a hidrografia oficial (rio → APP de 30 m)
e aponta as divergências: **APP omitida**, **"consolidada" pós-2008**, **uso não declarado**,
**déficit de Reserva Legal** — com hectares, cálculo e a base legal do estado.

Detalhes em [`docs/METODO.md`](docs/METODO.md).

## Fontes de dados (abertas)

| Camada | Fonte |
|---|---|
| RGB atual | Sentinel-2 L2A · AWS / Element84 STAC (`earth-search.aws.element84.com/v1`) |
| Pré-2008 | Landsat 4/5 C2 L2 · Microsoft Planetary Computer |
| Uso do solo | MapBiomas (COG) |
| Hidrografia → APP | IBGE BC250 |
| Declarado | SICAR (camadas do imóvel) |
| Regra de APP/RL | Código Florestal (Lei 12.651/2012) + legislação estadual citada por UF |

## Estrutura

```
engine/
  confront.py        # confronto declarado × observado → veredito (núcleo)
  suggest.py         # geometria corrigida sugerida (APP devida, KML/GeoJSON)
  render_stack.py    # camadas registradas (RGB atual/pré-2008/NDVI/MapBiomas/declarado)
  dossie.py          # dossiê por imóvel em PDF (hash SHA-256, imagens, APP/RL)
  api.py             # serviço FastAPI (endpoints por imóvel)
  per_uf_rules.json  # regras de RL/PRA/PRADA/CRA-PSA das 27 UFs, com citações
  uf_rules_parts/    # fontes por região
pipeline/
  crisp_rgb.py       # composição Sentinel-2 / Landsat sem nuvem e sem falha de borda
  landsat_rgb.py     # Landsat pré-2008
  mapbiomas_cross.py # cruzamento MapBiomas
  fix_my_car.py      # diagnóstico de APP/RL
  car_layer_pipeline.py # leitura das camadas declaradas (SICAR)
examples/run_one.py  # roda o confronto sobre um único CAR
docs/METODO.md
```

## Rodando

Requer Python 3.10+, PostGIS com os perímetros e camadas do CAR, e as libs:
`fastapi uvicorn rasterio pystac-client planetary-computer shapely pyproj numpy matplotlib weasyprint`.

```bash
cp .env.example .env        # preencha IAGRO_DSN (sua base PostGIS) — NÃO comite o .env
export $(grep -v '^#' .env | xargs)
python examples/run_one.py PA-1508308-8684020B3E93495987669D0F44B57C6E
```

Saída: o veredito em JSON (divergências, APP/RL, datas). Os geradores de imagem/dossiê
escrevem em `RAIOX_CACHE`.

## Aviso

Os hectares agregados são **ordem de grandeza** (triagem); casos individuais são calculados
pela ferramenta. A acurácia certificada (Kappa 85–95% por matriz de confusão) é a etapa de
piloto/validação de campo — não é reivindicada aqui.
