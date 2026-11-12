# Evaluación Consultor LCSP — 2026-11-12

- Corpus: LCSP consolidada (BOE-A-2017-12902, versión 2018-03-09)
- Preguntas: 25 (20 con base en la ley, 5 fuera de la ley)

## Métricas
- Recall@5: 100%
- Respuestas con todas las citas válidas: 90.0%
- Abstención correcta: 5/5 (100.0%)
- Abstenciones indebidas (preguntas con base en la ley): 0

## Objetivos (AC-10)
- Recall@5 >= 85%: objetivo **cumplido** (100.0%).
- Citas válidas >= 95%: objetivo **no cumplido** (90.0%).
- Abstención correcta: al menos 4 de 5 preguntas fuera de la ley — **cumplido** (5/5).
  - Por qué no se alcanza: hay respuestas que citan artículos fuera del contexto recuperado; revisar la validación de citas.

## Comparación: búsqueda híbrida frente a solo embeddings
- Recall@5 híbrido: 100% (solo embeddings: 100%, diferencia: +0.00 puntos)

| Pregunta | Híbrido | Solo embeddings |
| --- | --- | --- |
| P-01 — ¿Qué penalidades se imponen al contratista cuando incurre en demora en la ejecución del contrato? | 1.00 | 1.00 |
| P-02 — ¿Cuándo se exige la clasificación empresarial a los contratistas de obras? | 1.00 | 1.00 |
| P-03 — ¿Qué importe tiene la garantía definitiva y sobre qué precio se calcula? | 1.00 | 1.00 |
| P-04 — ¿Cuáles son los límites del contrato menor? | 1.00 | 1.00 |
| P-05 — ¿Qué características tiene el procedimiento abierto simplificado? | 1.00 | 1.00 |
| P-06 — ¿Qué criterios pueden usarse para adjudicar un contrato? | 1.00 | 1.00 |
| P-07 — ¿Qué ocurre cuando una oferta es anormalmente baja? | 1.00 | 1.00 |
| P-08 — ¿En qué condiciones puede el contratista subcontratar partes del contrato? | 1.00 | 1.00 |
| P-09 — ¿A partir de qué importe los contratos de suministro están sujetos a regulación armonizada? | 1.00 | 1.00 |
| P-10 — ¿Qué umbral aplica a los contratos de servicios sujetos a regulación armonizada? | 1.00 | 1.00 |
| P-11 — ¿Cuándo se exige garantía provisional y en qué consiste? | 1.00 | 1.00 |
| P-12 — ¿Qué reglas tiene la ley sobre el plazo de duración de los contratos y de ejecución de la prestación? | 1.00 | 1.00 |
| P-13 — ¿Quiénes están prohibidos de contratar con el sector público? | 1.00 | 1.00 |
| P-14 — ¿Cómo se acredita la solvencia económica y financiera? | 1.00 | 1.00 |
| P-15 — ¿Cómo se calcula el valor estimado del contrato? | 1.00 | 1.00 |
| P-16 — ¿Cuándo y cómo se formalizan los contratos? | 1.00 | 1.00 |
| P-17 — ¿En qué supuestos puede usarse el procedimiento negociado sin publicidad? | 1.00 | 1.00 |
| P-18 — ¿En qué plazo debe pagarse el precio al contratista? | 1.00 | 1.00 |
| P-19 — ¿Por qué causas puede resolverse un contrato administrativo de obras? | 1.00 | 1.00 |
| P-20 — ¿Cómo es la recepción de las obras y qué plazo de garantía tienen? | 1.00 | 1.00 |

## Peores casos
- Ninguna: todas las preguntas con base en la ley alcanzaron recall@5 = 1.0.
