# CL-04 · Recuperación híbrida, RRF, rerank y búsqueda por número

## 1. Qué se ha construido

El motor de recuperación de la fase de consulta. Dado "¿qué dice el artículo 107?" o una
pregunta temática, devuelve los 6 mejores chunks con su puntuación:

- **RRF puro y estable** (`app.domain.ranking`): Reciprocal Rank Fusion, la fusión que
  combina dos rankings (el de similitud vectorial y el de texto completo) en uno solo,
  sumando contribuciones inversas a la posición de cada chunk en cada lista.
- **Servicio de recuperación** (`app.services.retrieval`): búsqueda vectorial **exacta**
  con `<=>` de pgvector, búsqueda de texto completo con `spanish_unaccent`, fusión RRF,
  reordenación final con el modelo `rerank` de NaN sobre el top `top_k*2`, y la ruta
  directa por número de artículo (con extracción del número en español: "artículo",
  "art.", ordinal con espacios y puntos).
- **API**: `GET /buscar` (el ranking híbrido sin LLM, para depurar) y
  `GET /articulos/{numero}`, más el mapeo tipado de errores del LLM.

Verificado a escala real con los 580 chunks ingeridos: AC-04 pasa por construcción
("¿Qué dice el artículo 107?" → primera posición `articulo=107`, rama `direct`, URL
`#a1-19`); una consulta temática devuelve `top_k=6` con `best_score` poblado (0.9057);
`/articulos/9999` responde 404 con el cuerpo tipado `article_not_found`. Gates: 63
unitarios y 16 de integración.

## 2. Cómo se ha hecho y por qué así

### Decisión: búsqueda vectorial exacta, sin índice ANN
- **Qué se eligió.** El operador `<=>` (distancia coseno exacta) sobre los 580 chunks.
- **Por qué.** Con 4.096 dimensiones los índices HNSW e IVFFlat de pgvector no aplican:
  su límite de dimensiones es inferior. La búsqueda exacta sobre 580 filas es rápida de
  sobra, así que la "optimización" brillante habría sido más lenta de implementar y
  menos determinista de verificar.

### Decisión: el orden del rerank se reconstruye por índice, no se confía en el proveedor
- **Qué se eligió.** El adaptador llama `POST /rerank`, lee el contrato de la
  documentación de NaN (`results[{index, relevance_score}]`) y **reconstruye** el orden
  final a partir de los `index`, fallando con error tipado (`RerankResponseError`) si la
  respuesta no cumple el contrato. En ningún caso se toma el orden de llegada del array.
- **Por qué.** El cliente conoce el orden esperado (es el mismo top que envió); delegar el
  orden en la respuesta hace que un cambio silencioso del proveedor invada tu ranking sin
  que ningún test lo detecte. Con la reconstrucción por índice, el orden es una función
  determinista de datos que sí puedes verificar con dos rankings falsos (AC-05).

### Decisión: ruta directa por número de artículo
- **Qué se eligió.** Si la pregunta menciona un artículo concreto, se recupera
  directamente por número, sin embeddings ni RRF.
- **Por qué.** AC-04 lo exige, y además es el caso donde toda la maquinaria semántica es
  ruido: cuando el usuario nombra el artículo, la búsqueda exacta por columna es más
  precisa y más barata que cualquier ranking. También es honesto para el estado: la
  respuesta puede indicar que la recuperación fue `direct`.

### Decisión: los errores predecibles del LLM son 503 y 502, no 500
- **Qué se eligió.** Sin `NAN_API_KEY`: 503 `llm_not_configured`. Cualquier otro fallo de
  la llamada: 502 `llm_unavailable`. El mismo sobre tipado que el 404 de artículo.
- **Por qué.** La API garantiza errores explícitos con mensaje útil (AGENTS §10); una
  falta de configuración es lo más previsible que puede ocurrir, y responderle con un
  500 con traceback por eso es un defecto, no un accidente (ver sección 3).

## 3. Errores detectados

### Sin API key, `/buscar` respondía 500 con traceback
- **Cómo se detectó.** En la verificación a escala real, pidiendo `/buscar` en un entorno
  sin `NAN_API_KEY`: la respuesta fue un 500 con traza.
- **Causa.** La excepción `MissingAPIKeyError` del adaptador no tenía mapeo en la capa de
  API: un error de configuración conocido escapaba como fallo interno genérico.
- **Qué se hizo.** Mapeo tipado (503/502 descritos arriba), cubierto por
  `tests/unit/test_api_errors.py`.

### Una clave ausente en la respuesta del rerank escapaba como excepción sin manejar
- **Cómo se detectó.** RED propio del orquestador: el guion del test sin esa clave hacía
  tronar el servicio con un `KeyError` no controlado, no con el error tipado que la
  decisión arriba exige.
- **Causa.** El contrato se verificaba a medias: el caso de respuesta mal formada
  existía en diseño pero no en los tests.
- **Qué se hizo.** Validación estricta de la respuesta en el adaptador con
  `RerankResponseError` tipado, que después mapea a `llm_unavailable`.

### La pregunta se embebe siempre, incluso en la ruta directa
- **Cómo se detectó.** En la revisión del slice (assess `medium`, 1.145 líneas):
  `hybrid_search` llama a embeddings aunque el número extraído ya resuelva la consulta.
  Es una llamada extra por consulta directa.
- **Qué se hizo.** Nada, deliberadamente: se anotó como trabajo posterior. No afecta
  resultados (solo coste) y arreglarlo requería reordenar el flujo del servicio, que
  queda para otro slice.

## 4. Cómo se iteró hasta una solución válida

RED del worker observado: `ModuleNotFoundError` de `app.domain.ranking` y
`app.services.retrieval`, `ImportError: RerankResponseError`. GREEN: 63 unitarios y 16 de
integración, con `mypy --strict` limpio en 44 ficheros.

La verificación a escala recorrió las tres ramas del servicio: ruta directa (AC-04 con el
art. 107 real y su `#a1-19`), ruta híbrida (consulta temática → 6 resultados con
`best_score=0.9057`, que con embeddings reales después se re-calibraría en CL-08) y la
capa de errores (404 tipado de artículo inexistente, y el defecto del 500 corregido con
tests propios). Cada rama se comprobó contra Postgres real, no contra mock de repositorio.

## 5. Conclusión: qué se aprende de esto

En una pipeline de RAG, cada pieza externa (un rerank HTTP, una API de embeddings) es un
contrato que hay que hacer valer, no un servicio amigable del que heredas comportamiento.
Leer la documentación del proveedor para el formato es el mínimo; el diseño robusto es el
que reconstruye lo que importa (el orden final) desde datos atómicos verificables (los
índices y sus scores) y rechaza todo lo demás con un error tipado. Así un cambio del
proveedor se convierte en un 502 con mensaje claro, no en un ranking silenciosamente
incorrecto.

Y el segundo aprendizaje es de clasificación de fallos: un 500 con traceback por una
API key ausente no es "un error del sistema", es una categoría confundida. Cuando el
fallo es previsible (falta configuración, proveedor caído, entrada mal formada), la
respuesta correcta es un código y un cuerpo específicos que el frontend y el usuario
pueden entender. La lista de errores tipados es, en realidad, la lista de estados por los
que tu pipeline puede pasar: escribirla es diseñar el sistema.
