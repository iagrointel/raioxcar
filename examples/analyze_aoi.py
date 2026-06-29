#!/usr/bin/env python3
"""X-ray de QUALQUER perímetro do Brasil a partir de dados públicos — sem banco, sem chave.

Uso:
    python examples/analyze_aoi.py examples/car_exemplo.geojson amazonia_floresta

Entrada: um polígono (GeoJSON ou KML) — baixe o perímetro de um CAR na consulta pública do
SICAR, exporte um AOI do seu SIG, ou desenhe qualquer área que queira investigar.
Saída: o veredito observado (nativa/consolidada, supressão pós-2008, RL, APP) em JSON.

Não exige IAGRO_DSN. O fluxo institucional (confronto com as camadas DECLARADAS no SICAR em
escala) é o serviço — veja examples/run_one.py e o README.
"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "pipeline"))
import aoi_analyze

if __name__ == "__main__":
    aoi_analyze.main()
