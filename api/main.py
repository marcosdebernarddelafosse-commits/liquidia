"""API HTTP de LiquidIA.

Envuelve el motor del núcleo en endpoints REST y sirve el dashboard. El contador
sube su Libro IVA de ventas y compras (y opcionalmente el CSV de AFIP), el
sistema concilia, liquida y devuelve excepciones + saldo + papel de trabajo.

Persistencia: store en memoria para el MVP. En producción se reemplaza por
Postgres/Supabase con aislamiento por tenant. Marcado con TODO(persistencia).

Correr con:  uvicorn api.main:app --reload
"""

from __future__ import annotations

import tempfile
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse

from core.conciliacion import conciliar
from core.exportar import exportar_papel_de_trabajo
from core.liquidacion import LiquidacionIVA, liquidar
from core.models import TipoOperacion
from core.parser import parsear

from .serializers import conciliacion_a_dict, liquidacion_a_dict

app = FastAPI(title="LiquidIA", version="0.1.0")

_ESTATICO = Path(__file__).parent / "static"


# --------------------------------------------------------------------------
# Store en memoria  (TODO(persistencia): mover a Postgres/Supabase por tenant)
# --------------------------------------------------------------------------
@dataclass
class Liquidacion:
    id: str
    liq: LiquidacionIVA
    conciliacion: dict | None = None
    ruta_papel: str | None = None
    advertencias_parser: list[str] = field(default_factory=list)


_STORE: dict[str, Liquidacion] = {}


def _guardar_subida(archivo: UploadFile, carpeta: Path) -> Path:
    destino = carpeta / archivo.filename
    destino.write_bytes(archivo.file.read())
    return destino


# --------------------------------------------------------------------------
# Endpoints
# --------------------------------------------------------------------------
@app.post("/api/liquidaciones")
async def crear_liquidacion(
    periodo: str = Form(...),
    cuit: str = Form(...),
    ventas: UploadFile = File(...),
    compras: UploadFile = File(...),
    afip_ventas: UploadFile | None = File(None),
):
    """Procesa el período: parsea, (concilia si hay AFIP), liquida y exporta."""
    carpeta = Path(tempfile.mkdtemp(prefix="liquidia_"))
    ruta_v = _guardar_subida(ventas, carpeta)
    ruta_c = _guardar_subida(compras, carpeta)

    comp_ventas, map_v = parsear(str(ruta_v), TipoOperacion.VENTA, "excel")
    comp_compras, map_c = parsear(str(ruta_c), TipoOperacion.COMPRA, "excel")

    faltas = []
    if map_v.faltantes:
        faltas.append(f"ventas: no se detectaron {map_v.faltantes}")
    if map_c.faltantes:
        faltas.append(f"compras: no se detectaron {map_c.faltantes}")
    if faltas:
        raise HTTPException(
            422, detail={"error": "columnas no reconocidas", "detalle": faltas})

    liq = liquidar(comp_ventas, comp_compras, periodo=periodo, cuit=cuit)

    conciliacion = None
    if afip_ventas is not None:
        ruta_afip = _guardar_subida(afip_ventas, carpeta)
        comp_afip, _ = parsear(str(ruta_afip), TipoOperacion.VENTA, "afip")
        conciliacion = conciliacion_a_dict(conciliar(comp_ventas, comp_afip))

    ident = uuid.uuid4().hex[:12]
    ruta_papel = exportar_papel_de_trabajo(
        liq, str(carpeta / f"papel_trabajo_{periodo}.xlsx"))
    _STORE[ident] = Liquidacion(
        id=ident, liq=liq, conciliacion=conciliacion, ruta_papel=ruta_papel)

    resp = {"id": ident, "liquidacion": liquidacion_a_dict(liq)}
    if conciliacion is not None:
        resp["conciliacion"] = conciliacion
    return resp


@app.get("/api/liquidaciones/{ident}")
async def obtener_liquidacion(ident: str):
    item = _STORE.get(ident)
    if not item:
        raise HTTPException(404, "liquidación no encontrada")
    resp = {"id": item.id, "liquidacion": liquidacion_a_dict(item.liq)}
    if item.conciliacion is not None:
        resp["conciliacion"] = item.conciliacion
    return resp


@app.get("/api/liquidaciones/{ident}/papel")
async def descargar_papel(ident: str):
    item = _STORE.get(ident)
    if not item or not item.ruta_papel:
        raise HTTPException(404, "papel de trabajo no disponible")
    return FileResponse(
        item.ruta_papel,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=Path(item.ruta_papel).name,
    )


@app.get("/api/health")
async def health():
    return {"ok": True, "liquidaciones_en_memoria": len(_STORE)}


# --------------------------------------------------------------------------
# Frontend
# --------------------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
async def index():
    return (_ESTATICO / "index.html").read_text(encoding="utf-8")
