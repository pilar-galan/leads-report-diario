# GuruSup · Dashboard ejecutivo — guía de trabajo

Fichero fuente único: `generate_dashboard.py` → genera `dashboard_ejecutivo.html`.
Se despliega solo vía GitHub Action `refresh_dashboard.yml` (lee secrets HUBSPOT_TOKEN /
PAID_TRACKER_API_KEY). No se puede regenerar en local sin el token; tras cada cambio de
fuente hay que commitear y disparar el workflow para que regenere el HTML.

## Convenciones de diseño (aplicar SIEMPRE, también en peticiones nuevas)

- **Párrafos de introducción / descripción de sección** (`.sd`, `.xhead p` y equivalentes):
  no deben quedar apelotonados a la izquierda. Repartir el texto usando más ancho
  (`max-width` amplio, ~92ch en secciones, ~1040px en el hero), `text-align:justify`
  con `text-justify:inter-word` y `text-wrap:pretty`, para que queden equilibrados,
  justificados y visualmente repartidos. En móvil (`max-width:640px`) volver a
  `text-align:left` para evitar ríos de espacio.
- Mantener este estilo de párrafo equilibrado/justificado en cualquier bloque de texto
  introductorio o explicativo que se añada en el futuro.

## Restricciones permanentes

- Nunca exponer el identificador de modelo en artefactos del repo, commits ni PRs.
- Nunca escribir secretos en ficheros del repo (es público).
- Trailers de commit:
  `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`
  `Claude-Session: https://claude.ai/code/session_019WmuM4uE7b9LjzLhY7VJCf`
- No crear PRs salvo petición explícita.
