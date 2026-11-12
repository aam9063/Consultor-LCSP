# CL-06 · Revisor de cláusulas

## 1. Qué se ha construido

La segunda cara del producto: en vez de responder preguntas, revisa un documento. Pegas
el texto de una cláusula de un pliego (hasta unas 800 palabras) y el sistema recupera los
artículos relevantes y devuelve una lista de avisos tipados:

- `{tipo: posible_incumplimiento | ambiguedad | ok, explicacion, articulos_citados,
  cita_de_la_clausula}` — los tres `tipo` que pide la spec S4 (la UI los muestra en
  español con tilde).
- Mismas reglas de trazabilidad que las respuestas: solo artículos recuperados y
  validados; si no hay base, "sin observaciones fundadas".

Dos commits: dominio puro (`app.domain.clauses`) con los motivos de rechazo estables
(`tipo_no_valido`, `sin_articulos_citados`, `articulo_no_recuperado`, `cita_no_encontrada`,
`aviso_mal_formado`) y servicio + `POST /revisiones` (`review_clause`). Verificado
con los 580 chunks reales: aviso "posible incumplimiento" citando un artículo
efectivamente recuperado valida con 1 llamada y 0 descartes; cita inventada `[art. 999]`
→ 2 llamadas (un solo reintento) y aviso descartado; sin base (rerank 0.02 bajo umbral) →
`sin_observaciones=True` y 0 llamadas. Gates: 112 unitarios, 26 de integración,
`mypy --strict` limpio.

## 2. Cómo se ha hecho y por qué así

### Decisión: el revisor reutiliza el parser de citas de las respuestas
- **Qué se eligió.** Los `articulos_citados` de los avisos viajan con el mismo formato
  `[art. X]` / `[art. X.Y]` del prompt y se parsean con la misma función
  `parse_citations` de CL-05.
- **Por qué.** Reimplementar el parseo para "avisos" habría creado una segunda
  definición de lo que es una cita, con sus propios bugs, y la regla de validación
  (artículo recuperado o rechazo) debía ser idéntica por diseño. Reutilizar es
  más barato y también un control de calidad: si el parser tiene un caso raro, un solo
  arreglo cubre las dos caras del producto.

### Decisión: un aviso citando un artículo no recuperado se descarta y se reporta, nunca se muestra
- **Qué se eligió.** La respuesta lleva `avisos` (ya validados) y `avisos_invalidos` con
  el motivo de rechazo de cada uno.
- **Por qué.** La promesa del producto es que cada aviso apunta a un artículo que
  realmente está en el contexto recuperado. Un aviso con cita fantasma no se "corrige"
  ni se muestra con asterisco: no se muestra. Pero sí se reporta con su motivo, porque
  ocultar por completo un descarte haría indistinguible "no hay avisos" de "hubo avisos
  y no pasaron", que son informaciones distintas para quien depura.

### Decisión: la ausencia de cláusula es 422 tipado en el propio endpoint
- **Qué se eligió.** Sin texto → `422 clausula_ausente` manejado en el endpoint de
  revisiones, no en un handler global; 801 palabras → `422 clausula_demasiado_larga`.
- **Por qué.** Un handler global habría cambiado el sobre de 422 de `/consultas`, que ya
  tenía tests: tocar código compartido para añadir un caso nuevo es exactamente lo que
  rompe comportamiento existente. El límite de palabras (800) viene de la
  spec S4 y su desborde es validación de entrada, no error del sistema.

### Decisión: exponer `chunks` también en el camino sin base
- **Qué se eligió.** Cuando no hay base y la respuesta es "sin observaciones fundadas",
  la respuesta igual incluye los chunks recuperados con sus puntuaciones.
- **Por qué.** "¿Por qué no observó nada?" es una pregunta legítima del usuario y de quien
  depura: mostrarle qué se recuperó (y qué no) hace la abstención auditable en vez de
  mágica. Decisión del worker, aceptada porque respeta el espíritu de trazabilidad del
  BRIEF.

## 3. Errores detectados

### El recuperador no trajo el art. 107 para una cláusula de garantía del 3%
- **Cómo se detectó.** Verificación con el caso real diseñado para el test: una cláusula
  que pacta una garantía del 3%, que choca con el 5% del art. 107. Para esa cláusula el
  recuperador (con embeddings del fake, no semánticos) devolvió `306, 266, DA23, 268,
  347, DA3` y **no** el 107.
- **Causa.** Con el `FakeLLMClient` la similitud no es semántica: es determinista y
  arreglada para el test. Pero el hallazgo quedó escrito en el feature document como el
  riesgo real: con embeddings verosímiles, ¿entra el artículo correcto en el top-6?
- **Qué se hizo.** Nada de esconderlo: se anotó como la pregunta a responder en CL-08, y
  la evaluación con embeddings reales la cuantificó (P-03, garantía definitiva, recuperó
  1.00; P-08, subcontratación, quedó en 0.50 porque el art. 216 no entró en el top-5).
- **Por qué importa.** Un revisor de cláusulas solo puede avisar de lo que recupera: la
  calidad del revisor está limitada por arriba por la calidad del recuperador.

### 404 en lugar de 422 en la validación de entrada
- **Cómo se detectó.** RED del worker: los tests de API con entrada vacía esperaban 422 y
  recibían 404.
- **Causa.** Confusión entre "no existe un recurso" (404) y "la petición está mal
  formada" (422) al validar el cuerpo.
- **Qué se hizo.** Corrección del worker en el GREEN; los tests quedaron cubriendo el
  sobre exacto de cada error (`422 clausula_ausente`, `422 clausula_demasiado_larga`).

## 4. Cómo se iteró hasta una solución válida

RED del worker observado: `ModuleNotFoundError: app.domain.clauses` y los 404/422 de la
sección anterior. GREEN: 112 unitarios, 26 de integración. La verificación del
orquestador recorrió con Postgres real los cuatro caminos: aviso válido (1 llamada, 0
descartes), aviso con cita inventada (2 llamadas, un solo reintento y `articulo_no_recuperado`
en `avisos_invalidos`), sin base (`model_called=False`, 0 llamadas, texto exacto "sin
observaciones fundadas") y los dos 422. RDD: assess `medium` (1.049 líneas), diferido al
cierre del slice según AGENTS §5, igual que CL-03 a CL-05.

La observación del 107 ausente no generó código ese día: generó una pregunta anotada con
lugar y hora de resolverse (la evaluación de CL-08). Ese es el ciclo correcto para
hallazgos fuera de alcance: no se arregla en bucle, se agenda con evidencia.

## 5. Conclusión: qué se aprende de esto

Pasar de "responder preguntas" a "revisar documentos" costó casi nada porque lo que
cambió es el orquestador, no las reglas: el mismo parser de citas, la misma validación
contra chunks recuperados, la misma abstención. Esa reutilización no es casualidad de
buen diseño: si las reglas de trazabilidad vivieran en dos módulos, un revisor y un
respondedor con comportamientos distintos serían una puerta falsa abierta en el sistema
(el usuario confía en que la barra de validez es la misma a ambos lados).

Y el hallazgo del 107 enseña lo contrario del instinto habitual: cuando tu test
diseñado "para pasar" no encuentra el artículo que esperabas, la reacción útil no es
ajustar el test ni el fake, sino preguntarse si eso puede pasar en producción. Aquí pasó
que el fake era la causa; pero el sospechoso natural (¿el recuperador real va a traer el
artículo correcto?) era una pregunta legítima que solo la evaluación con datos reales
podía responder. Anotarlo y agendarlo gana a disimularlo.
