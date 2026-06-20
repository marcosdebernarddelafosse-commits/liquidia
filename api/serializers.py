"""Conversión de los objetos del núcleo a dicts JSON-serializables."""

from __future__ import annotations

from core.conciliacion import ResultadoItem, ResumenConciliacion
from core.liquidacion import LiquidacionIVA


def item_a_dict(item: ResultadoItem) -> dict:
    ref = item.comp_estudio or item.comp_afip
    return {
        "clave": item.clave,
        "estado": item.estado.value,
        "razon_social": ref.razon_social if ref else "",
        "fecha": ref.fecha.isoformat() if ref else None,
        "neto_estudio": float(item.comp_estudio.neto_gravado) if item.comp_estudio else None,
        "neto_afip": float(item.comp_afip.neto_gravado) if item.comp_afip else None,
        "dif_neto": float(item.dif_neto),
        "dif_iva": float(item.dif_iva),
        "detalle": item.detalle,
    }


def conciliacion_a_dict(resumen: ResumenConciliacion) -> dict:
    return {
        "total": resumen.total,
        "conciliados": resumen.conciliados,
        "tasa_conciliacion": resumen.tasa_conciliacion,
        "por_estado": resumen.por_estado(),
        "excepciones": [item_a_dict(i) for i in resumen.excepciones],
    }


def liquidacion_a_dict(liq: LiquidacionIVA) -> dict:
    def renglones(por_alicuota):
        return [
            {"alicuota": float(a), "neto": float(r.neto), "iva": float(r.iva)}
            for a, r in sorted(por_alicuota.items(), reverse=True)
        ]

    return {
        "periodo": liq.periodo,
        "cuit": liq.cuit,
        "ventas_por_alicuota": renglones(liq.ventas_por_alicuota),
        "compras_por_alicuota": renglones(liq.compras_por_alicuota),
        "debito_fiscal": float(liq.debito_fiscal),
        "credito_fiscal": float(liq.credito_fiscal),
        "percepciones_iva": float(liq.percepciones_iva),
        "saldo_tecnico": float(liq.saldo_tecnico),
        "saldo_a_pagar": float(liq.saldo_a_pagar),
        "saldo_a_favor": float(liq.saldo_a_favor),
        "advertencias": liq.advertencias,
    }
