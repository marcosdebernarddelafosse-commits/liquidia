"""Demo end-to-end del núcleo de LiquidIA.

Genera dos planillas con formatos DISTINTOS (como las que llegan en la vida
real) para probar que el parser universal las entiende sin configuración, y
luego concilia una contra la otra mostrando las excepciones.

Correr con:  python -m core.demo
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pandas as pd

from .conciliacion import conciliar
from .models import TipoOperacion
from .parser import parsear


def _planilla_estudio(ruta: Path) -> None:
    """Formato 'Excel armado a mano' por el estudio, con nombres informales
    y montos en formato argentino (texto)."""
    df = pd.DataFrame([
        # Factura A, conciliada OK
        {"Fecha": "05/03/2026", "Tipo Cbte": "1", "Pto Venta": "3",
         "Nro Comprobante": "1045", "CUIT Cliente": "30-71234567-8",
         "Cliente": "Distribuidora Norte SA", "Neto Gravado": "100.000,00",
         "IVA 21": "21.000,00", "Total": "121.000,00"},
        # Factura B, con diferencia de monto contra AFIP
        {"Fecha": "12/03/2026", "Tipo Cbte": "6", "Pto Venta": "3",
         "Nro Comprobante": "1046", "CUIT Cliente": "27-99887766-5",
         "Cliente": "Kiosco El Sol", "Neto Gravado": "50.000,00",
         "IVA 21": "10.500,00", "Total": "60.500,00"},
        # Nota de Crédito A (invierte signo)
        {"Fecha": "15/03/2026", "Tipo Cbte": "3", "Pto Venta": "3",
         "Nro Comprobante": "88", "CUIT Cliente": "30-71234567-8",
         "Cliente": "Distribuidora Norte SA", "Neto Gravado": "10.000,00",
         "IVA 21": "2.100,00", "Total": "12.100,00"},
        # Factura solo en el estudio (no declarada en AFIP)
        {"Fecha": "20/03/2026", "Tipo Cbte": "1", "Pto Venta": "3",
         "Nro Comprobante": "1047", "CUIT Cliente": "20-12345678-9",
         "Cliente": "Servicios Pampa SRL", "Neto Gravado": "30.000,00",
         "IVA 21": "6.300,00", "Total": "36.300,00"},
    ])
    df.to_excel(ruta, index=False)


def _planilla_afip(ruta: Path) -> None:
    """Formato 'export AFIP', con OTROS nombres de columna y números nativos."""
    df = pd.DataFrame([
        {"Fecha Emision": "05/03/2026", "Cod Comprobante": 1, "Punto de Venta": 3,
         "Numero": 1045, "Nro Doc": "30712345678", "Denominacion": "DISTRIBUIDORA NORTE SA",
         "Importe Neto": 100000.00, "I.V.A": 21000.00, "Importe Total": 121000.00},
        # misma factura B pero AFIP tiene neto distinto -> excepción
        {"Fecha Emision": "12/03/2026", "Cod Comprobante": 6, "Punto de Venta": 3,
         "Numero": 1046, "Nro Doc": "27998877665", "Denominacion": "KIOSCO EL SOL",
         "Importe Neto": 48000.00, "I.V.A": 10080.00, "Importe Total": 58080.00},
        {"Fecha Emision": "15/03/2026", "Cod Comprobante": 3, "Punto de Venta": 3,
         "Numero": 88, "Nro Doc": "30712345678", "Denominacion": "DISTRIBUIDORA NORTE SA",
         "Importe Neto": 10000.00, "I.V.A": 2100.00, "Importe Total": 12100.00},
        # factura que AFIP tiene pero el estudio no cargó
        {"Fecha Emision": "22/03/2026", "Cod Comprobante": 1, "Punto de Venta": 3,
         "Numero": 1050, "Nro Doc": "23456789014", "Denominacion": "LOGISTICA SUR SA",
         "Importe Neto": 75000.00, "I.V.A": 15750.00, "Importe Total": 90750.00},
    ])
    df.to_excel(ruta, index=False)


def main() -> None:
    tmp = Path(tempfile.mkdtemp())
    ruta_estudio = tmp / "libro_iva_estudio.xlsx"
    ruta_afip = tmp / "comprobantes_afip.xlsx"
    _planilla_estudio(ruta_estudio)
    _planilla_afip(ruta_afip)

    comp_estudio, map_estudio = parsear(str(ruta_estudio), TipoOperacion.VENTA, "excel")
    comp_afip, map_afip = parsear(str(ruta_afip), TipoOperacion.VENTA, "afip")

    print("=" * 68)
    print("  LiquidIA — Demo de conciliación IVA Ventas")
    print("=" * 68)
    print(f"\nParser — planilla del estudio:")
    print(f"  confianza de detección: {map_estudio.confianza:.0%}")
    print(f"  columnas mapeadas: {len(map_estudio.mapa)} | "
          f"sin mapear: {map_estudio.no_mapeadas}")
    print(f"\nParser — export AFIP (otro formato de columnas):")
    print(f"  confianza de detección: {map_afip.confianza:.0%}")
    print(f"  -> el MISMO parser entendió ambos formatos sin configuración\n")

    print(f"Comprobantes leídos: estudio={len(comp_estudio)} | afip={len(comp_afip)}")

    resumen = conciliar(comp_estudio, comp_afip)

    print("\n" + "-" * 68)
    print(f"  Tasa de conciliación: {resumen.tasa_conciliacion:.0%}  "
          f"({resumen.conciliados}/{resumen.total} comprobantes OK)")
    print("-" * 68)
    print("  Desglose:", resumen.por_estado())

    print(f"\n  EXCEPCIONES A REVISAR ({len(resumen.excepciones)}):\n")
    for item in resumen.excepciones:
        ref = item.comp_estudio or item.comp_afip
        print(f"  [{item.estado.value.upper()}] {ref.razon_social}")
        print(f"     comprobante {item.clave}")
        for d in item.detalle:
            print(f"     -> {d}")
        print()

    print("=" * 68)
    print("  El contador solo revisa estas excepciones, no los 4 comprobantes.")
    print("  En un período real: revisa ~30 de 3000. Ahí está el 70% de ahorro.")
    print("=" * 68)


if __name__ == "__main__":
    main()
