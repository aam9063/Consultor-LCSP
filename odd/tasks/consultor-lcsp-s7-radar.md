# Feature: Consultor LCSP · Fase 2 — S7 Conexión con Radar de Pliegos

Spec: `BRIEF.md` (Fase 2, S7) + `AGENTS.md`. Fase 1 cerrada y en `dev`; S8 cerrada. Esta feature
estaba **paralizada** por decisión de Albert (L2 de `consultor-lcsp-s8-feedback.md`); se desbloquea
con L1 de este documento.

**Objetivo (BRIEF §5, Fase 2, literal):**

> - **S7 · Conexión con Radar de Pliegos**: el revisor recibe las penalidades o garantías extraídas por Radar y las contrasta con la LCSP.

**Problema que resuelve:** Radar extrae de un pliego las penalidades y la garantía definitiva como
texto verbatim, pero no sabe si lo que el pliego exige cabe en la LCSP. Consultor sabe contrastar
una cláusula contra el corpus, pero hoy solo recibe texto pegado a mano. Sin esta conexión, quien
analiza un pliego copia el texto de Radar a la vista del revisor y pierde la trazabilidad de qué
campo venía de dónde.

## Contrato real de Radar (verificado, no supuesto)

- `GET /licitaciones/{id}/ficha` devuelve `FichaOut.datos` = `PliegoFicha`
  (`backend/app/domain/pliego_ficha.py:110-152` del repo de Radar).
- `penalidades: CampoExtraido[list[str]]`, `garantia_definitiva: CampoExtraido[str]`: **texto libre
  verbatim**, sin números normalizados ni enum de tipos.
- Sin autenticación; FastAPI en `api:8000` dentro de su propio compose.
- Radar **no declara** nada sobre esta integración en su `BRIEF.md`.

## Specs

- **S1 · Endpoint de recepción.** `POST /revisiones/radar` acepta
  `{licitacion_id: int, expediente: str | null, penalidades: list[str], garantia_definitiva: str | null}`
  y devuelve los avisos del revisor. Consultor no consulta a Radar: **Radar empuja** (decisión de
  Albert, L2).
- **S2 · Alcance de campos.** Solo `penalidades` y `garantia_definitiva` (decisión de Albert, L2).
  `garantia_provisional` y `subcontratacion_limites` quedan fuera.
- **S3 · Contraste contra la LCSP.** Los campos se componen en un texto con etiquetas de origen
  para que el revisor los contraste en una sola pasada, reutilizando el motor de cláusulas existente
  (mismas reglas: solo artículos recuperados, citas validadas, `sin observaciones fundadas` si no hay
  base, abstención antes de generar si el rerank no da base).
- **S4 · Trazabilidad del origen.** Cada aviso identifica de qué campo viene (`penalidades` o
  `garantia_definitiva`) y conserva la cita literal del pliego; la respuesta repite la entrada
  recibida (`licitacion_id`, `expediente`) para poder cruzarla con Radar.
- **S5 · Errores tipados.** Mismo sobre `{"error": {"code", "message"}}`: ficha sin datos
  (`ficha_sin_datos`), texto por encima del límite del revisor (`ficha_demasiado_larga`), cuerpo
  inválido (422). Nunca un 500 previsible.
- **S6 · Verificación.** Unitarios de composición y validación; integración del endpoint contra el
  corpus real con `FakeLLMClient` (cita válida, cita inventada descartada, sin base →
  `sin_observaciones` y cero llamadas al modelo). Sin llamadas reales a la IA. CI en verde.

## Non-goals

Consultar la API de Radar (pull); autenticación entre servicios; persistir la ficha; normalizar
cifras a números; garantía provisional o subcontratación; tocar Radar (es otro repo).

## Restricciones

- Stack, TDD, RDD y CI según `AGENTS.md`. Sin dependencias nuevas: el payload es JSON y se valida con
  Pydantic, igual que el resto de la API.
- Una sola pasada de generación por petición (coste acotado); el límite de palabras del revisor se
  aplica al texto compuesto.

## Configuración de proceso

- **TDD: activado** (fuente `AGENTS.md` §4). Runners: `uv run pytest`,
  `uv run pytest tests/integration`, `pnpm vitest run`.
- **RDD: activado.** `assess` tras cada work-unit commit; `medium` se revisa al cerrar el slice;
  `high` se revisa de inmediato.
- **Entrega:** autorización permanente de Albert (AGENTS §6): push, PR contra `dev`, CI verde, merge
  commit, nunca a `main`.

## Tasks

| ID | Tarea | Specs | Ruta | Commit |
| --- | --- | --- | --- | --- |
| S7-01 | Dominio: composición de la ficha y validación de entrada | S1, S2, S3, S5 | pendiente | — |
| S7-02 | Servicio de contraste reutilizando el motor de cláusulas | S3, S4 | pendiente | — |
| S7-03 | `POST /revisiones/radar` con errores tipados | S1, S4, S5 | pendiente | — |
| S7-04 | Tests de integración contra el corpus real | S6 | pendiente | — |
| S7-05 | Documento de aprendizaje y cierre | S6 | pendiente | — |

## Evidencias de verificación

Se rellena por tarea.

## Progreso y siguiente paso

- Progreso: 0/5.
- Siguiente paso: S7-01 con RED observado.

## Log

- **L1 (decisión de Albert, 2026-11-13, literal):** "ok. Mira radar ya esta terminado. aqui tienes el repo https://github.com/aam9063/Radar-de-Pliegos" — Radar de Pliegos terminado; queda desbloqueada S7, que estaba paralizada por L2 de la feature de S8.
- **L2 (decisiones de Albert, 2026-11-13, vía cuestionario):**
  - Dirección: **"Push: Radar envía el payload"**, con la vista previa de `POST /revisiones/radar` (`licitacion_id`, `expediente`, `penalidades`, `garantia_definitiva` → avisos con artículos validados contra el corpus).
  - Alcance: **"Solo penalidades y garantía definitiva"**.
- **L3 (hecho, 2026-11-13):** contrato de Radar verificado en su repo (`C:/Users/alber/orca/Radar-de-Pliegos`, solo lectura): `GET /licitaciones/{id}/ficha` → `datos` con `penalidades` (lista de frases verbatim) y `garantia_definitiva` (frase), sin normalizar y sin auth.
