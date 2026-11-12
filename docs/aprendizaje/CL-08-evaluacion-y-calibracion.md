# CL-08 · Evaluación, calibración del umbral y la verdad sobre el híbrido

## 1. Qué se ha construido

La medición del sistema con datos reales, de punta a punta:

- **`evals/preguntas.yaml`** con 25 entradas anotadas (pregunta, artículos esperados,
  respuesta de referencia breve, si debería abstenerse): 20 con base en la ley y 5 fuera
  de ella (IVA, derecho laboral…). Los ejemplos de partida del BRIEF se confirmaron
  contra el texto del BOE al anotar, como el propio BRIEF pide.
- **`uv run python -m evals.run`** contra la API real (nunca en CI; solo
  `workflow_dispatch` con `NAN_API_KEY`), que genera `evals/results/<fecha>.md` con
  recall@5, % de respuestas con todas las citas válidas, % de abstención correcta, los
  peores casos y la comparación híbrido vs. solo embeddings, con los JSON de scores como
  evidencia versionada.
- **Tres corridas documentadas** (corpus real: 580 chunks, `qwen3-embedding` + `rerank` +
  `deepseek-v4-flash`), descritas en la sección 4.

Resultado final (AC-10, cumplido): recall@5 **97.5%**, citas válidas **100%**,
abstención correcta **5/5**. Objetivos del BRIEF: ≥ 85%, ≥ 95% y ≥ 4/5.

## 2. Cómo se ha hecho y por qué así

### Decisión: endurecer el set original (decisión de Albert)
- **Qué se eligió.** El set de 25 original (títulos casi literales: "¿Qué penalidades se
  imponen…?", "¿Cuándo se exige la clasificación…?") se reemplazó por uno endurecido con
  preguntas de escenario: "El contratista lleva tres semanas de retraso injustificado…",
  "Nos han adjudicado un contrato y nos piden aportar la garantía definitiva…".
- **Por qué.** El set original saturaba el sistema (recall@5 = 100%) porque las preguntas
  usaban el mismo vocabulario que la ley: medían el mejor caso, no el uso real. La
  alternativa (conservar el 100% y reportarlo) habría sido medir el orgullo, no el
  producto.

### Decisión: calibrar el umbral de abstención con la distribución real
- **Qué se eligió.** `rerank_threshold` = 0.85, elegido mirando las puntuaciones reales
  que dejó la corrida: con base legal, mínimo ~0.958; fuera de la ley, máximo ~0.757. Dos
  corridas distintas dieron 0.9579/0.7528 y 0.9577/0.7573, así que el rerank no es determinista
  al milésimo: lo que hace seguro el 0.85 es el hueco de ~0.20 entre los dos grupos, no un
  número exacto. El
  umbral se apoya en el hueco entre ambos mundos.
- **Por qué.** El 0.35 inicial era un número inventado (constante razonable en el
  momento), y fallaba por los dos lados: abstenía indebidamente en 5 de las 20 preguntas
  válidas del set endurecido y dejaba fuera preguntas sin base. Con la distribución en la
  mano, el umbral deja de ser una opinión y pasa a ser una lectura del hueco entre
  distribuciones.

### Decisión: medir la recuperación aparte de las respuestas
- **Qué se eligió.** El recall@5 se calcula sobre los chunks **recuperados** del sistema,
  no sobre los chunks que cita la respuesta generada.
- **Por qué.** Es el arreglo de un artefacto de medición (sección 3): una pregunta que se
  abstiene no trae chunks de respuesta, y contaba como "no recuperó nada" aunque el
  recuperador hubiera hecho bien su trabajo.

### Decisión: `evals/` entra al alcance de lint y tipos
- **Qué se eligió.** El CI lintea y tipa el runner de evaluación (commit `2bdbb95`, y la
  regla copiada a AGENTS.md §9: `uv run ruff check ../evals`).
- **Por qué.** El caso de la sección 3: un string mal escapado rompió el runner y ningún
  gate lo vio porque `evals/` estaba fuera de alcance.

## 3. Errores detectados

### La primera corrida: 100% de recall y 90% de citas válidas
- **Cómo se detectó.** El informe marcó 90% y señalaba citas fuera del contexto
  recuperado; al leer los casos, lo que la evaluación mostraba era dos respuestas
  **sin ninguna cita respaldada**, enviadas igual con su aviso.
- **Qué se hizo.** Ese hallazgo pertenece a CL-05 y su corrección (abstener cuando no
  sobrevive ninguna cita, decisión de Albert, commit `71c36eb`) se cuenta en su documento.
  Acá importa la lección de medición: el % de citas válidas medía lo que el sistema
  entregaba, y entregaba cosa que no debía entregar.

### La segunda corrida: 75% de recall, un artefacto de medición
- **Cómo se detectó.** Con el set endurecido y el umbral sin calibrar: híbrido 75% contra
  97.5% de solo embeddings (-22.50 puntos), con cinco preguntas en 0.00 que reportaban
  "recuperados: ninguno".
- **Causa.** El recall se computaba sobre los chunks de la respuesta; al abstenerse, la
  lista queda vacía. Las cinco preguntas de 0.00 eran abstenciones del umbral mal
  calibrado, no fallos del recuperador.
- **Qué se hizo.** Corrección en `4118100` (medir recuperación aparte) y calibración del
  umbral a 0.85. La corrida 2 se conserva como evidencia de cómo una métrica mal definida
  invierte el orden de dos técnicas.

### El umbral 0.35 era un número inventado
- **Cómo se detectó.** En la corrida 2: abstenciones indebidas en 5 de las 20 preguntas
  con base; y según lo registrado en el feature document durante la calibración, dejaba
  pasar 4 de las 5 preguntas fuera de la ley sin abstenerse.
- **Qué se hizo.** Calibración con la distribución real (detalle en la sección 2). Sin la
  lista de `best_score` por pregunta, el umbral habría quedado como "constante mágica que
  funciona".

### Un string mal escapado llegó al worktree sin que ningún gate lo viera
- **Cómo se detectó.** El runner de evaluación roto por un literal mal escapado.
- **Causa.** `evals/` estaba fuera del alcance de `ruff` y `mypy`; los gates solo miraban
  `backend/`.
- **Qué se hizo.** `2bdbb95` añade `evals/` al CI y la regla quedó en AGENTS.md §9.

### Los casos no perfectos de la corrida final (honestidad de informe)
- **P-08** (subcontratación, esperaba 215 y 216): el 216 no entró en el top-5 y el
  **modelo** se abstuvo con `best_score=0.9756`, por encima del umbral. Es abstención del
  LLM, no del umbral; es la única "abstención indebida" del informe final.
- El top-5 de P-08 trae el 215 dos veces: el artículo supera los 1.500 tokens y se parte
  en dos chunks.

## 4. Cómo se iteró hasta una solución válida

Tres corridas sobre el mismo corpus, cada una cambiando una cosa:

| Corrida | Set | Umbral | Recall@5 | Citas válidas | Abstención |
| --- | --- | --- | --- | --- | --- |
| 1 | original (títulos casi literales) | 0.35 | 100% | 90% | 5/5 |
| 2 | endurecido | 0.35 | 75% (artefacto) | 100% | 5/5 |
| 3 | endurecido | 0.85 calibrado | **97.5%** | **100%** | **5/5** |

Entre corridas hubo dos correcciones con commits: la de citas (CL-05, `71c36eb`) y la de
medición (`4118100`, que además saca el cálculo del recall de la respuesta y añade el informe
de puntuaciones). La comparación híbrido vs. solo embeddings de la corrida 3 es el resultado
más incómodo y más valioso: **97.5% en ambos casos, diferencia +0.00**. Con este corpus,
RRF + rerank no aportan nada medible. La interpretación honesta (anotada como propuesta,
no como deuda oculta): 580 chunks de artículo completo son léxicamente ricos; `top_k=6`
es generoso; la búsqueda exacta de pgvector ya resuelve; y con un corpus chico los
métodos convergen. Para demostrar valor del híbrido haría falta un corpus mayor, chunks
más finos o preguntas donde léxico y semántica discrepen.

## 5. Conclusión: qué se aprende de esto

Una evaluación vale lo que vale su set. El set fácil y literal dio 100% y no dijo nada;
el set endurecido con preguntas de escenario dio 75% (falso) y después 97.5% (verdadero),
y en el camino destapó dos defectos reales. Si tu evaluación satura, estás midiendo la
similitud de vocabulario, no la calidad. Y una métrica mal definida (recall sobre los
chunks de la respuesta, vacíos al abstener) no solo es imprecisa: puede invertir el orden
de dos técnicas y hacerte creer que tu ingeniería agravó el sistema.

El umbral de abstención es una constante que debe salir de datos: imprimir la distribución
de puntuaciones por pregunta (el informe lo hace) y el hueco entre "con base" y "sin
base" te dice dónde poner la frontera. Un número inventado falla por los dos lados a la
vez, y cada lado falla distinto (abstenerse de más es incómodo; abstenerse de menos es
grave). La última lección es de honestidad: 97.5% con híbrido idéntico a solo embeddings
es un resultado que invita a disimular. Informarlo tal cual, con la hipótesis de por qué
no aporta y qué experimento lo demostraría, es lo único que permite decidir bien la
Fase 2.
