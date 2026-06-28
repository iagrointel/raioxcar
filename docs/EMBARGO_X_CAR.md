# Cruzamento Embargo × CAR — método aberto

> **Bem Público Digital.** Aqui está *o método* (não os dados): como ligar embargos
> ambientais ao perímetro do CAR por **sobreposição espacial**. Você traz os seus polígonos
> (de qualquer órgão), roda o cruzamento e obtém, por imóvel, os embargos ativos que incidem
> sobre ele. Nenhum dado de proprietário é distribuído neste repositório.

## O problema que isto resolve

No Brasil cada sistema fala sozinho. O embargo ambiental (IBAMA, ICMBio, OEMAs estaduais)
é arquivado por **auto de infração** e **CPF/CNPJ do autuado** — **nunca pelo código do CAR**.
Por isso ninguém responde, em massa, a pergunta mais simples da fiscalização:

> *Este imóvel declarado no CAR tem um embargo ativo sobre o seu perímetro?*

A resposta não está em nenhum campo — está na **geometria**. O embargo carrega o seu próprio
polígono (ou ponto); o CAR carrega o seu perímetro. Ligar os dois é uma **junção espacial**.

## O método (4 passos)

```
0. (origem)        polígonos/pontos de embargo, por órgão, em formatos heterogêneos
1. INGESTÃO        carregar cada fonte numa tabela PostGIS (SRID 4326)
2. NORMALIZAÇÃO    mapear os campos de cada fonte para um esquema comum + filtrar ATIVOS
3. CRUZAMENTO      ST_Intersects(embargo.geom, car.geom)  ← a "inteligência"
4. DISSECAÇÃO      por imóvel: auto, data, infração, área, situação
```

### 1. Ingestão
Cada órgão publica diferente (Shapefile, GeoJSON, WFS, CSV+lat/lon). Carregue tudo em
`EPSG:4326`. Polígonos (área embargada) **e** pontos (localização do embargo) servem — a
sobreposição funciona para ambos (`ST_Intersects` resolve polígono∩polígono e ponto∈polígono).

### 2. Normalização + filtro de ATIVOS (o passo honesto)
Cada fonte expõe o "ativo vs. desembargado" de um jeito. **Só conte embargos ativos** — o resto
é irrelevante e atacável. Regras observadas (adapte às suas fontes):

| Fonte | Campo de status | Regra de "ativo" |
|---|---|---|
| IBAMA | `status_norm` | `= 'ATIVO'` (descarta `DESEMBARGADO`) |
| Estado c/ tabela de desembargo | chave do processo | `processo NOT IN (desembargos)` |
| Estado c/ situação | `sit_embargo` | `LIKE 'EMBARG%'` (descarta `DESEMBARGADO`/`NÃO SE APLICA`) |
| Camada "áreas embargadas" publicada | — | ativa por natureza (documente a premissa) |

**Não misture auto de infração / multa com embargo.** Se a fonte é uma lista de *autos*
(ex.: multas), rotule `tipo = 'auto_infracao'` e **mantenha fora da contagem de embargos**.

Esquema comum sugerido (`emb_attr`):
`fonte · orgao · uf · tipo(embargo|auto_infracao) · autuado · data · infracao · area · processo · status · geom`

### 3. Cruzamento (a junção espacial)
Pré-requisitos de desempenho: índice GIST nas duas geometrias e **mesmo SRID**.

```sql
-- 1 linha por (imóvel, embargo que o sobrepõe)
CREATE TABLE car_embargo_active AS
SELECT c.cod_imovel, c.uf AS uf_car, e.gid AS emb_gid, e.fonte, e.tipo
FROM   emb_active e
JOIN   car_perimetro c        -- a sua camada de perímetros do CAR (SRID 4326, GIST)
  ON   ST_Intersects(c.geom, e.geom)
WHERE  e.tipo = 'embargo';
```

Dicas de escala (testado sobre ~7,4 M perímetros do CAR):
- **Faça a varredura dirigida pelos embargos** (conjunto menor) contra o índice GIST do CAR.
- **Particione** por `gid % N` e rode N processos em paralelo (junção espacial é "embaraçosamente paralela").
- **Saneie geometrias**: descarte coordenadas fora do bounding box do país (digitalização corrompida
  infla o envelope e arrasta a varredura para milhões de candidatos).

### 4. Dissecação por imóvel
Junte `car_embargo_active` de volta ao `emb_attr` por `(fonte, gid)` para, ao clicar num embargo,
mostrar o ato público completo: **auto, data, infração, área, situação**. Um imóvel que declara
"consolidada" mas carrega embargo ativo **sobe de prioridade** na triagem.

## Traga os seus polígonos
O cruzamento é agnóstico de fonte. Para incluir um novo órgão:
1. carregue a camada em PostGIS (4326);
2. acrescente um `INSERT ... SELECT` mapeando os campos dela para o esquema comum + a sua regra de "ativo";
3. recrie o índice GIST e rode o passo 3.

Pronto — os imóveis daquele estado passam a acender no mapa.

## LGPD / dado pessoal
As bases de embargo são **públicas e oficiais** (transparência ambiental). Este método é de
**reconciliação territorial**: cruza geometria com geometria. **Não use CPF/CNPJ para reidentificar**
e **não distribua dados de proprietário**. O nome do autuado, quando exibido, é o constante do
**próprio ato público** do órgão. Trate as páginas por imóvel como `noindex`.
