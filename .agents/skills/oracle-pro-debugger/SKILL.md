---
name: oracle-pro-debugger
description: Skill para usar Oracle CLI como segunda opinion con ChatGPT Pro/GPT Pro en depuracion, fallas dificiles, revision de arquitectura y validacion de hipotesis, siempre con dry-run, minima seleccion de archivos y aprobacion explicita antes de enviar contexto externo.
---

# Oracle Pro Debugger

Usa esta skill cuando necesites una segunda opinion externa mediante Oracle CLI para:

- fallas dificiles o intermitentes
- bugs no reproducibles
- debugging profundo despues de inspeccion local
- revision de arquitectura
- validacion cruzada de hipotesis
- analisis de logs previamente sanitizados
- solicitudes explicitas de consultar ChatGPT Pro, GPT Pro u Oracle

No uses esta skill para:

- tareas triviales
- sustituir la inspeccion local inicial
- contexto con secretos no sanitizados
- enviar repos completos
- enviar `.env`, certificados, claves, wallets, cookies, configs privadas o produccion sensible

## Flujo obligatorio

1. Inspecciona localmente el problema, reproduce si es posible y reduce la pregunta.
2. Selecciona el minimo conjunto de archivos necesario con `--file`.
3. Para validar sin tocar `npx` ni Oracle, usa `--print-command` o `ORACLE_NO_EXEC=1`.
4. Ejecuta primero un dry-run con resumen y `files-report`.
5. Revisa el escaneo local de contenido y el reporte de archivos excluidos/incluidos.
6. Pide aprobacion explicita al usuario antes de cualquier consulta real externa.
7. Ejecuta real-run solo con `ORACLE_APPROVED=1` y `--real-run`.
8. Trata la respuesta de Oracle como asesoria, no como verdad.
9. Verifica cualquier recomendacion con tests, lint, typecheck o reproduccion local.

Lee `references/oracle-security-policy.md` antes de cualquier real-run. Usa `references/oracle-usage.md` para ejemplos.

## Wrapper obligatorio

No llames Oracle directamente. Usa siempre:

```bash
.agents/skills/oracle-pro-debugger/scripts/oracle_safe_consult.sh \
  --print-command \
  --dry-run \
  --prompt "Diagnostica esta falla TypeScript y sugiere hipotesis verificables." \
  --file "src/**/*.ts" \
  --file "tsconfig.json"
```

Ejemplo de real-run aprobado:

```bash
ORACLE_APPROVED=1 .agents/skills/oracle-pro-debugger/scripts/oracle_safe_consult.sh \
  --real-run \
  --engine browser \
  --model "gpt-5-pro" \
  --prompt "Revisa estas hipotesis y senala la mas probable con pruebas locales sugeridas." \
  --file "src/**/*.ts" \
  --file "tests/**/*.ts"
```

El wrapper fuerza denies de secretos y dependencias, rechaza globs demasiado amplios, escanea contenido local antes de llamar Oracle, usa dry-run por defecto, imprime el comando sanitizado y requiere aprobacion para cualquier envio externo.
