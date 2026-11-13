# FX — El umbral que vetaba artículos nombrados

Fecha: 2026-11-13 · Commit: `8e10bad` · Líneas: 120 (1 fichero de producto + 2 de test)

## 1. Qué se ha construido

La corrección de la abstención indebida cuando la pregunta **nombra un artículo**: el sistema lo
recuperaba bien por número y después lo descartaba, contestando "No encuentro base en la LCSP para
responder esto". Ahora el umbral de rerank solo decide cuando **ningún** chunk vino de la ruta
directa: un artículo nombrado que existe es base por definición.

## 2. Cómo se ha hecho y por qué así

- **El umbral deja de aplicar si hubo ruta directa.** `answer_question` calculaba
  `best_score < rerank_threshold` sobre todos los casos. Se añadió `_resolved_by_direct_route`, que
  mira si algún chunk trae la rama `direct` en sus `branches`, y el umbral solo se evalúa cuando no
  la hay. Razón: el score mide solapamiento semántico pregunta/texto, y una pregunta del tipo
  "¿qué dice el art. 5?" no aporta contenido; el artículo corto puntúa bajo con independencia de
  ser exactamente lo que se pidió. *Alternativa descartada:* bajar el umbral global a 0.75. Se
  descartó porque el 0.85 está calibrado con datos reales (con base legal ≥ 0.958, fuera de la ley
  ≤ 0.757) y bajarlo reabriría las preguntas fuera de la ley, que es el caso que el umbral existe
  para atajar.
- **Nada más cambia.** Sin chunks → abstiene; chunks sin rama directa y bajo umbral → abstiene (AC-07
  intacto); abstención del propio modelo → igual; validación de citas y afirmaciones no respaldadas
  → igual. El arreglo es una condición, no un rediseño.
- **Test de integración con el fixture real, no con un caso inventado.** El artículo 5 no existe en
  los fixtures, así que se usó el 159 de `retrieval_lcsp.xml` y se fijaron los scores del rerank falso
  por debajo del umbral **derivado de la configuración** (`threshold - 0.05`), sin números sueltos.
  Afirma no-abstención, una única llamada a generación y que los chunks del 159 traen `direct`; no
  afirma magnitudes de score.

## 3. Errores detectados

- **El defecto mismo (producto).** Reportado por Albert con una captura: preguntó por un artículo y
  la UI dijo que no lo encontraba. Medido: art. 1 → 0.8302, art. 5 → 0.8084, art. 17 → 0.8433,
  art. 38 → 0.8031, todos con el artículo correcto **ya recuperado** en primera posición. Cuatro de
  diez muestreados caían en la trampa.
- **Por qué los tests no lo vieron (proceso).** AC-04 fija la pregunta con el artículo 107, que
  puntúa 0.9456: el criterio de aceptación pasó con el mejor caso posible. Un criterio con un solo
  ejemplo no fija una regla, fija un ejemplo. La evaluación (AC-10) tampoco lo detectó: sus 25
  preguntas son temáticas, no "dame el artículo N".
- **Diagnóstico del entorno (propio, de esta sesión).** Mi primera hipótesis fue "el corpus está
  vacío" y la segunda "el navegador habla con otro backend". Las dos eran falsas y descartables con
  datos: los logs del api no tenían ninguna petición a la hora de la captura, y un `POST /feedback`
  posterior a las 12:52 probaba que la app sí funcionaba. Lo que resolvió el caso fue leer la tabla
  `feedback` (la fila guardada por el propio Albert) y medir el score del artículo concreto. Sin esa
  medición habría contestado una explicación plausible y equivocada.
- **Sesgo de confirmación evitado.** Antes de tocar código probé la pregunta exacta de la captura
  ("¿qué dice el art. 193?") y funcionaba: no abstiene. Eso obligó a buscar qué preguntas sí fallan
  (el art. 5 de la misma captura) en vez de "arreglar" un caso que ya andaba.

## 4. Cómo se iteró hasta una solución válida

1. Reproducción por la API: `/buscar` devuelve art. 193 primero, `best_score=0.976` → no es la
   recuperación.
2. `/consultas` con art. 193 → `abstencion: false`, con respuesta. La captura mostraba otra cosa →
   había que aislar qué consulta sí abstenía.
3. Muestra de diez artículos: cuatro (`1`, `5`, `17`, `38`) con `best_score` 0.80–0.84, por debajo
   del 0.85, y **el artículo correcto en la primera posición** en los cuatro.
4. Causa: el umbral se evaluaba sin distinguir si el artículo se había resuelto por número.
5. RED (unitario): un retrieval con chunk de rama `direct` y score bajo abstiene en vez de generar
   → `assert True is False`, 1 failed / 7 passed.
6. GREEN: `_resolved_by_direct_route` + condición; 8 passed.
7. RED de integración (honesto): con el fix ya puesto, se neutralizó el helper (`return False`) y el
   test nuevo falló con `assert True is False`; restaurado → 7 passed. Es una comprobación por
   mutación, no un RED cronológico, y se reporta como tal.
8. Verificación en vivo tras reconstruir las imágenes: arts. 1, 5, 17, 38 ahora responden con su
   cita correcta; la pregunta de IVA sigue absteniéndose; la misma consulta por el dev server
   (`:5174`) que usa Albert también responde. Corpus intacto: 580 chunks.

## 5. Conclusión: qué se aprende de esto

**Un criterio de aceptación con un solo ejemplo se cumple por suerte, no por regla.** AC-04 se
escribió con "¿Qué dice el artículo 107?" y esa elección ocultó el defecto durante toda la Fase 1:
el 107 puntúa 0.94 y el 5 puntúa 0.81. La regla correcta era "cualquier artículo nombrado", y eso
pide al menos dos casos, uno de ellos corto o de contenido poco llamativo. Cuando un test de
aceptación elige un ejemplo, hay que preguntarse qué tiene de especial ese ejemplo.

**Una métrica sirve para una pregunta concreta; usarla para otra más es un error de categoría.** El
score de rerank responde "¿esta pregunta tiene base en el texto recuperado?". Una pregunta que
nombra un artículo ya respondió esa pregunta antes, por una vía determinista. Aplicar el umbral ahí
no era prudencia: era medir la cosa equivocada. El patrón transferible es preguntarse, en cada
guarda, **qué pregunta responde** y si esa pregunta ya está contestada antes de llegar.

**La explicación plausible no es la explicación verdadera.** Con la captura delante, "el corpus se
vació" y "tu navegador apunta a otro backend" eran las hipótesis naturales, y las dos eran falsas.
Lo que las descartó fue barato: mirar los logs con marca de tiempo, leer la fila que el propio
usuario había guardado y medir diez artículos. Antes de escribir la primera línea de arreglo, la
fila de `feedback` valía más que cualquier razonamiento.
