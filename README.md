# LiquidIA — Liquidación Fiscal Automatizada para Estudios Contables

SaaS multi-tenant que automatiza la liquidación de IVA e Ingresos Brutos para
estudios contables argentinos. Pensado para estudios que todavía trabajan con
Excel: el contador sube su planilla, el sistema detecta el formato
automáticamente, concilia contra AFIP/ARCA y genera la declaración lista.

## Por qué existe

El proceso actual en la mayoría de los estudios es manual: descargar portal por
portal, abrir XML en Excel, copiar y pegar, conciliar a mano. Esto consume más
del 70% del tiempo operativo y es propenso a errores.

LiquidIA transforma ese flujo en uno automatizado, auditable y trazable, sin
exigir que el estudio cambie sus herramientas ni contrate IT.

## Arquitectura

```
Excel/CSV del estudio ──┐
                        ├──> Parser universal ──> Motor ETL ──> Motor de
AFIP/ARCA (RPA) ────────┘     (detecta formato)   (reglas IVA)   conciliación
                                                                      │
                                                                      ▼
                                                  Dashboard de excepciones
                                                                      │
                                                                      ▼
                                              TXT SIFERE / F.2002 ARCA
```

## Stack

| Capa | Tecnología |
|---|---|
| Parser + ETL | Python + Pandas |
| Conciliación | Python |
| RPA portales | Playwright |
| Clasificación excepciones | Claude API |
| Backend API | FastAPI |
| Frontend | Next.js |
| Base de datos / Auth / Storage | Supabase (PostgreSQL) |
| Cola de tareas | Celery + Redis |
| Pagos | Stripe |
| Hosting | Railway + Vercel |

## Estado actual

MVP en construcción. Primer slice funcional:

- [x] Parser universal de Excel/CSV (detección automática de columnas + separador)
- [x] Fallback de mapeo con Claude para headers no estándar
- [x] Modelo de datos de comprobantes
- [x] Motor de conciliación IVA (Libro IVA vs. AFIP)
- [x] RPA AFIP (Playwright) con modo mock para desarrollo
- [x] Motor de liquidación IVA (débito/crédito/saldo, apertura por alícuota)
- [x] Papel de trabajo exportable a Excel
- [ ] Dashboard de excepciones (FastAPI + Next.js)
- [ ] Multi-tenant + autenticación

## Cómo correr el núcleo

```bash
cd "SOLUCION AFIP"
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

python -m core.demo       # conciliación IVA Excel vs AFIP
python -m core.demo_ia    # fallback de mapeo con Claude (headers raros)
python -m core.demo_rpa   # pipeline completo: RPA AFIP -> parser -> conciliación
python -m core.demo_liquidacion  # liquidación IVA + papel de trabajo en Excel
```

## RPA de AFIP (real)

El módulo `core/rpa/afip.py` automatiza login con clave fiscal y descarga de
"Mis Comprobantes" con Playwright. Para correrlo de verdad:

```bash
playwright install chromium
export AFIP_CUIT=20XXXXXXXX9
export AFIP_CLAVE_FISCAL=...        # nunca commitear; en prod va al secret store
```

Mientras tanto, `core/rpa/mock_afip.py` genera un CSV con el formato real de
AFIP para desarrollar todo el pipeline sin credenciales. Las credenciales se
gestionan vía `core/rpa/credenciales.py` (multi-tenant por `tenant_id` + `cuit`),
nunca hardcodeadas.
