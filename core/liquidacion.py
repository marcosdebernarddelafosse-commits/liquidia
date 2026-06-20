"""Motor de liquidación de IVA.

Toma los comprobantes ya normalizados (ventas y compras de un período) y produce
la liquidación del período: débito fiscal, crédito fiscal, percepciones sufridas
y el saldo resultante (a pagar o a favor).

Reglas aplicadas:
  - Notas de Crédito invierten el signo (una NC de venta resta débito fiscal).
  - Débito fiscal = IVA de ventas (facturas) - IVA de NC de ventas.
  - Crédito fiscal = IVA de compras (facturas) - IVA de NC de compras.
  - Percepciones/retenciones de IVA sufridas son saldo de libre disponibilidad.
  - Saldo técnico = débito - crédito. Si percepciones lo superan, queda saldo
    a favor del contribuyente.

Apertura por alícuota: se infiere la alícuota efectiva (iva/neto) y se agrupa,
porque la declaración jurada de IVA (F.2002) exige el detalle por alícuota.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP

from .models import Comprobante, TipoOperacion


CERO = Decimal("0.00")


def _q(valor: Decimal) -> Decimal:
    """Redondeo a 2 decimales, medio hacia arriba (criterio AFIP)."""
    return valor.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _alicuota_efectiva(c: Comprobante) -> Decimal:
    """Alícuota inferida (21%, 10.5%, 27%, 0%) a partir de iva/neto."""
    if c.neto_gravado == 0:
        return CERO
    ratio = (c.iva / c.neto_gravado * 100)
    # Encasillar a las alícuotas legales argentinas más cercanas.
    for legal in (Decimal("27"), Decimal("21"), Decimal("10.5"), Decimal("5"),
                  Decimal("2.5")):
        if abs(ratio - legal) <= Decimal("0.5"):
            return legal
    return _q(ratio)


@dataclass
class RenglonAlicuota:
    alicuota: Decimal
    neto: Decimal = CERO
    iva: Decimal = CERO

    def sumar(self, c: Comprobante) -> None:
        self.neto += c.neto_gravado_con_signo
        self.iva += c.iva_con_signo


@dataclass
class LiquidacionIVA:
    periodo: str                       # "2026-03"
    cuit: str

    # Apertura por alícuota
    ventas_por_alicuota: dict[Decimal, RenglonAlicuota] = field(default_factory=dict)
    compras_por_alicuota: dict[Decimal, RenglonAlicuota] = field(default_factory=dict)

    # Totales
    debito_fiscal: Decimal = CERO
    credito_fiscal: Decimal = CERO
    percepciones_iva: Decimal = CERO

    # Bases informativas
    neto_ventas: Decimal = CERO
    neto_compras: Decimal = CERO
    no_gravado_ventas: Decimal = CERO
    exento_ventas: Decimal = CERO

    # Advertencias de calidad (comprobantes sospechosos)
    advertencias: list[str] = field(default_factory=list)

    @property
    def saldo_tecnico(self) -> Decimal:
        """Débito - Crédito. Positivo = a pagar antes de percepciones."""
        return _q(self.debito_fiscal - self.credito_fiscal)

    @property
    def saldo_a_pagar(self) -> Decimal:
        """Saldo final tras aplicar percepciones. 0 si da a favor."""
        neto = self.saldo_tecnico - self.percepciones_iva
        return _q(neto) if neto > 0 else CERO

    @property
    def saldo_a_favor(self) -> Decimal:
        """Saldo a favor del contribuyente. 0 si hay saldo a pagar."""
        neto = self.percepciones_iva - self.saldo_tecnico
        return _q(neto) if neto > 0 else CERO


def liquidar(
    ventas: list[Comprobante],
    compras: list[Comprobante],
    periodo: str,
    cuit: str,
) -> LiquidacionIVA:
    """Calcula la liquidación de IVA de un período."""
    liq = LiquidacionIVA(periodo=periodo, cuit=cuit)

    def acumular(comprobantes, destino_alicuota, es_venta):
        for c in comprobantes:
            ali = _alicuota_efectiva(c)
            renglon = destino_alicuota.setdefault(ali, RenglonAlicuota(ali))
            renglon.sumar(c)
            if es_venta:
                liq.neto_ventas += c.neto_gravado_con_signo
                liq.debito_fiscal += c.iva_con_signo
                liq.no_gravado_ventas += c.no_gravado * c.signo
                liq.exento_ventas += c.exento * c.signo
            else:
                liq.neto_compras += c.neto_gravado_con_signo
                liq.credito_fiscal += c.iva_con_signo
                liq.percepciones_iva += c.percepciones_iva * c.signo
            # Control de calidad: alícuota fuera de las legales.
            if ali not in (CERO, Decimal("2.5"), Decimal("5"), Decimal("10.5"),
                           Decimal("21"), Decimal("27")):
                liq.advertencias.append(
                    f"Alícuota inusual {ali}% en {c.clave} "
                    f"({'venta' if es_venta else 'compra'})")

    acumular(ventas, liq.ventas_por_alicuota, es_venta=True)
    acumular(compras, liq.compras_por_alicuota, es_venta=False)

    # Redondeo final de totales.
    liq.debito_fiscal = _q(liq.debito_fiscal)
    liq.credito_fiscal = _q(liq.credito_fiscal)
    liq.percepciones_iva = _q(liq.percepciones_iva)
    liq.neto_ventas = _q(liq.neto_ventas)
    liq.neto_compras = _q(liq.neto_compras)
    return liq
