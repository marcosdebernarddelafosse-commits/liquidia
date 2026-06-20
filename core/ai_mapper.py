"""Fallback de mapeo de columnas con Claude.

Cuando el diccionario de sinónimos (parser.py) no logra identificar todas las
columnas requeridas, recurrimos a Claude: le pasamos los headers que quedaron
sin mapear más una muestra de filas, y Claude infiere qué columna corresponde a
cada campo canónico faltante.

Diseño:
  - Degradación elegante: si no hay API key o falla la llamada, devuelve mapeo
    vacío y el sistema sigue funcionando (solo que esa planilla queda marcada
    como "requiere revisión manual").
  - Barato: usa claude-haiku-4-5, suficiente para mapear headers.
  - Determinista: temperature 0 y salida JSON estricta.
"""

from __future__ import annotations

import json
import os

try:
    from anthropic import Anthropic
    _SDK_DISPONIBLE = True
except ImportError:
    _SDK_DISPONIBLE = False

# Mismo conjunto de campos requeridos que usa el parser.
CAMPOS_CANONICOS = [
    "fecha", "tipo_comprobante", "punto_venta", "numero", "cuit_contraparte",
    "razon_social", "neto_gravado", "iva", "no_gravado", "exento",
    "percepciones_iva", "percepciones_iibb", "total", "jurisdiccion_iibb",
    "unidad_negocio",
]

MODELO = "claude-haiku-4-5"

_DESCRIPCIONES = {
    "fecha": "fecha de emisión del comprobante",
    "tipo_comprobante": "código numérico de tipo de comprobante AFIP (1=Fac A, 6=Fac B, 3=NC A, etc.)",
    "punto_venta": "punto de venta / sucursal",
    "numero": "número correlativo del comprobante",
    "cuit_contraparte": "CUIT del cliente o proveedor",
    "razon_social": "nombre o razón social de la contraparte",
    "neto_gravado": "importe neto gravado (base imponible del IVA)",
    "iva": "monto de IVA liquidado",
    "no_gravado": "importe no gravado",
    "exento": "importe exento",
    "percepciones_iva": "percepciones de IVA",
    "percepciones_iibb": "percepciones de Ingresos Brutos",
    "total": "importe total del comprobante",
    "jurisdiccion_iibb": "jurisdicción/provincia para Ingresos Brutos",
    "unidad_negocio": "unidad de negocio / centro de costo",
}


def _construir_prompt(
    columnas: list[str],
    campos_faltantes: list[str],
    muestra: list[dict],
) -> str:
    desc = "\n".join(
        f"  - {c}: {_DESCRIPCIONES[c]}" for c in campos_faltantes
    )
    return (
        "Sos un experto en contabilidad argentina. Tengo una planilla Excel de "
        "comprobantes fiscales y necesito mapear sus columnas a campos canónicos.\n\n"
        f"Columnas disponibles en el archivo:\n{json.dumps(columnas, ensure_ascii=False)}\n\n"
        f"Muestra de las primeras filas:\n{json.dumps(muestra, ensure_ascii=False, default=str)}\n\n"
        f"Necesito identificar SOLO estos campos que no pude detectar automáticamente:\n{desc}\n\n"
        "Devolvé EXCLUSIVAMENTE un objeto JSON donde cada clave es un campo canónico "
        "y su valor es el nombre EXACTO de la columna del archivo que le corresponde. "
        "Si un campo no tiene columna correspondiente en el archivo, omitilo. "
        "No inventes columnas. No incluyas explicaciones, solo el JSON."
    )


def mapear_con_ia(
    columnas: list[str],
    campos_faltantes: list[str],
    muestra: list[dict],
) -> dict[str, str]:
    """Devuelve {campo_canonico: nombre_columna} para los campos faltantes.

    Devuelve {} si no hay SDK, no hay API key, o la llamada falla."""
    if not _SDK_DISPONIBLE or not os.environ.get("ANTHROPIC_API_KEY"):
        return {}
    if not campos_faltantes:
        return {}

    try:
        client = Anthropic()
        resp = client.messages.create(
            model=MODELO,
            max_tokens=512,
            temperature=0,
            messages=[{
                "role": "user",
                "content": _construir_prompt(columnas, campos_faltantes, muestra),
            }],
        )
        texto = resp.content[0].text.strip()
        # Robustez: extraer el bloque JSON aunque venga con texto alrededor.
        inicio = texto.find("{")
        fin = texto.rfind("}")
        if inicio == -1 or fin == -1:
            return {}
        crudo = json.loads(texto[inicio:fin + 1])
    except Exception:
        return {}

    # Validar: solo aceptar mapeos a columnas que existen de verdad.
    validado: dict[str, str] = {}
    for campo, columna in crudo.items():
        if campo in CAMPOS_CANONICOS and columna in columnas:
            validado[campo] = columna
    return validado
