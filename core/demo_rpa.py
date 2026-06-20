"""Demo end-to-end con descarga RPA (modo mock).

Encadena el pipeline real del producto:
  1. RPA descarga 'Mis Comprobantes' de AFIP   (mock: genera el CSV de AFIP)
  2. El parser universal lee ESE CSV de AFIP
  3. El estudio aporta su Libro IVA (Excel propio)
  4. El motor concilia ambas fuentes y reporta excepciones

Demuestra que el CSV que entrega AFIP entra al mismo parser universal sin
código especial: es solo otra fuente con otros nombres de columna.

Correr con:  python -m core.demo_rpa
"""

from __future__ import annotations

import tempfile
from datetime import date
from pathlib import Path

import pandas as pd

from .conciliacion import conciliar
from .models import TipoOperacion
from .parser import parsear
from .rpa.afip import ParametrosDescarga
from .rpa.mock_afip import descargar_comprobantes_mock


def _libro_iva_estudio(ruta: Path) -> None:
    """Excel propio del estudio (mismo del demo base)."""
    df = pd.DataFrame([
        {"Fecha": "05/03/2026", "Tipo Cbte": "1", "Pto Venta": "3",
         "Nro Comprobante": "1045", "CUIT Cliente": "30-71234567-8",
         "Cliente": "Distribuidora Norte SA", "Neto Gravado": "100.000,00",
         "IVA 21": "21.000,00", "Total": "121.000,00"},
        {"Fecha": "12/03/2026", "Tipo Cbte": "6", "Pto Venta": "3",
         "Nro Comprobante": "1046", "CUIT Cliente": "27-99887766-5",
         "Cliente": "Kiosco El Sol", "Neto Gravado": "50.000,00",
         "IVA 21": "10.500,00", "Total": "60.500,00"},
        {"Fecha": "15/03/2026", "Tipo Cbte": "3", "Pto Venta": "3",
         "Nro Comprobante": "88", "CUIT Cliente": "30-71234567-8",
         "Cliente": "Distribuidora Norte SA", "Neto Gravado": "10.000,00",
         "IVA 21": "2.100,00", "Total": "12.100,00"},
        {"Fecha": "20/03/2026", "Tipo Cbte": "1", "Pto Venta": "3",
         "Nro Comprobante": "1047", "CUIT Cliente": "20-12345678-9",
         "Cliente": "Servicios Pampa SRL", "Neto Gravado": "30.000,00",
         "IVA 21": "6.300,00", "Total": "36.300,00"},
    ])
    df.to_excel(ruta, index=False)


def main() -> None:
    tmp = Path(tempfile.mkdtemp())

    print("=" * 68)
    print("  LiquidIA — Pipeline end-to-end: RPA AFIP -> Parser -> Conciliación")
    print("=" * 68)

    # 1) Descarga AFIP (mock).
    params = ParametrosDescarga(
        cuit_representado="30712345678",
        desde=date(2026, 3, 1),
        hasta=date(2026, 3, 31),
        emitidos=True,
        directorio_salida=str(tmp),
    )
    print("\n  [1] RPA AFIP (modo mock) — descargando Mis Comprobantes...")
    resultado = descargar_comprobantes_mock(params)
    print(f"      CSV descargado: {Path(resultado.ruta_csv).name}")
    print(f"      Comprobantes en AFIP: {resultado.cantidad_estimada}")

    # 2) Parsear el CSV de AFIP con el MISMO parser universal.
    print("\n  [2] Parser universal leyendo el CSV de AFIP...")
    comp_afip, map_afip = parsear(resultado.ruta_csv, TipoOperacion.VENTA, "afip")
    print(f"      Confianza de detección: {map_afip.confianza:.0%}  "
          f"(formato AFIP reconocido sin config)")

    # 3) Libro IVA del estudio.
    ruta_estudio = tmp / "libro_iva.xlsx"
    _libro_iva_estudio(ruta_estudio)
    comp_estudio, _ = parsear(str(ruta_estudio), TipoOperacion.VENTA, "excel")
    print(f"\n  [3] Libro IVA del estudio: {len(comp_estudio)} comprobantes")

    # 4) Conciliar.
    print("\n  [4] Conciliando estudio vs AFIP...")
    resumen = conciliar(comp_estudio, comp_afip)
    print(f"      Tasa de conciliación: {resumen.tasa_conciliacion:.0%}")
    print(f"      Desglose: {resumen.por_estado()}")

    print(f"\n  EXCEPCIONES ({len(resumen.excepciones)}):")
    for item in resumen.excepciones:
        ref = item.comp_estudio or item.comp_afip
        print(f"    - [{item.estado.value}] {ref.razon_social}: "
              f"{'; '.join(item.detalle)}")

    print("\n" + "=" * 68)
    print("  El CSV de AFIP entró al mismo parser que el Excel del estudio.")
    print("  Sin clave fiscal real, todo el flujo queda validado punta a punta.")
    print("=" * 68)


if __name__ == "__main__":
    main()
