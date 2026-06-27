# Método — confronto declarado × observado

## 1. Recorte e camadas (por imóvel, registradas)
Definido o perímetro do imóvel (SICAR), todas as camadas são renderizadas na **mesma grade
UTM** (mesmo W×H), de modo que se sobrepõem sem desalinhar:
- **RGB atual** — Sentinel-2 L2A; busca as cenas mais recentes de céu limpo, mascara nuvem
  (banda SCL), tira a mediana por pixel → composição sem nuvem e sem falha de borda, **com a data**.
- **Pré-2008** — Landsat 4/5; o marco do Código Florestal é 22/07/2008.
- **NDVI** — (NIR−Red)/(NIR+Red), mediana mascarada por nuvem.
- **Declarado (SICAR)** — APP, Reserva Legal, vegetação nativa, área consolidada, hidrografia.

## 2. Cálculo de APP (hidrografia)
Para cada rio oficial que cruza o imóvel, faixa marginal do art. 4º (mín. 30 m):
```
APP devida = ST_Buffer(rio, 30 m) ∩ perímetro do imóvel     (fonte: IBGE BC250)
```
> Limite conhecido: a hidrografia oficial nacional (BC250, 1:250.000) é grossa em escala de
> imóvel e pode subestimar córregos finos; o piloto prevê drenagem fina por DEM.

## 3. Cálculo de Reserva Legal (mínimo por bioma)
Percentual conforme bioma / Amazônia Legal: **80%** floresta (Amaz. Legal), **35%** cerrado
(Amaz. Legal), **20%** demais casos.
```
RL mínima (ha) = área × percentual do bioma
déficit de RL (ha) = max(0, RL mínima − RL declarada)
```
A regra por UF (PRA/PRADA/CRA-PSA/OEMA) e a base legal citada estão em `engine/per_uf_rules.json`.

## 4. Divergências e veredito
- **APP omitida** — rio cruza, buffer ∩ perímetro não declarado como APP.
- **"Consolidada" pós-2008** — uso declarado como consolidado que só aparece depois de 22/07/2008.
- **Uso não declarado** — área aberta observada que a declaração não reconhece.
- **Déficit de Reserva Legal** — RL declarada abaixo do mínimo do bioma.

Veredito do imóvel = agregado: qualquer item grave → `grave`; senão `divergente`; senão `conforme`.

## 5. Saída
- Veredito + métricas (JSON).
- Geometria corrigida sugerida (KML/GeoJSON) — `suggest.py`.
- Dossiê por imóvel em PDF com carimbo de tempo e **hash SHA-256** — `dossie.py`.

Tudo de dado aberto, sem Google Earth Engine e sem ArcGIS.
