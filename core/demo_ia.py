"""Demo del fallback de mapeo con Claude.

Genera una planilla con headers "raros" que el diccionario de sinónimos NO
puede mapear (ej. "Fec.Cpbte", "C.U.I.T.", "Imp.Grav."), y muestra cómo el
fallback de Claude los resuelve.

Para no depender de tener ANTHROPIC_API_KEY al correr la demo, si no hay key
real se stubbea la respuesta de Claude para probar la integración. Si hay key,
usa Claude de verdad.

Correr con:  python -m core.demo_ia
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pandas as pd

from . import ai_mapper
from .models import TipoOperacion
from .parser import parsear


def _planilla_rara(ruta: Path) -> None:
    """Headers abreviados/no estándar que el diccionario no cubre."""
    df = pd.DataFrame([
        {"Fec.Cpbte": "05/03/2026", "Cod.": "1", "Bca": "3", "Corr.": "1045",
         "C.U.I.T.": "30712345678", "Sujeto": "Distribuidora Norte SA",
         "Imp.Grav.": "100000,00", "Déb.Fiscal": "21000,00"},
    ])
    df.to_excel(ruta, index=False)


def _stub_claude(columnas, faltantes, muestra):
    """Simula lo que devolvería Claude para esta planilla concreta."""
    posible = {
        "tipo_comprobante": "Cod.",
        "punto_venta": "Bca",
        "numero": "Corr.",
        "cuit_contraparte": "C.U.I.T.",
        "neto_gravado": "Imp.Grav.",
        "iva": "Déb.Fiscal",
    }
    return {c: col for c, col in posible.items() if c in faltantes}


def main() -> None:
    tmp = Path(tempfile.mkdtemp())
    ruta = tmp / "planilla_rara.xlsx"
    _planilla_rara(ruta)

    hay_key = bool(os.environ.get("ANTHROPIC_API_KEY"))
    print("=" * 68)
    print("  LiquidIA — Demo del fallback de mapeo con Claude")
    print("=" * 68)
    print(f"\n  ANTHROPIC_API_KEY presente: {hay_key}")

    if not hay_key:
        print("  -> sin key: stubbeando la respuesta de Claude para probar la "
              "integración\n")
        ai_mapper.mapear_con_ia = _stub_claude  # type: ignore
    else:
        print("  -> usando Claude real (claude-haiku-4-5)\n")

    # Primero mostramos qué pasa SIN ia: el diccionario falla.
    comp_sin, mapeo_sin = parsear(str(ruta), TipoOperacion.VENTA, usar_ia=False)
    print(f"  Sin IA: confianza {mapeo_sin.confianza:.0%}, "
          f"faltantes={mapeo_sin.faltantes}")
    print(f"          comprobantes leídos: {len(comp_sin)}  (no puede procesar)\n")

    # Ahora con el fallback activo.
    comp, mapeo = parsear(str(ruta), TipoOperacion.VENTA, usar_ia=True)
    print(f"  Con IA: confianza {mapeo.confianza:.0%}, "
          f"faltantes={mapeo.faltantes}")
    print(f"          resueltos por Claude: {mapeo.resueltos_por_ia}")
    print(f"          comprobantes leídos: {len(comp)}\n")

    if comp:
        c = comp[0]
        print(f"  Comprobante recuperado: {c.razon_social} | "
              f"neto ${c.neto_gravado} | IVA ${c.iva}")
        print(f"  Clave de conciliación: {c.clave}")

    print("\n" + "=" * 68)
    print("  Una planilla que antes requería configuración manual ahora se")
    print("  procesa sola. Ese es el 10% de casos que el diccionario no cubre.")
    print("=" * 68)


if __name__ == "__main__":
    main()
