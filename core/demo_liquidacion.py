"""Demo de liquidación de IVA + papel de trabajo.

Encadena: parseo de ventas y compras -> liquidación del período -> exportación
del papel de trabajo en Excel. Es el entregable final que recibe el estudio.

Correr con:  python -m core.demo_liquidacion
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pandas as pd

from .exportar import exportar_papel_de_trabajo
from .liquidacion import liquidar
from .models import TipoOperacion
from .parser import parsear


def _ventas(ruta: Path) -> None:
    df = pd.DataFrame([
        {"Fecha": "05/03/2026", "Tipo Cbte": "1", "Pto Venta": "3",
         "Nro Comprobante": "1045", "CUIT Cliente": "30-71234567-8",
         "Cliente": "Distribuidora Norte SA", "Neto Gravado": "100.000,00",
         "IVA 21": "21.000,00"},
        {"Fecha": "12/03/2026", "Tipo Cbte": "6", "Pto Venta": "3",
         "Nro Comprobante": "1046", "CUIT Cliente": "27-99887766-5",
         "Cliente": "Kiosco El Sol", "Neto Gravado": "200.000,00",
         "IVA 21": "21.000,00"},   # alícuota 10.5%
        {"Fecha": "15/03/2026", "Tipo Cbte": "3", "Pto Venta": "3",
         "Nro Comprobante": "88", "CUIT Cliente": "30-71234567-8",
         "Cliente": "Distribuidora Norte SA", "Neto Gravado": "10.000,00",
         "IVA 21": "2.100,00"},     # Nota de crédito: resta débito
    ])
    df.to_excel(ruta, index=False)


def _compras(ruta: Path) -> None:
    df = pd.DataFrame([
        {"Fecha": "03/03/2026", "Tipo Cbte": "1", "Pto Venta": "44",
         "Nro Comprobante": "9001", "CUIT Proveedor": "30-55667788-2",
         "Proveedor": "Insumos del Plata SA", "Neto Gravado": "80.000,00",
         "IVA 21": "16.800,00", "Perc IIBB": "0,00", "Perc IVA": "2.400,00"},
        {"Fecha": "10/03/2026", "Tipo Cbte": "1", "Pto Venta": "12",
         "Nro Comprobante": "5500", "CUIT Proveedor": "33-44556677-9",
         "Proveedor": "Energía Total SRL", "Neto Gravado": "40.000,00",
         "IVA 21": "8.400,00", "Perc IIBB": "0,00", "Perc IVA": "1.200,00"},
    ])
    df.to_excel(ruta, index=False)


def main() -> None:
    tmp = Path(tempfile.mkdtemp())
    ruta_v, ruta_c = tmp / "ventas.xlsx", tmp / "compras.xlsx"
    _ventas(ruta_v)
    _compras(ruta_c)

    ventas, _ = parsear(str(ruta_v), TipoOperacion.VENTA, "excel")
    compras, _ = parsear(str(ruta_c), TipoOperacion.COMPRA, "excel")

    liq = liquidar(ventas, compras, periodo="2026-03", cuit="30-71234567-8")

    print("=" * 64)
    print(f"  LiquidIA — Liquidación de IVA · Período {liq.periodo}")
    print("=" * 64)
    print(f"\n  DÉBITO FISCAL (ventas)")
    for ali in sorted(liq.ventas_por_alicuota, reverse=True):
        r = liq.ventas_por_alicuota[ali]
        print(f"     {ali:>5}%  neto {r.neto:>14,.2f}  IVA {r.iva:>12,.2f}")
    print(f"     {'Total débito':>20}: {liq.debito_fiscal:>14,.2f}")

    print(f"\n  CRÉDITO FISCAL (compras)")
    for ali in sorted(liq.compras_por_alicuota, reverse=True):
        r = liq.compras_por_alicuota[ali]
        print(f"     {ali:>5}%  neto {r.neto:>14,.2f}  IVA {r.iva:>12,.2f}")
    print(f"     {'Total crédito':>20}: {liq.credito_fiscal:>14,.2f}")

    print(f"\n  DETERMINACIÓN")
    print(f"     Saldo técnico (déb - créd): {liq.saldo_tecnico:>12,.2f}")
    print(f"     (-) Percepciones IVA:       {liq.percepciones_iva:>12,.2f}")
    if liq.saldo_a_pagar > 0:
        print(f"     => SALDO A PAGAR:           {liq.saldo_a_pagar:>12,.2f}")
    else:
        print(f"     => SALDO A FAVOR:           {liq.saldo_a_favor:>12,.2f}")

    if liq.advertencias:
        print(f"\n  ADVERTENCIAS:")
        for a in liq.advertencias:
            print(f"     • {a}")

    ruta_papel = exportar_papel_de_trabajo(liq, str(tmp / "papel_trabajo_IVA.xlsx"))
    print(f"\n  Papel de trabajo generado:\n     {ruta_papel}")
    print("=" * 64)


if __name__ == "__main__":
    main()
