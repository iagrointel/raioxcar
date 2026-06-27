#!/usr/bin/env python3
"""Roda o confronto declarado × observado sobre UM imóvel do CAR e imprime o veredito.
Uso: IAGRO_DSN=postgresql://... python examples/run_one.py <COD_IMOVEL>"""
import os, sys, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "engine"))
import confront
def main():
    if len(sys.argv) < 2:
        print("uso: python examples/run_one.py <COD_IMOVEL>"); sys.exit(1)
    dsn = os.environ.get("IAGRO_DSN")
    if not dsn:
        print("defina IAGRO_DSN (veja .env.example)"); sys.exit(1)
    print(json.dumps(confront.confront(sys.argv[1], dsn), ensure_ascii=False, indent=1))
if __name__ == "__main__":
    main()
