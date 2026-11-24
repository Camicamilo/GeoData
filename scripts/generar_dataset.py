#!/usr/bin/env python3
"""Genera el dataset propio de prueba (datos 100 % sintéticos, semilla fija = reproducible).

    python3 scripts/generar_dataset.py        -> crea dataset/
"""
import random
from pathlib import Path

SALIDA = Path(__file__).resolve().parent.parent / "dataset"
ENCABEZADO = "muestra_id,ph,humedad,nitrogeno,fosforo\n"
rnd = random.Random(2026)


def fila(i, prefijo="M"):
    return (f"{prefijo}{i:05d},{rnd.uniform(4.5, 8.5):.2f},{rnd.uniform(10, 60):.1f},"
            f"{rnd.uniform(20, 300):.1f},{rnd.uniform(5, 80):.1f}\n")


def csv(nombre, n, prefijo="M", encabezado=ENCABEZADO, alterar=None):
    lineas = [encabezado] + [fila(i, prefijo) for i in range(1, n + 1)]
    if alterar:
        alterar(lineas)
    (SALIDA / nombre).write_text("".join(lineas), encoding="utf-8")


def main():
    SALIDA.mkdir(exist_ok=True)
    # 1. Válido pequeño -> COMPLETADO
    csv("muestras_finca_a.csv", 100, "FA")
    # 2. Válido grande (~1,1 MB) -> COMPLETADO (se usa en la prueba de carga)
    csv("muestras_valle_completo.csv", 38_000, "VS")
    # 3. Encabezado incorrecto -> FALLIDO en el worker
    csv("muestras_encabezado_malo.csv", 50, "EM", encabezado="id,acidez,agua,n,p\n")
    # 4. Valor no numérico en la fila 40 -> FALLIDO en el worker
    def ph_texto(l):
        partes = l[39].split(",")
        partes[1] = "acido"
        l[39] = ",".join(partes)
    csv("muestras_ph_texto.csv", 80, "PT", alterar=ph_texto)
    # 5. "PDF" renombrado a .csv (binario) -> RECHAZADO en el API
    (SALIDA / "informe_renombrado.csv").write_bytes(
        b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n" + bytes(rnd.getrandbits(8) for _ in range(50_000)))
    # 6. Demasiado grande (~2,3 MB) -> RECHAZADO en el API
    csv("muestras_gigante.csv", 80_000, "GG")

    for f in sorted(SALIDA.iterdir()):
        print(f"{f.name:32s} {f.stat().st_size:>10,d} B")


if __name__ == "__main__":
    main()
