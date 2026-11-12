# Documentación de aprendizaje

Un documento por implementación cerrada, según la sección 11 de `AGENTS.md`.

## Convención de nombres

`docs/aprendizaje/<ID>-<slug>.md`, con el mismo `ID` que el feature document:

- `CL-01-esqueleto-y-compose.md`
- `CL-08-evaluacion-y-set-anotado.md`
- correcciones: `FX-<slug>.md` cuando no pertenecen a una tarea concreta.

## Plantilla

```markdown
# <ID> · <Título de la implementación>

## 1. Qué se ha construido

## 2. Cómo se ha hecho y por qué así
### Decisión: <nombre>
- **Qué se eligió.**
- **Por qué.** (argumento; la alternativa descartada y su motivo)

## 3. Errores detectados
### <Síntoma>
- **Cómo se detectó.** (la evidencia concreta: el test que falló, el número raro)
- **Causa.**
- **Qué se hizo.**

## 4. Cómo se iteró hasta una solución válida
Secuencia RED → diagnóstico → decisión → GREEN, con números.

## 5. Conclusión: qué se aprende de esto
El principio transferible, en dos o tres párrafos.
```

## Reglas de honestidad

- Nada de métricas inventadas, redondeadas a favor ni "aprox.". Si no se midió, se dice.
- Los errores del propio agente se documentan igual que los del código: son la parte más útil.
- Si una decisión la tomó Albert, se registra como suya y con su motivo.
