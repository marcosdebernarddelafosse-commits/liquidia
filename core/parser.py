"""Parser universal de Excel/CSV.

El diferenciador del producto: el contador sube SU planilla, con SUS nombres de
columna, y el sistema la entiende. No le pedimos que se adapte a un formato.

Estrategia en dos capas:
  1. Diccionario de sinónimos (rápido, gratis, cubre el 90% de los casos).
  2. Fallback a Claude para mapear headers ambiguos (fase siguiente).

Este módulo implementa la capa 1, que ya resuelve la mayoría de las planillas
reales de estudios argentinos (export de Tango, Bejerman, Excel armado a mano).
"""

from __future__ import annotations

import csv
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

import pandas as pd

from .models import Comprobante, TipoOperacion


# ---------------------------------------------------------------------------
# Diccionario de sinónimos: campo canónico -> variantes que vemos en la práctica
# ---------------------------------------------------------------------------
SINONIMOS: dict[str, list[str]] = {
    "fecha": ["fecha", "fecha comprobante", "fecha emision", "f emision", "fec"],
    "tipo_comprobante": ["tipo", "tipo comprobante", "cod comprobante",
                         "comprobante", "tipo cbte", "cbte tipo"],
    "punto_venta": ["punto venta", "pto venta", "pv", "punto de venta",
                    "sucursal"],
    "numero": ["numero", "nro", "n comprobante", "numero comprobante",
               "nro comprobante", "factura nro", "comprobante nro"],
    "cuit_contraparte": ["cuit", "cuit cliente", "cuit proveedor", "cuit/cuil",
                         "documento", "nro doc"],
    "razon_social": ["razon social", "cliente", "proveedor", "denominacion",
                     "nombre", "razon"],
    "neto_gravado": ["neto", "neto gravado", "gravado", "importe neto",
                     "base imponible", "neto gravado 21"],
    "iva": ["iva", "iva 21", "iva liquidado", "impuesto", "i.v.a", "iva 105",
            "alicuota iva"],
    "no_gravado": ["no gravado", "concepto no gravado", "importe no gravado"],
    "exento": ["exento", "importe exento", "operaciones exentas"],
    "percepciones_iva": ["percepcion iva", "perc iva", "percepciones iva"],
    "percepciones_iibb": ["percepcion iibb", "perc iibb", "percepcion ib",
                          "percepciones iibb", "perc ingresos brutos"],
    "total": ["total", "importe total", "total comprobante", "monto total"],
    "jurisdiccion_iibb": ["jurisdiccion", "provincia", "juris", "jurisdicción"],
    "unidad_negocio": ["unidad negocio", "un", "centro costo", "sucursal un",
                       "segmento"],
}


def _normalizar(texto: str) -> str:
    """Minúsculas, sin acentos, sin puntuación, espacios colapsados."""
    texto = str(texto).strip().lower()
    texto = unicodedata.normalize("NFKD", texto)
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    texto = re.sub(r"[._/]+", " ", texto)
    texto = re.sub(r"[^a-z0-9 ]+", "", texto)
    return re.sub(r"\s+", " ", texto).strip()


@dataclass
class MapeoColumnas:
    """Resultado de detectar qué columna del archivo corresponde a cada campo."""

    mapa: dict[str, str]            # campo_canonico -> nombre real de columna
    no_mapeadas: list[str]          # columnas del archivo que no reconocimos
    faltantes: list[str]            # campos requeridos que no encontramos
    resueltos_por_ia: list[str] = field(default_factory=list)  # campos que mapeó Claude

    @property
    def confianza(self) -> float:
        requeridos = {"fecha", "tipo_comprobante", "punto_venta", "numero",
                      "cuit_contraparte", "neto_gravado", "iva"}
        encontrados = sum(1 for r in requeridos if r in self.mapa)
        return round(encontrados / len(requeridos), 2)


def detectar_columnas(columnas: list[str]) -> MapeoColumnas:
    """Mapea las columnas reales del archivo a los campos canónicos."""
    normalizadas = {col: _normalizar(col) for col in columnas}
    mapa: dict[str, str] = {}
    usadas: set[str] = set()

    for campo, variantes in SINONIMOS.items():
        variantes_norm = [_normalizar(v) for v in variantes]
        # 1) match exacto
        for col, norm in normalizadas.items():
            if col in usadas:
                continue
            if norm in variantes_norm:
                mapa[campo] = col
                usadas.add(col)
                break
        if campo in mapa:
            continue
        # 2) match por inclusión (la variante aparece dentro del header)
        for col, norm in normalizadas.items():
            if col in usadas:
                continue
            if any(v and (v in norm or norm in v) for v in variantes_norm):
                mapa[campo] = col
                usadas.add(col)
                break

    no_mapeadas = [c for c in columnas if c not in usadas]
    requeridos = ["fecha", "tipo_comprobante", "punto_venta", "numero",
                  "cuit_contraparte", "neto_gravado", "iva"]
    faltantes = [r for r in requeridos if r not in mapa]
    return MapeoColumnas(mapa=mapa, no_mapeadas=no_mapeadas, faltantes=faltantes)


# ---------------------------------------------------------------------------
# Coerción de valores
# ---------------------------------------------------------------------------
def _a_decimal(valor) -> Decimal:
    """Convierte a Decimal tolerando formato argentino (1.234,56) y vacíos."""
    if valor is None or (isinstance(valor, float) and pd.isna(valor)):
        return Decimal("0")
    if isinstance(valor, (int, float)):
        return Decimal(str(valor))
    s = str(valor).strip()
    if not s or s in {"-", "."}:
        return Decimal("0")
    s = re.sub(r"[^\d,.\-]", "", s)
    # Formato argentino: punto = miles, coma = decimal
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        return Decimal(s)
    except InvalidOperation:
        return Decimal("0")


def _a_fecha(valor) -> date | None:
    if valor is None or (isinstance(valor, float) and pd.isna(valor)):
        return None
    if isinstance(valor, (datetime, pd.Timestamp)):
        return valor.date()
    if isinstance(valor, date):
        return valor
    s = str(valor).strip()
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d", "%d/%m/%y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _detectar_separador(ruta: str) -> str:
    """Sniff del separador (',' ';' o tab) sobre la primera línea del CSV."""
    with open(ruta, encoding="utf-8", errors="ignore") as fh:
        primera = fh.readline()
    try:
        return csv.Sniffer().sniff(primera, delimiters=",;\t").delimiter
    except csv.Error:
        # Fallback: el que más aparezca.
        return max(",;\t", key=primera.count)


def _a_int(valor, default: int = 0) -> int:
    if valor is None or (isinstance(valor, float) and pd.isna(valor)):
        return default
    s = re.sub(r"[^\d]", "", str(valor))
    return int(s) if s else default


def _limpiar_cuit(valor) -> str:
    return re.sub(r"[^\d]", "", str(valor or ""))


def parsear(
    ruta: str,
    tipo_operacion: TipoOperacion,
    origen: str = "excel",
    usar_ia: bool = True,
) -> tuple[list[Comprobante], MapeoColumnas]:
    """Lee un Excel/CSV y devuelve comprobantes normalizados + el mapeo usado.

    Si el diccionario de sinónimos no detecta todos los campos requeridos y
    `usar_ia` está activo, recurre a Claude para mapear lo faltante."""
    if ruta.lower().endswith(".csv"):
        # AFIP exporta con ';'; otros sistemas con ','. Detectamos el separador
        # con el sniffer de csv sobre la primera línea.
        df = pd.read_csv(ruta, dtype=str, sep=_detectar_separador(ruta),
                         engine="python")
    else:
        df = pd.read_excel(ruta, dtype=str)

    df.columns = [str(c).strip() for c in df.columns]
    mapeo = detectar_columnas(list(df.columns))

    if mapeo.faltantes and usar_ia:
        # Fallback a Claude: le pasamos headers + muestra de filas.
        from .ai_mapper import mapear_con_ia
        muestra = df.head(3).to_dict(orient="records")
        sugerido = mapear_con_ia(list(df.columns), mapeo.faltantes, muestra)
        for campo, columna in sugerido.items():
            if campo not in mapeo.mapa:
                mapeo.mapa[campo] = columna
                mapeo.resueltos_por_ia.append(campo)
        # Recalcular faltantes y columnas sin mapear tras la ayuda de la IA.
        mapeo.faltantes = [f for f in mapeo.faltantes if f not in mapeo.mapa]
        mapeo.no_mapeadas = [c for c in mapeo.no_mapeadas
                             if c not in mapeo.mapa.values()]

    if mapeo.faltantes:
        # Ni el diccionario ni la IA alcanzaron: la capa superior decide
        # (pedir intervención manual). No reventamos.
        return [], mapeo

    comprobantes: list[Comprobante] = []
    m = mapeo.mapa
    for idx, fila in df.iterrows():
        fecha = _a_fecha(fila[m["fecha"]])
        if fecha is None:
            continue  # fila sin fecha válida = probablemente subtotal o header repetido
        comp = Comprobante(
            tipo_operacion=tipo_operacion,
            fecha=fecha,
            tipo_comprobante=_a_int(fila[m["tipo_comprobante"]]),
            punto_venta=_a_int(fila[m["punto_venta"]]),
            numero=_a_int(fila[m["numero"]]),
            cuit_contraparte=_limpiar_cuit(fila[m["cuit_contraparte"]]),
            razon_social=str(fila.get(m.get("razon_social", ""), "") or "").strip(),
            neto_gravado=_a_decimal(fila[m["neto_gravado"]]),
            iva=_a_decimal(fila[m["iva"]]),
            no_gravado=_a_decimal(fila[m["no_gravado"]]) if "no_gravado" in m else Decimal("0"),
            exento=_a_decimal(fila[m["exento"]]) if "exento" in m else Decimal("0"),
            percepciones_iva=_a_decimal(fila[m["percepciones_iva"]]) if "percepciones_iva" in m else Decimal("0"),
            percepciones_iibb=_a_decimal(fila[m["percepciones_iibb"]]) if "percepciones_iibb" in m else Decimal("0"),
            total=_a_decimal(fila[m["total"]]) if "total" in m else Decimal("0"),
            jurisdiccion_iibb=str(fila[m["jurisdiccion_iibb"]]).strip() if "jurisdiccion_iibb" in m else None,
            unidad_negocio=str(fila[m["unidad_negocio"]]).strip() if "unidad_negocio" in m else None,
            origen=origen,
            fila_origen=int(idx) + 2,  # +2: header + base-1 de Excel
        )
        comprobantes.append(comp)

    return comprobantes, mapeo
