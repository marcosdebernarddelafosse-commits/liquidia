"""Motor de conciliación IVA.

Cruza dos fuentes del mismo período (típicamente Libro IVA del estudio vs.
padrón de comprobantes de AFIP) y clasifica cada comprobante en:

  - CONCILIADO          : aparece en ambas fuentes, montos coinciden
  - DIFERENCIA_MONTO    : aparece en ambas, pero neto o IVA difieren
  - SOLO_ESTUDIO        : está en el Libro IVA pero no en AFIP
  - SOLO_AFIP           : está en AFIP pero no en el Libro IVA

El resultado alimenta el dashboard de excepciones, donde el contador resuelve
solo lo que necesita atención (no el 100% de los comprobantes).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum

from .models import Comprobante


# Tolerancia de redondeo: diferencias por debajo se consideran iguales.
TOLERANCIA = Decimal("0.50")


class EstadoConciliacion(str, Enum):
    CONCILIADO = "conciliado"
    DIFERENCIA_MONTO = "diferencia_monto"
    SOLO_ESTUDIO = "solo_estudio"
    SOLO_AFIP = "solo_afip"


@dataclass
class ResultadoItem:
    clave: str
    estado: EstadoConciliacion
    comp_estudio: Comprobante | None = None
    comp_afip: Comprobante | None = None
    dif_neto: Decimal = Decimal("0")
    dif_iva: Decimal = Decimal("0")
    detalle: list[str] = field(default_factory=list)

    @property
    def requiere_atencion(self) -> bool:
        return self.estado != EstadoConciliacion.CONCILIADO


@dataclass
class ResumenConciliacion:
    items: list[ResultadoItem]

    def _contar(self, estado: EstadoConciliacion) -> int:
        return sum(1 for i in self.items if i.estado == estado)

    @property
    def total(self) -> int:
        return len(self.items)

    @property
    def conciliados(self) -> int:
        return self._contar(EstadoConciliacion.CONCILIADO)

    @property
    def excepciones(self) -> list[ResultadoItem]:
        return [i for i in self.items if i.requiere_atencion]

    @property
    def tasa_conciliacion(self) -> float:
        return round(self.conciliados / self.total, 4) if self.total else 0.0

    def por_estado(self) -> dict[str, int]:
        return {e.value: self._contar(e) for e in EstadoConciliacion}


def _indexar(comprobantes: list[Comprobante]) -> dict[str, Comprobante]:
    """Indexa por clave de matching. Si hay duplicados, el último gana
    (se registra como advertencia para auditoría)."""
    indice: dict[str, Comprobante] = {}
    for c in comprobantes:
        if c.clave in indice:
            c.advertencias.append("clave duplicada en el lote")
        indice[c.clave] = c
    return indice


def conciliar(
    estudio: list[Comprobante],
    afip: list[Comprobante],
) -> ResumenConciliacion:
    """Concilia comprobantes del estudio contra los de AFIP."""
    idx_estudio = _indexar(estudio)
    idx_afip = _indexar(afip)
    todas_las_claves = set(idx_estudio) | set(idx_afip)

    items: list[ResultadoItem] = []
    for clave in sorted(todas_las_claves):
        ce = idx_estudio.get(clave)
        ca = idx_afip.get(clave)

        if ce and ca:
            dif_neto = (ce.neto_gravado - ca.neto_gravado).copy_abs()
            dif_iva = (ce.iva - ca.iva).copy_abs()
            if dif_neto <= TOLERANCIA and dif_iva <= TOLERANCIA:
                items.append(ResultadoItem(clave, EstadoConciliacion.CONCILIADO,
                                           ce, ca))
            else:
                detalle = []
                if dif_neto > TOLERANCIA:
                    detalle.append(f"neto difiere en ${dif_neto}")
                if dif_iva > TOLERANCIA:
                    detalle.append(f"IVA difiere en ${dif_iva}")
                items.append(ResultadoItem(
                    clave, EstadoConciliacion.DIFERENCIA_MONTO, ce, ca,
                    dif_neto, dif_iva, detalle))
        elif ce and not ca:
            items.append(ResultadoItem(
                clave, EstadoConciliacion.SOLO_ESTUDIO, comp_estudio=ce,
                detalle=["no figura en AFIP — posible no declarado o error de carga"]))
        else:
            items.append(ResultadoItem(
                clave, EstadoConciliacion.SOLO_AFIP, comp_afip=ca,
                detalle=["figura en AFIP pero no en el Libro IVA — falta registrar"]))

    return ResumenConciliacion(items=items)
