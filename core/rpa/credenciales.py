"""Gestión de credenciales de clave fiscal.

REGLA DE ORO: las claves fiscales nunca se hardcodean ni se loguean. En
producción viven cifradas en el secret store (Supabase Vault / AWS Secrets
Manager) y se resuelven por (tenant_id, cuit). Acá definimos la interfaz y una
implementación de desarrollo basada en variables de entorno.

Para multi-tenant: un estudio (tenant) gestiona varias empresas (cada una con
su CUIT y su clave fiscal). La credencial se identifica por ambos.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class CredencialFiscal:
    cuit: str            # CUIT del representado (la empresa)
    clave_fiscal: str    # clave fiscal AFIP

    def __repr__(self) -> str:  # nunca exponer la clave en logs/trazas
        return f"CredencialFiscal(cuit={self.cuit}, clave_fiscal=***)"


class ProveedorCredenciales:
    """Interfaz. En producción se implementa contra el secret store."""

    def obtener(self, tenant_id: str, cuit: str) -> CredencialFiscal:
        raise NotImplementedError


class CredencialesDesdeEntorno(ProveedorCredenciales):
    """Implementación de desarrollo: lee de variables de entorno.

    Espera:
      AFIP_CUIT          -> CUIT a usar
      AFIP_CLAVE_FISCAL  -> clave fiscal
    Ignora tenant_id/cuit (modo single-tenant de desarrollo)."""

    def obtener(self, tenant_id: str, cuit: str) -> CredencialFiscal:
        clave = os.environ.get("AFIP_CLAVE_FISCAL")
        cuit_env = os.environ.get("AFIP_CUIT", cuit)
        if not clave:
            raise RuntimeError(
                "Falta AFIP_CLAVE_FISCAL en el entorno. En producción esto se "
                "resuelve desde el secret store por (tenant_id, cuit)."
            )
        return CredencialFiscal(cuit=cuit_env, clave_fiscal=clave)
