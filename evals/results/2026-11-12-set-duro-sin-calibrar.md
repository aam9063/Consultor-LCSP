# Evaluación Consultor LCSP — 2026-11-12

- Corpus: LCSP consolidada (BOE-A-2017-12902, versión 2018-03-09)
- Preguntas: 25 (20 con base en la ley, 5 fuera de la ley)

## Métricas
- Recall@5: 75%
- Respuestas con todas las citas válidas: 100.0%
- Abstención correcta: 5/5 (100.0%)
- Abstenciones indebidas (preguntas con base en la ley): 5

## Objetivos (AC-10)
- Recall@5 >= 85%: objetivo **no cumplido** (75.0%).
- Citas válidas >= 95%: objetivo **cumplido** (100.0%).
- Abstención correcta: al menos 4 de 5 preguntas fuera de la ley — **cumplido** (5/5).
  - Por qué no se alcanza: ver Peores casos (P-03, P-08, P-16, P-19, P-20); el artículo esperado no entró en el top-5 recuperado.

## Comparación: búsqueda híbrida frente a solo embeddings
- Recall@5 híbrido: 75% (solo embeddings: 97.5%, diferencia: -22.50 puntos)

| Pregunta | Híbrido | Solo embeddings |
| --- | --- | --- |
| P-03 — Nos han adjudicado un contrato y nos piden aportar la garantía definitiva: ¿de qué porcentaje parte y sobre qué precio se calcula? | 0.00 | 1.00 |
| P-08 — El adjudicatario nos pregunta si puede encargar parte de la prestación a otras empresas: ¿qué condiciones pone la ley para eso y en qué plazo tiene después que pagarles? | 0.00 | 0.50 |
| P-16 — La empresa adjudicataria quiere saber cómo se firma el contrato: ¿ante qué documento se hace, quién soporta el coste si se eleva a escritura pública y se puede tocar el contenido de la adjudicación? | 0.00 | 1.00 |
| P-19 — El contratista lleva un retraso enorme y dudamos si continuar con él: ¿por qué causas puede resolverse el contrato antes de terminar la prestación? | 0.00 | 1.00 |
| P-20 — La obra está terminada y vamos a hacer la recepción: ¿cómo se desarrolla el acta, cuándo empieza el periodo de garantía y quién responde si años después aparecen vicios ocultos? | 0.00 | 1.00 |
| P-01 — El contratista lleva tres semanas de retraso injustificado en la ejecución: ¿qué multas puede aplicarnos el órgano de contratación y cómo se hacen efectivas después? | 1.00 | 1.00 |
| P-02 — Estamos preparando la licitación de una obra de 600.000 euros: ¿es obligatorio que las empresas licitadoras estén clasificadas y qué aporta esa clasificación frente a acreditar la solvencia por otros medios? | 1.00 | 1.00 |
| P-04 — Solo necesito comprar material de oficina por unos 12.000 euros sin montar todo el expediente de licitación: ¿qué dice la ley sobre las compras de esta cuantía y qué documentación exige? | 1.00 | 1.00 |
| P-05 — Para agilizar una licitación de servicios de 90.000 euros cuyos criterios son todos automáticos, ¿qué procedimiento ligero nos permite la ley y qué condiciones tiene? | 1.00 | 1.00 |
| P-06 — Estamos redactando los criterios con los que puntuaremos las ofertas: ¿qué clases de criterios admite la ley y qué se puede llegar a valorar? | 1.00 | 1.00 |
| P-07 — En una licitación llega una oferta sospechosamente barata, muy por debajo de las demás: ¿qué debe hacer el órgano de contratación antes de poder excluir a ese licitador? | 1.00 | 1.00 |
| P-09 — Vamos a comprar equipos informáticos por un valor estimado de 150.000 euros desde la Administración General del Estado: ¿estamos sujetos a regulación armonizada? | 1.00 | 1.00 |
| P-10 — Un hospital del sector público autonómico va a contratar un servicio de mantenimiento por 250.000 euros: ¿supera el umbral de contratación armonizada y hay casos con cifras distintas? | 1.00 | 1.00 |
| P-11 — ¿Podemos pedir a los licitadores un depósito al inicio del procedimiento para responder del mantenimiento de sus ofertas y, en tal caso, hasta qué porcentaje podemos exigir? | 1.00 | 1.00 |
| P-12 — El pliego va a fijar cuánto dura el contrato y si habrá prórrogas: ¿qué exige la ley sobre cómo fijar esos plazos y sobre el preaviso cuando llega el vencimiento? | 1.00 | 1.00 |
| P-13 — Un licitador tiene una condena firme por cohecho: ¿puede contratar con la Administración y en qué otras circunstancias está prohibido contratar? | 1.00 | 1.00 |
| P-14 — Estamos definiendo la documentación que deben aportar los licitadores para acreditar su capacidad económica: ¿qué medios acepta la ley para ello? | 1.00 | 1.00 |
| P-15 — Al preparar el expediente me piden justificar el importe que servirá de referencia para decidir el procedimiento: ¿qué debe incluir exactamente ese cálculo, por ejemplo las prórrogas o las modificaciones previsibles? | 1.00 | 1.00 |
| P-17 — Con la urgencia de una obra, ¿en qué casos puede el órgano de contratación adjudicar directamente sin publicar anuncio en el perfil de contratante? | 1.00 | 1.00 |
| P-18 — Un proveedor nos reclama porque llevamos 45 días sin pagarle una certificación ya aprobada: ¿en qué plazo debe pagar la Administración y qué genera pasarse de ese plazo? | 1.00 | 1.00 |

## Respuestas sin citas válidas
- Ninguna: todas las respuestas generadas citan artículos del contexto recuperado.

## Peores casos
- **P-03** (recall@5 0.00): Nos han adjudicado un contrato y nos piden aportar la garantía definitiva: ¿de qué porcentaje parte y sobre qué precio se calcula? — recuperados: ninguno
- **P-08** (recall@5 0.00): El adjudicatario nos pregunta si puede encargar parte de la prestación a otras empresas: ¿qué condiciones pone la ley para eso y en qué plazo tiene después que pagarles? — recuperados: ninguno
- **P-16** (recall@5 0.00): La empresa adjudicataria quiere saber cómo se firma el contrato: ¿ante qué documento se hace, quién soporta el coste si se eleva a escritura pública y se puede tocar el contenido de la adjudicación? — recuperados: ninguno
- **P-19** (recall@5 0.00): El contratista lleva un retraso enorme y dudamos si continuar con él: ¿por qué causas puede resolverse el contrato antes de terminar la prestación? — recuperados: ninguno
- **P-20** (recall@5 0.00): La obra está terminada y vamos a hacer la recepción: ¿cómo se desarrolla el acta, cuándo empieza el periodo de garantía y quién responde si años después aparecen vicios ocultos? — recuperados: ninguno
