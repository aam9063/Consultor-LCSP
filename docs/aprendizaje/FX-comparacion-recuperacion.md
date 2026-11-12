# FX · Comparar la recuperación por posición, no solo por recuerdo

## 1. Qué se ha construido

Un modo de evaluación que mide **dónde** aparece el artículo correcto, no solo si aparece: `hit@1`
(¿es el primero?) y `MRR` (media del inverso de la posición), calculados sobre la recuperación sola,
sin llamar al modelo de generación. Escribe ambos rankings por pregunta para que el análisis posterior
no cueste cuota.

## 2. Cómo se ha hecho y por qué así

### Decisión: medir la recuperación como un paso propio
- **Qué se eligió.** Un comando que corre únicamente `hybrid_search` y la búsqueda por embeddings, sin
  generar respuestas.
- **Por qué.** La pregunta era sobre el ranking, no sobre la redacción. Aislar el paso elimina dos
  fuentes de ruido: el modelo de generación y la abstención. Y abarata el experimento de 25
  generaciones a 75 llamadas de embeddings/rerank.

### Decisión: `hit@1` y MRR en vez de más `recall@k`
- **Qué se eligió.** Dos métricas de posición, junto al `recall@5` que ya existía.
- **Por qué.** `recall@5` responde «¿está en los cinco primeros?», y con 580 chunks y `top_k=6` casi
  todo está. Es una métrica que **satura**: no distingue un sistema que acierta por casualidad de uno
  que acierta con precisión. La posición sí: al usuario le cambia que la cita correcta sea la primera
  o la cuarta, y al prompt de generación también.

## 3. Errores detectados

### Mi conclusión anterior sobre el híbrido era falsa, y la causó la métrica
- **Cómo se detectó.** Al revisar los datos disponibles para este experimento: el JSON de evaluación
  guardaba el ranking híbrido pero no el de solo embeddings, así que solo se podía afirmar el empate
  en `recall@5`. Ese empate se había convertido en «el híbrido no aporta nada medible».
- **Causa.** Confundir «esta métrica no distingue» con «no hay diferencia». `recall@5` era la vara
  equivocada: los dos modos aciertan el artículo, pero no lo colocan igual.
- **Qué se hizo.** Medir la posición. El híbrido gana con claridad: `hit@1` 95% frente a 80%, MRR
  0,967 frente a 0,892. La conclusión anterior queda corregida en el README y en el feature document,
  no borrada.

### El corpus desapareció antes de poder medirlo
- **Cómo se detectó.** La tabla `chunk` tenía 0 filas justo antes de la comparación.
- **Causa.** Las suites de integración hacen `DELETE FROM chunk` y comparten base con el entorno de
  trabajo; cada `pytest tests/integration` se lleva por delante la ley ingerida (y con ella 37 lotes
  de embeddings ya pagados).
- **Qué se hizo.** Reingerir antes de medir. **No se corrigió todavía**: los tests merecen su propia
  base (`lcsp_test`) para no volver a destruir el corpus de trabajo.

### El reintento de red se estrenó solo
- **Cómo se detectó.** Durante la reingesta aparecieron cuatro `429` seguidos del proveedor.
- **Qué pasó.** El backoff del fix anterior los absorbió y la ingesta terminó con 580 chunks. Primera
  evidencia en producción de que el cambio servía.

## 4. Cómo se iteró hasta una solución válida

1. `recall@5` empatado en la evaluación completa → sospecha de métrica saturada, no de sistema
   sobredimensionado.
2. Comparación de recuperación sin generación → diferencia clara en posición.
3. Métricas nuevas con 18 pruebas (posiciones 1 y 3, ausencia, ranking vacío, dos artículos
   esperados, empates y orden de los peores casos) y `mypy --strict` limpio.
4. Evidencia persistida en `evals/results/2026-11-12-retrieval.json` y conclusiones corregidas en la
   documentación pública del proyecto.

## 5. Conclusión: qué se aprende de esto

**Una métrica saturada no es una buena noticia: es una métrica que dejó de informar.** Cuando un
sistema acierta el 100% en una métrica de cobertura, hay que sospechar del instrumento antes que
celebrar el resultado. En este caso el `recall@5` empataba porque los dos modos encontraban el
artículo; lo que no veía era que uno lo ponía primero y el otro cuarto. Elegir la métrica **es** la
parte más importante del experimento.

**Corregir una conclusión cuesta más que acertarla, y hay que hacerlo igual.** El README decía que el
híbrido no aportaba nada. Hoy dice lo contrario, con la tabla delante y una frase que explica por qué
la conclusión anterior estaba equivocada. Un documento que se corrige a sí mismo vale más que uno que
nunca se equivoca: el segundo, o miente, o no se está midiendo.

**Un test que borra datos productivos es un test mal ubicado.** Las suites de integración deben tener
su propia base. Compartirla con el entorno que se usa para medir convierte cada ejecución de tests en
una pérdida de datos reales y de cuota pagada.
