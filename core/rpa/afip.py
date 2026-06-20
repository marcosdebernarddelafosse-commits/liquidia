"""Automatización de AFIP / ARCA — descarga de 'Mis Comprobantes'.

Flujo automatizado:
  1. Login con clave fiscal en auth.afip.gob.ar
  2. Acceso al servicio 'Mis Comprobantes'
  3. Selección de empresa representada (si corresponde), período y tipo
     (emitidos / recibidos)
  4. Descarga del CSV de comprobantes

Notas de realidad:
  - El portal de AFIP cambia con frecuencia y sin aviso. Por eso los selectores
    se concentran acá y se prueban varias estrategias antes de fallar.
  - Esta automatización corre en modo headless en producción (worker Celery),
    pero conviene debuggear con headless=False.
  - Se ejecuta CONTRA PRODUCCIÓN de AFIP: nunca correr en bucle ni en paralelo
    masivo sobre el mismo CUIT (riesgo de bloqueo).

El módulo no se importa pesado: Playwright solo se importa al ejecutar.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from .credenciales import CredencialFiscal


AFIP_LOGIN_URL = "https://auth.afip.gob.ar/contribuyente_/login.xhtml"
SERVICIO_MIS_COMPROBANTES = "Mis Comprobantes"


class ErrorRPA(Exception):
    """Error recuperable de automatización (login, navegación, descarga)."""


class ErrorLogin(ErrorRPA):
    """Credenciales rechazadas o portal de login cambiado."""


@dataclass
class ParametrosDescarga:
    cuit_representado: str
    desde: date
    hasta: date
    emitidos: bool = True          # True=ventas (emitidos), False=compras (recibidos)
    directorio_salida: str = "/tmp/liquidia_descargas"


@dataclass
class ResultadoDescarga:
    ruta_csv: str
    cantidad_estimada: int
    parametros: ParametrosDescarga


class ClienteAFIP:
    """Driver de Playwright para AFIP. Usar como context manager."""

    def __init__(self, headless: bool = True, timeout_ms: int = 30_000):
        self.headless = headless
        self.timeout_ms = timeout_ms
        self._pw = None
        self._browser = None
        self._context = None
        self.page = None

    def __enter__(self) -> "ClienteAFIP":
        from playwright.sync_api import sync_playwright
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=self.headless)
        self._context = self._browser.new_context(
            accept_downloads=True,
            locale="es-AR",
        )
        self.page = self._context.new_page()
        self.page.set_default_timeout(self.timeout_ms)
        return self

    def __exit__(self, *exc) -> None:
        for cerrar in (self._context, self._browser):
            try:
                if cerrar:
                    cerrar.close()
            except Exception:
                pass
        if self._pw:
            self._pw.stop()

    # -- Login -------------------------------------------------------------
    def login(self, credencial: CredencialFiscal) -> None:
        """Login en dos pasos: CUIT, luego clave fiscal."""
        page = self.page
        page.goto(AFIP_LOGIN_URL)

        # Paso 1: CUIT
        page.fill("#F1\\:username", credencial.cuit)
        page.click("#F1\\:btnSiguiente")

        # Paso 2: clave fiscal
        page.fill("#F1\\:password", credencial.clave_fiscal)
        page.click("#F1\\:btnIngresar")

        # Verificación: si seguimos en login, las credenciales fallaron.
        page.wait_for_load_state("networkidle")
        if "login" in page.url.lower():
            # AFIP muestra un mensaje de error sin cambiar de URL.
            mensaje = self._texto_seguro(".ui-messages-error, .error")
            raise ErrorLogin(f"Login rechazado por AFIP. {mensaje}".strip())

    # -- Navegación al servicio -------------------------------------------
    def abrir_mis_comprobantes(self) -> None:
        page = self.page
        # El buscador de servicios del portal cambia de selector seguido;
        # probamos por placeholder y por rol.
        for estrategia in (
            lambda: page.get_by_placeholder("Buscar").fill(SERVICIO_MIS_COMPROBANTES),
            lambda: page.fill("input[type='search']", SERVICIO_MIS_COMPROBANTES),
        ):
            try:
                estrategia()
                break
            except Exception:
                continue
        else:
            raise ErrorRPA("No se encontró el buscador de servicios en el portal.")

        page.get_by_text(SERVICIO_MIS_COMPROBANTES, exact=False).first.click()
        page.wait_for_load_state("networkidle")

    # -- Descarga ----------------------------------------------------------
    def descargar(self, params: ParametrosDescarga) -> ResultadoDescarga:
        page = self.page
        salida = Path(params.directorio_salida)
        salida.mkdir(parents=True, exist_ok=True)

        # Seleccionar empresa representada (si el usuario representa a varias).
        self._seleccionar_representado(params.cuit_representado)

        # Tipo de comprobante: emitidos vs recibidos.
        solapa = "Emitidos" if params.emitidos else "Recibidos"
        page.get_by_role("link", name=solapa).click()

        # Rango de fechas (formato dd/mm/aaaa en AFIP).
        page.fill("input[name='fechaEmisionDesde']", params.desde.strftime("%d/%m/%Y"))
        page.fill("input[name='fechaEmisionHasta']", params.hasta.strftime("%d/%m/%Y"))
        page.get_by_role("button", name="Buscar").click()
        page.wait_for_load_state("networkidle")

        # Disparar la descarga del CSV capturando el evento.
        with page.expect_download(timeout=self.timeout_ms) as dl_info:
            page.get_by_role("button", name="Descargar").click()
        download = dl_info.value

        tipo = "emitidos" if params.emitidos else "recibidos"
        nombre = (f"afip_{params.cuit_representado}_{tipo}_"
                  f"{params.desde:%Y%m%d}_{params.hasta:%Y%m%d}.csv")
        ruta = salida / nombre
        download.save_as(str(ruta))

        return ResultadoDescarga(
            ruta_csv=str(ruta),
            cantidad_estimada=self._contar_filas(ruta),
            parametros=params,
        )

    # -- Helpers -----------------------------------------------------------
    def _seleccionar_representado(self, cuit: str) -> None:
        page = self.page
        try:
            page.get_by_text(cuit, exact=False).first.click(timeout=5_000)
            page.wait_for_load_state("networkidle")
        except Exception:
            # Si no aparece selector, el usuario opera con su propio CUIT.
            pass

    def _texto_seguro(self, selector: str) -> str:
        try:
            return self.page.locator(selector).first.inner_text(timeout=2_000)
        except Exception:
            return ""

    @staticmethod
    def _contar_filas(ruta: Path) -> int:
        try:
            with open(ruta, encoding="utf-8", errors="ignore") as fh:
                return max(0, sum(1 for _ in fh) - 1)  # menos el header
        except Exception:
            return 0


def descargar_comprobantes(
    credencial: CredencialFiscal,
    params: ParametrosDescarga,
    headless: bool = True,
    reintentos: int = 2,
) -> ResultadoDescarga:
    """Orquesta login + descarga con reintentos ante fallos transitorios."""
    ultimo_error: Exception | None = None
    for intento in range(1, reintentos + 1):
        try:
            with ClienteAFIP(headless=headless) as cliente:
                cliente.login(credencial)
                cliente.abrir_mis_comprobantes()
                return cliente.descargar(params)
        except ErrorLogin:
            raise  # credenciales malas no se reintentan
        except Exception as e:
            ultimo_error = e
            if intento < reintentos:
                time.sleep(3 * intento)  # backoff
    raise ErrorRPA(f"Descarga fallida tras {reintentos} intentos: {ultimo_error}")
