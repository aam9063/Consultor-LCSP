# FX · Base de datos propia para los tests de integración

## 1. Qué se ha construido

Los tests de integración dejan de usar la base de trabajo. Ahora exigen `DATABASE_URL_TEST`, apuntan a
`lcsp_test`, y si la variable falta **se niegan a correr** con un mensaje que explica por qué. Compose
crea la base de tests al inicializar el volumen, y el CI la crea y migra como un paso propio.

## 2. Cómo se ha hecho y por qué así

### Decisión: exigir la variable en vez de tener un valor por defecto
- **Qué se eligió.** `conftest.py` aborta la sesión si `DATABASE_URL_TEST` está vacía, en lugar de
  caer a `DATABASE_URL`.
- **Por qué.** Un fallback silencioso reproduce el problema que este cambio viene a resolver: alguien
  corre los tests sin pensar, sin variable, y se lleva por delante el corpus y 37 lotes de embeddings
  pagados. Un error con mensaje cuesta diez segundos; la pérdida silenciosa, una reingesta completa.

### Decisión: el conftest apunta `DATABASE_URL` a la base de test
- **Qué se eligió.** Tras validar la variable, el conftest escribe `DATABASE_URL` en el entorno antes
  de importar nada de la aplicación.
- **Por qué.** La configuración ya da prioridad a las variables de entorno sobre el fichero local, así
  que basta con eso para que cada módulo que construya un motor más tarde apunte a `lcsp_test`. Se
  evita duplicar una segunda ruta de configuración para tests.

### Decisión: la base de test se crea en la inicialización, no en cada corrida
- **Qué se eligió.** Un script en `docker/postgres-init/` que crea `<nombre>_test` la primera vez que
  arranca el volumen; en CI, un paso que la crea si no existe.
- **Por qué.** Es idempotente donde importa y no añade trabajo a cada corrida. El precio es que hay
  que recrear el volumen si ya existía antes de este cambio, y eso está documentado.

## 3. Errores detectados

### Las suites borraban el corpus de trabajo
- **Cómo se detectó.** La tabla `chunk` apareció con 0 filas justo antes de medir la comparación de
  recuperación: la corrida anterior de `pytest tests/integration` se había llevado la ley ingerida.
- **Causa.** Los tests truncan las tablas del corpus para que la recuperación sea determinista, y lo
  hacían sobre la misma base que usa la aplicación.
- **Qué se hizo.** Base separada, con la variable obligatoria.

### El mensaje de error de pytest puede engañar
- **Cómo se detectó.** Al verificar el caso «sin variable», la salida acaba en `exit=0`.
- **Causa.** Ese 0 es el del `tail` de la tubería, no el de pytest: `pytest.exit(..., returncode=2)`
  sí termina con 2.
- **Qué se hizo.** Se documenta el matiz y se verifica el mensaje, que es lo observable que importa.

## 4. Cómo se iteró hasta una solución válida

1. Síntoma: corpus en 0 tras correr tests.
2. Diagnóstico: `DELETE FROM chunk` sobre la base compartida.
3. Implementación: variable obligatoria, script de inicialización, paso en CI.
4. Verificación funcional: 580 chunks antes → 34 tests pasan → **580 chunks después**; sin la variable,
   la sesión aborta con el mensaje esperado.

## Avisos de la revisión nativa (no bloqueantes, trabajo posterior)

La revisión aprobó el slice con tres avisos que quedan anotados, con mi propia lectura de cada uno:

- `R3-002` (WARNING, script de inicialización): Postgres no tiene `CREATE DATABASE IF NOT EXISTS`, y el
  script corre con `set -e`; si la base ya existiera, el `psql` fallaría y la inicialización del
  contenedor abortaría. Hoy no ocurre porque la inicialización corre una sola vez sobre un volumen
  vacío, pero conviene un guardia explícito.
- `R3-003` (WARNING, paso de CI): el nombre de la base se interpola en un `CREATE DATABASE` con
  f-string. El valor viene de nuestra propia configuración y no de un usuario, así que el riesgo real
  es bajo, pero lo correcto es validar el nombre con una expresión regular antes de interpolar.
- `R3-001` (SUGGESTION, `conftest.py`): el guardia de la variable y la asignación de `DATABASE_URL`
  están en el mismo ámbito de módulo; funcionan, pero se leen mejor separados en dos pasos comentados.

Ninguno abrió corrección: son mejoras de robustez, no defectos del comportamiento entregado.

## 5. Conclusión: qué se aprende de esto

**Un test que destruye datos reales está mal ubicado, no mal escrito.** Truncar tablas es la forma
correcta de aislar una prueba de base de datos; el error es hacerlo sobre la base que alguien usa para
trabajar. Aislar el entorno es parte del diseño de la prueba, no una precaución opcional.

**Los valores por defecto silenciosos son deuda técnica disfrazada de comodidad.** Que el conftest
pudiera caer a `DATABASE_URL` habría hecho que este problema volviera la primera vez que alguien
olvidara exportar la variable. Un fallo ruidoso y explicado es más barato que un éxito que borra.
