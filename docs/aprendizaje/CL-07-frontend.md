# CL-07 · Frontend: consulta con chips, revisor e historial

## 1. Qué se ha construido

La cara visible del producto, en React 19 + TypeScript estricto + Tailwind, fiel a los
mockups de `frontend/docs/mock/`:

- **Vista de consulta**: caja de pregunta; respuesta con las citas como chips; al pulsar
  un chip, un panel lateral muestra el texto del artículo (vía `GET /articulos/{numero}`)
  con su enlace al BOE; lista plegable de los artículos recuperados con su puntuación de
  rerank; estados de abstención y de aviso; historial de la sesión en memoria del
  navegador (sin persistir, como dice el BRIEF).
- **Vista de revisor**: área de texto para la cláusula y tarjetas de avisos con su tipo,
  explicación, cita literal de la cláusula y artículo citado; también los avisos
  descartados.
- **Tests**: 9 de Vitest + Testing Library y 2 de Playwright, con la red stubbeada
  (`fetch` en Vitest, `page.route` en Playwright): sin backend ni clave de API.
- **CI**: job de e2e con Playwright, solo en PR hacia `dev`/`main`, subiendo el informe
  como artifact si falla.

Verificación del orquestador con capturas reales contra la API stubbeada: chip del
art. 107 abre el panel con el texto y el enlace; tarjetas del revisor con
`posible_incumplimiento` y cita literal entrecomillada; gates completos en verde.

## 2. Cómo se ha hecho y por qué así

### Decisión: tests con la red stubbeada, no contra un backend de desarrollo
- **Qué se eligió.** Vitest reemplaza `fetch` y Playwright intercepta con `page.route`;
  ningún test necesita la API ni consume cuota.
- **Por qué.** Hace los tests rápidos, deterministas y ejecutables en CI sin secretos
  (el CI no usa `NAN_API_KEY`). La alternativa (un backend real en el test) habría
  necesitado ingesta, clave y estabilidad de red para probar, en realidad, componentes.

### Decisión: los mockups como fuente de diseño, fuera de la revisión de código
- **Qué se eligió.** Los dos HTML de `frontend/docs/mock/` (creados por Albert) entran al
  repo como fuente de diseño (`b12de34`) pero están excluidos de la candidata de revisión
  por decisión de Albert.
- **Por qué.** Son artefactos de diseño, no código de producción: revisarlos con lentes de
  riesgo de código no aporta nada y consume presupuesto de contexto del revisor.

### Decisión: puerto del e2e por entorno y sin reutilizar servidor
- **Qué se eligió.** `reuseExistingServer: false` y el puerto configurable por
  `PLAYWRIGHT_PORT`.
- **Por qué.** El hallazgo de la sección 3: un puerto fijo en una máquina con otros
  proyectos puede dar pie a que Playwright testee otra aplicación. Sin
  reutilización, el Playwright siempre levanta su propio servidor del build nuevo.

### Decisión: `.gitattributes` con `eol=lf`
- **Qué se eligió.** Todo el repo en LF, normalizado en el commit `4341dab`.
- **Por qué.** El fallo de la sección 3: `core.autocrlf=true` de Windows contra el
  prettier del repo. Arreglarlo en configuración del repo (no en cada clon) hace que
  ningún clon nuevo reproduzca el problema.

## 3. Errores detectados

### `format:check` fallaba en ficheros que nadie había tocado
- **Cómo se detectó.** Ejecutar `pnpm format:check` en el clon Windows: 9 ficheros
  fallidos, ninguno modificado por el slice.
- **Causa.** `core.autocrlf=true` del clon de Windows: Git entrega CRLF en el working tree,
  prettier exige LF, y el fichero aparece "sucio" sin haberse tocado.
- **Qué se hizo.** `.gitattributes` con `* text=auto eol=lf`; `format:check` limpio y
  estable en cualquier clon futuro.

### Playwright pudo estar testeando la aplicación equivocada, en silencio
- **Cómo se detectó.** La revisión nativa (`R3-003-ci-port-reuse-flakiness`): el puerto
  fijo 5273 puede colisionar con otro proyecto local; con `reuseExistingServer` activo,
  el test habría corrido contra lo que ya escuchaba en ese puerto.
- **Causa.** Reutilizar un servidor "por comodidad" convierte un puerto compartido en un
  test que pasa contra software equivocado: el peor tipo de falso verde.
- **Qué se hizo.** Puerto por `PLAYWRIGHT_PORT` (verificado con el puerto por defecto y
  con 5301) y `reuseExistingServer: false`, en `a26d52c`.

### Panel con artículo rancio al cambiar de consulta
- **Cómo se detectó.** `R3-002-stale-panel-history-switch` (WARNING, de la primera
  revisión): al cambiar de entrada del historial, el panel lateral podía mostrar el
  artículo de la consulta anterior.
- **Causa.** La selección del panel no estaba atada a la consulta mostrada: quedaba del
  render anterior.
- **Qué se hizo.** Corregido en `a26d52c` con test propio (la selección pertenece a la
  consulta mostrada y vuelve al placeholder al cambiar de respuesta) y verificado por una
  segunda revisión nativa (`review-f05afb069150ce72`, tier `medium`, 4 ficheros, 77
  líneas, `approved`).

### El hallazgo "crítico" resultó falso, y lo refutó el refutador
- **Cómo se detectó.** La revisión nativa del slice (lineage
  `review-fc0433fbf0ffb962`, 19 ficheros, 1.732 líneas, tres lentes) produjo el hallazgo
  crítico `R3-001-ui-crash-undefined-filter` en `RevisorView.tsx`.
- **Causa del desmentido.** El paso de refutación lo desmintió: el camino de ejecución no
  podía llegar allí con el estado que activaría el crash.
- **Qué se hizo.** Nada: no se cambió código por un hallazgo refutado. El veredicto final
  fue `approved`. Queda la lección: una revisión alucina un crash tan fácil como un
  revisor humano; el paso de refutación es lo que lo filtra.
- `R3-004-regex-silent-cast` (`answerText.ts`) quedó solo como sugerencia menor.

## 4. Cómo se iteró hasta una solución válida

RED del worker observado: imports no resueltos de `ConsultaView`/`RevisorView` y
`Unable to find a label` (Testing Library sin la etiqueta del formulario). GREEN: 9
unitarios y 2 e2e. La primera revisión nativa terminó `approved` con authority quemada
tras el ciclo revisores → refutador. Los avisos no bloqueantes se convirtieron en un
segundo slice pequeño (4 ficheros, 77 líneas) con su propia revisión `approved`: los
warnings y suggestions no reabren la revisión original, se trabajan como unidad nueva.

La verificación añadió evidencia que ningún test da: capturas reales de ambas vistas
contra la API stubbeada, comparadas contra los mockups (paleta y estructura), y el chequeo
de que el job e2e nuevo corría bajo `actionlint` sin errores.

## 5. Conclusión: qué se aprende de esto

El frontend de un producto auditable lleva la trazabilidad a la UI: que el chip apunte a
un artículo real, que el panel no muestre basura de la consulta anterior, que la lista de
recuperados sea visible y plegable para entender qué encontró el sistema. Ninguno de esos
detalles es "pintura": ahí vive la mitad de la promesa del producto.

El otro aprendizaje es sobre el silencio de los falsos verdes. Un test de e2e que corre
contra la aplicación equivocada pasa igual de verde que uno correcto; un `format:check`
que "falla solo" por CRLF borra poco a poco la confianza en el chequeo. Ambos se
arreglan quitando ambigüedad del entorno (puerto explícito, sin reutilización, el
fin de línea declarado en el repo): el CI debe poder reproducirse de la misma manera en la
máquina de cualquiera, y la forma de lograrlo es que el entorno viva declarado en el
repositorio, no en la configuración local de cada clon.
