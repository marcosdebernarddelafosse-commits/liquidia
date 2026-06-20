"""Modo mock de la descarga de AFIP.

Genera un CSV con el MISMO formato de columnas que exporta 'Mis Comprobantes'
de AFIP en la vida real, sin tocar el portal. Sirve para:
  - Desarrollar y testear el pipeline completo (RPA -> parser -> conciliación)
    sin clave fiscal ni Playwright.
  - Demostrar el flujo end-to-end.

El formato de columnas imita el export real de AFIP (separador ';', formato de
fecha dd/mm/aaaa, montos con coma decimal).
"""

from __future__ import annotations

import csv
from pathlib import Path

from .afip import ParametrosDescarga, ResultadoDescarga

# Encabezados reales del export 'Mis Comprobantes' (emitidos), simplificados.
_HEADERS = [
    "Fecha", "Tipo", "Punto de Venta", "Número Desde", "Número Hasta",
    "Nro. Doc. Receptor", "Denominación Receptor",
    "Imp. Neto Gravado", "Imp. Neto No Gravado", "Imp. Op. Exentas",
    "IVA", "Imp. Total",
]

# Filas de ejemplo que conciliarán (o no) contra el Libro IVA del estudio.
_FILAS_EMITIDOS = [
    ["05/03/2026", "1", "3", "1045", "1045", "30712345678",
     "DISTRIBUIDORA NORTE SA", "100000,00", "0,00", "0,00", "21000,00", "121000,00"],
    ["12/03/2026", "6", "3", "1046", "1046", "27998877665",
     "KIOSCO EL SOL", "48000,00", "0,00", "0,00", "10080,00", "58080,00"],
    ["15/03/2026", "3", "3", "88", "88", "30712345678",
     "DISTRIBUIDORA NORTE SA", "10000,00", "0,00", "0,00", "2100,00", "12100,00"],
    ["22/03/2026", "1", "3", "1050", "1050", "23456789014",
     "LOGISTICA SUR SA", "75000,00", "0,00", "0,00", "15750,00", "90750,00"],
]


def descargar_comprobantes_mock(
    params: ParametrosDescarga,
) -> ResultadoDescarga:
    """Réplica de la firma real, pero escribe un CSV simulado de AFIP."""
    salida = Path(params.directorio_salida)
    salida.mkdir(parents=True, exist_ok=True)

    tipo = "emitidos" if params.emitidos else "recibidos"
    ruta = salida / (
        f"afip_MOCK_{params.cuit_representado}_{tipo}_"
        f"{params.desde:%Y%m%d}_{params.hasta:%Y%m%d}.csv"
    )

    filas = _FILAS_EMITIDOS if params.emitidos else []
    with open(ruta, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh, delimiter=";")
        writer.writerow(_HEADERS)
        writer.writerows(filas)

    return ResultadoDescarga(
        ruta_csv=str(ruta),
        cantidad_estimada=len(filas),
        parametros=params,
    )
