"""Modelo de datos canónico de un comprobante fiscal argentino.

Toda fuente heterogénea (Excel del estudio, export de Tango/Bejerman, descarga
de AFIP) se normaliza a este modelo antes de conciliar. Es el "idioma común"
del sistema.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import Enum


class TipoOperacion(str, Enum):
    VENTA = "venta"
    COMPRA = "compra"


# Códigos de comprobante AFIP relevantes para liquidación.
# Las Notas de Crédito invierten el signo en la liquidación.
NOTAS_DE_CREDITO = {3, 8, 13, 21, 53, 110, 119}  # A, B, C, M, etc.
FACTURAS = {1, 6, 11, 51, 109, 118}


@dataclass
class Comprobante:
    """Comprobante normalizado. Montos siempre positivos en origen;
    el signo se resuelve en la liquidación según `es_nota_credito`."""

    tipo_operacion: TipoOperacion
    fecha: date
    tipo_comprobante: int          # código AFIP
    punto_venta: int
    numero: int
    cuit_contraparte: str          # CUIT del cliente o proveedor
    razon_social: str
    neto_gravado: Decimal
    iva: Decimal
    no_gravado: Decimal = Decimal("0")
    exento: Decimal = Decimal("0")
    percepciones_iva: Decimal = Decimal("0")
    percepciones_iibb: Decimal = Decimal("0")
    total: Decimal = Decimal("0")
    jurisdiccion_iibb: str | None = None   # código provincia para IIBB
    unidad_negocio: str | None = None      # segregación opcional
    origen: str = "desconocido"            # "excel", "afip", "tango", etc.

    # Metadatos de trazabilidad
    fila_origen: int | None = None
    advertencias: list[str] = field(default_factory=list)

    @property
    def es_nota_credito(self) -> bool:
        return self.tipo_comprobante in NOTAS_DE_CREDITO

    @property
    def signo(self) -> int:
        """+1 para facturas, -1 para notas de crédito."""
        return -1 if self.es_nota_credito else 1

    @property
    def clave(self) -> str:
        """Clave única de matching: tipo-PV-número-CUIT.

        Es la huella que permite cruzar el mismo comprobante entre el Libro IVA
        del estudio y el padrón de AFIP."""
        return (
            f"{self.tipo_comprobante:03d}-{self.punto_venta:05d}-"
            f"{self.numero:08d}-{self.cuit_contraparte}"
        )

    @property
    def neto_gravado_con_signo(self) -> Decimal:
        return self.neto_gravado * self.signo

    @property
    def iva_con_signo(self) -> Decimal:
        return self.iva * self.signo
