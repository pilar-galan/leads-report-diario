# Organización del departamento de Marketing

> **Objetivo.** Definir cómo funciona el departamento de Marketing de GuruSup: organización, KPIs, seguimiento y ownership. Este documento ya no es un borrador de opciones: da **una solución cerrada por cada punto** de la propuesta.
>
> Última actualización: 2026-07-21 · Responsable del doc: **Picu** (Pilar — RevOps / Marketing Automation)

---

## 1. Situación actual

### 1.1 El equipo — un responsable por área

Tras la salida de Jonathan, el equipo queda con **un único owner por área**. Organización plana, sin managers intermedios.

| Persona | Área | Scope / misión |
|---|---|---|
| **Marisa Silva** | **Marca, eventos y comunicación** | Posicionamiento, mensaje e ICP, marca y rebranding (con Diego Lunelli), PR/prensa, eventos, partnerships (Cámaras, Contact Center Hub…) y customer stories. |
| **Marina Mas** | **SEO, web, tráfico y analítica** | SEO por verticales (salud, legal, inmobiliaria, hoteles, dental), contenido/YouTube, enlazado externo, web, y **analítica/atribución** (GA4, dashboards, instrumentación). Apoyo externo puntual: José Gilarte (SEO/CRO). |
| **Alejandro Melero** | **Paid (Google + Social Ads)** | Toda la adquisición de pago: Google Ads, Meta, LinkedIn, Bing y demás; creatividades con IA, análisis de campañas y optimización de coste. |
| **Picu (Pilar)** | **CRM, automatización y sistema de datos** | HubSpot, automatizaciones, **calidad del dato** y montar el **sistema de reporting/tracking**. Owner del lead scoring (heredado). |
| **Víctor Molla** | Sponsor / dirección | Visión global del squad; sparring mensual. Cada vez más absorbido por fundraising y Brain. |

**Misión de Picu (declarada):** que **en septiembre exista un sistema que traccione** y permita tomar decisiones sobre los datos, que aporte valor y que el proceso funcione. No tiene que estar al 100% ni ser perfecto — **tiene que funcionar**.

### 1.2 Herramientas y reporting
- **HubSpot** como CRM y centro de automatización (owner: Picu).
- **Reporting** en este repo: `dashboard_diario`, `dashboard_ejecutivo`, `informe_leads_semanal`, GA4.
- Paid: Google/Meta/LinkedIn/Bing, Capterra/G2; creatividades IA (HeyGen, Veo3, Creatify, ElevenLabs). Web/landings en Framer/Next.js; heatmaps con Clarity; A/B con Midas.

### 1.3 Funnel y scoring (lenguaje común)
- **freemiums** (signups app) → fuera de nurturing de demanda · **Lead** (sin info/intención) · **SQL Consultoría/Demo** (quiere reunión con ventas).
- Ciclo de vida: spam · disqualified · bad fit · closed lost · cliente (no se borran, se categorizan; spam/disqualified se envían como señal a las plataformas de ads).
- **Lead scoring**: modelo **fit score + hit score**, umbral ~50 puntos para MQL (formalizado 20-jul). Ownership: Picu.

---

## 2. La mejor solución a cada punto

### ✅ 2.1 Frecuencia de seguimiento

**Solución:** cadencia en cuatro capas, con el KPI review incrustado en el ritmo semanal y mensual.

| Ritmo | Ritual | Duración | Para qué |
|---|---|---|---|
| **Diario** | Async por canal en Discord (`@paid`, `@seo`, `@marketing`) + stand-up 9:40 | — | Desbloqueos rápidos; nada que alargue reuniones |
| **Semanal** | **Syncro Marketing Squad** con agenda fija | **60 min, hard stop** | Revisar KPIs vs objetivo + decisiones + reparto |
| **Mensual** | **Marketing Review** + sparring con Víctor | 60–90 min | KPIs del mes vs objetivo, aprendizajes, ajuste de prioridades |
| **Trimestral** | Planificación de roadmap / objetivos | 2 h | Fijar prioridades y objetivos del trimestre |

Regla de oro: **el reporting se lee antes** del Syncro (Picu comparte highlights), para no quemar la reunión en revisar números.

### ✅ 2.2 KPIs del equipo

**North Star del departamento:** **oportunidades cualificadas generadas por Marketing en el pipeline.** El foco es **mejorar y optimizar las tasas de conversión del funnel inbound** (lead → MQL → SQL → oportunidad). El cierre del pipeline es responsabilidad de **Ventas**: Marketing aprende de él y saca feedback (entender por qué no convierten) pero no lo gestiona — esto es estructura de Marketing.

Cada área tiene **1 North Star propio + 2-3 KPIs primarios + 1 métrica de calidad/guardrail**, todos con objetivo mensual. Ver detalle por persona en la **sección 3**.

### ✅ 2.3 Reuniones

**Solución:** consolidar en las cuatro capas de 2.1. No se crea ninguna reunión nueva sin quitar otra. Cada Syncro **cierra con compromisos (owner + plazo)**. Los temas operativos por canal (WhatsApp, Instantly, HubSpot, workflows) van a hilos async, no a la reunión.

### ✅ 2.4 Prioridades del trimestre (hasta septiembre)

1. **Sistema de datos que funcione (Picu)** — objetivo ancla del trimestre: en septiembre, tracking y reporting fiables para decidir con datos.
2. **Marca** — cerrar reposicionamiento (tecnología/autonomía, tono intermedio sin alarma) y rebranding; rollout público + nota de prensa en **septiembre**.
3. **Adquisición cualificada** — reactivar paid que funcionó en junio; explotar **Capterra/G2**; foco en verticales de menor presión de paid.
4. **Conversión** — arreglar nurturing (correos 2 y 3), formulario "pedir demo" trackeado, mejorar activación de freemiums.

---

## 3. KPIs por persona (según perfil, scope y misión)

### 🎨 Marisa — Marca, eventos y comunicación
- **North Star:** oportunidades cualificadas originadas por marca (eventos, partnerships, PR y contenido de marca).
- **Primarios:**
  - Leads/demos atribuidos a eventos y partnerships activos (Cámaras, Contact Center Hub…).
  - Publicaciones/menciones de prensa y colaboraciones vivas al mes.
  - Customer stories publicadas (objetivo trimestral).
- **Guardrail/calidad:** hitos del rebranding cumplidos a tiempo (referencias → dirección → logo/tipografía → rollout sept.) y consistencia del claim aprobado en todas las piezas.
- *Apoyo:* alcance/impresiones e interacción en LinkedIn (awareness, top of funnel).

### 🔎 Marina — SEO, web, tráfico y analítica
- **North Star:** leads orgánicos cualificados (MQL) desde SEO/web.
- **Primarios:**
  - Rankings **top 3 / top 10** en las verticales prioritarias.
  - Tráfico orgánico y su tendencia mensual.
  - Autoridad de dominio (referencia 25→32; objetivo creciente).
- **Guardrail/calidad (analítica):** **% de sesiones/leads con origen/canal correctamente atribuido** (bajar la sobreatribución a "directo") y freemium instrumentado en GA4.
- *Coordinación:* avisar de picos de SEO forzado y no pisar cambios de web.

### 📈 Alejandro Melero — Paid (Google + Social Ads)
- **North Star:** oportunidades cualificadas desde paid (MQL con fit+hit ≥50).
- **Primarios:**
  - **CPL y CP-MQL por canal** (Google, Meta, LinkedIn).
  - **Coste por oportunidad / ROAS** cruzando campañas con CRM.
  - **% de leads cualificados** vs volumen de "porra".
- **Guardrail/calidad:** tasa de disqualified/spam por canal (se devuelve como señal a las plataformas) y gasto vs presupuesto.
- *Apoyo:* CTR/CPM/CPC como métricas de diagnóstico, no de objetivo.

### ⚙️ Picu — CRM, automatización y sistema de datos
- **North Star:** **en septiembre, un sistema de tracking/reporting operativo y fiable** — que el equipo tome decisiones semanales sobre sus datos (que funcione, no que sea perfecto).
- **Primarios:**
  - **Evolución del funnel:** tasa de conversión en cada salto — **lead → MQL → SQL → oportunidad** — visible en un único cuadro de mando.
  - **Oportunidades generadas en pipeline:** contactos con una nueva oportunidad en etapa (p. ej. *discovery*) ya precualificada por Ventas y de origen inbound.
  - **Atribución por canal de inbound:** orgánico, directo, pago (Google Ads / social ads), eventos, webinars, referencias, referencias de IA, newsletters externas, medios, chat web y *otros* (tráfico web sin identificar por no aprobar cookies).
- **Automatización:** nurturing operativo y medido (apertura/CTR; arreglar correos 2 y 3) y lead scoring fit+hit vivo y mantenido.
- **Health del proyecto (milestone septiembre):** hitos cumplidos — formularios nativos de HubSpot, `forms.gurusup.com`, freemium instrumentado, dashboard único en marcha.

---

## 4. Acciones

### 4.1 Definir rituales del equipo
- [ ] Aplicar la cadencia de 2.1 (Syncro 60 min con hard stop + Marketing Review mensual). — *Owner: Marisa + Picu*
- [ ] Reporting compartido y leído antes del Syncro. — *Owner: Picu*

### 4.2 Establecer KPIs
- [ ] Adoptar el cuadro de la sección 3 y fijar el **objetivo mensual** de cada KPI en el próximo Marketing Review. — *Owner: cada responsable de área*
- [ ] Reflejar los KPIs en `dashboard_ejecutivo` como panel de seguimiento. — *Owner: Picu*

### 4.3 Crear roadmap de Marketing
- [ ] Backlog único priorizado con owner y objetivo, alineado con las prioridades de 2.4. — *Owner: Marisa, con cada área*
- [ ] Revisión mensual del roadmap en el Marketing Review. — *Owner: equipo*

### 4.4 Definir ownership de cada área
- [ ] Confirmar la matriz de la sección 1.1 (un owner por área). — *Owner: equipo + Víctor*
- [ ] Traspasar formalmente a Picu lo que llevaba Jonathan del CRM/scoring; el paid completo pasa a Melero. — *Owner: Picu + Melero*

---

## 5. Matriz de ownership

| Área | Owner | Consultado |
|---|---|---|
| Marca, mensaje, ICP, rebranding | Marisa | Víctor, equipo, producto |
| PR, eventos, partnerships, customer stories | Marisa | Ventas |
| SEO, contenido web/YouTube | Marina | Marisa (contenido) |
| Analítica y atribución (GA4, tráfico) | Marina | Picu (CRM/atribución) |
| Paid (Google + Social Ads) | Alejandro Melero | Picu (scoring/atribución) |
| CRM HubSpot, automatización, calidad del dato | Picu | Todo el equipo |
| Sistema de reporting / tracking (hito septiembre) | Picu | Marina (GA4), Víctor |
| Dirección / prioridades globales | Víctor | Squad |

---

*Fuentes internas (GuruSup Brain): serie Syncro Marketing Squad (2026-06-15 → 2026-07-20), decisión de sparrings mutuos (2026-06-24), Funnel de leads, modelo fit/hit score y reposicionamiento de marca (2026-07-20), fichas de equipo (Marisa Silva, Marina Mas), concepto SEO, sesión de analítica (2026-06-17) y kickoff de paid de Alejandro Melero (2026-07-01).*
