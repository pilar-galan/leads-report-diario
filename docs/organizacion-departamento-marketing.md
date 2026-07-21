# Organización del departamento de Marketing

> **Objetivo del documento.** Definir cómo queremos que funcione el departamento de Marketing de GuruSup: cómo nos organizamos, qué medimos, cómo hacemos seguimiento y quién es dueño de cada área. Es un documento de trabajo para cerrar en el Syncro Marketing Squad y con Víctor en el sparring mensual.
>
> Estado: **propuesta para decidir**. Las secciones "Decisiones a tomar" recogen recomendaciones; el equipo confirma o ajusta.
>
> Última actualización: 2026-07-21 · Responsable del doc: Pilar (RevOps / Marketing Automation)

---

## 1. Situación actual

### 1.1 El equipo (Marketing Squad, ~5 personas)

Equipo verticalizado por función, organización plana y sin managers intermedios. Composición actual:

| Persona | Función | Foco / ownership de hecho |
|---|---|---|
| **Marisa Silva** (Da Silva Rivero) | Marketing / posicionamiento y contenido | ICP y mensaje, marca y rebranding (con Diego Lunelli, freelance), customer stories/testimonios, prensa/PR, eventos y brand awareness. Coordina de facto el squad. |
| **Jonathan Guillén** | Paid / performance | Campañas paid (LinkedIn, Meta, Google Ads, Capterra/G2), modelo de lead scoring, dashboards y atribución (con Pilar). |
| **Alejandro Melero** | Paid / performance (incorporado 01-jul-2026) | Creatividades con IA, scraper de competidores, análisis de campañas y dashboards. |
| **Marina Mas** | SEO / contenido | SEO por verticales (salud, legal, inmobiliaria, hoteles, dental), enlazado externo, autoridad de dominio, contenido de YouTube, web. |
| **Pilar** | RevOps / Marketing Automation | HubSpot, taxonomía del funnel y ciclo de vida de leads, reporting/highlights, formularios y autenticación de dominio. |
| **Víctor Molla** | Sponsor / dirección | Visión global del squad; cada vez más absorbido por fundraising y por GuruSup Brain. |

*Nota:* José Frías dejó el equipo de SEO (Marina queda sola en esa función). Nacho González se integró al equipo en la bienvenida del 10-jul.

### 1.2 Rituales actuales

- **Syncro Marketing Squad** — sesión semanal (~90–120 min) donde todo el equipo revisa reporting/atribución, pricing, contenido y SEO/web. Registrada como serie recurrente.
- **Sparrings mutuos semanales** entre miembros del equipo (rotando quién "cuestiona" y quién expone su misión). Decisión del 24-jun.
- **Sparring mensual con Víctor** (visión global del squad), en lugar de one-on-ones semanales que se cancelaban con frecuencia.
- **Stand-up de empresa** diario (9:40) y **retro semanal de todo el equipo** (formato problems/tries/keeps, facilita Ana) — la retro global excluye explícitamente temas de marketing aislados, que van a los rituales propios.

### 1.3 Herramientas y reporting

- **HubSpot** como CRM/centro de marketing automation (ownership asumido por Pilar tras ser "tierra de nadie").
- **Repositorio de reporting** (este repo): `dashboard_diario`, `dashboard_ejecutivo`, `informe_leads_semanal`, dashboards de leads/pipeline por canal, GA4.
- Paid: Meta/Google/LinkedIn Ads, Capterra/G2; creatividades con IA (HeyGen, Veo3, Creatify, ElevenLabs). Web/landings en Framer/Next.js; heatmaps con Clarity; A/B con Midas.

### 1.4 Funnel y datos (referencia común)

Taxonomía fijada por Pilar al depurar el CRM (jun 2026):

- **freemiums** (signups de la app) → no pasan a Lead, se excluyen de nurturing de demanda.
- **SQL Consultoría/Demo** → contactos que quieren reunión con ventas.
- **Lead** → contacto en CRM sin info ni intención activa.
- **Ciclo de vida del lead**: spam · disqualified · bad fit · closed lost · cliente (no se borran leads, se categorizan; spam/disqualified se envían como señal a las plataformas de ads).
- **Lead scoring**: modelo **fit score + hit score**, umbral ~50 puntos para MQL (formalizado 20-jul).

---

## 2. Diagnóstico por tema

### Necesidades del equipo
- Dirección de marca estable: el mensaje oscila entre "tecnología/autonomía" y "trato humano" (debate del 20-jul). Necesitamos un posicionamiento cerrado y un tono acordado.
- Mejor material visual de producto (dashboards, mockups, tablas) para web y presentaciones — reclamado por Pilar y Jonathan.
- Coordinación paid clara entre Jonathan y Alejandro para evitar solapamientos.

### Seguimiento y cadencia
- El Syncro semanal funciona pero tiende a alargarse (sesiones de 90–120 min). Falta foco y hard stops.
- El seguimiento de KPIs no está formalizado como ritual: se revisa reporting, pero sin objetivos fijados contra los que medir.

### Bloqueos
- **Saturación de reuniones** y sesiones sin hard stop → poco focus time (reportado en retros).
- **Dependencia de Víctor**, cada vez más absorbido por fundraising/Brain (mitigado con el modelo mutuo + mensual).
- **Calidad de leads**: Meta en modo *broad* genera volumen pero baja cualificación; ~300–400 registros orgánicos/mes con muy baja activación.
- **Nurturing**: el 1er autoresponder va bien (45% apertura, ~50% CTR) pero el 2º y 3º caen mucho.
- **Web**: ausencia de formulario "pedir demo" bien trackeado.

### Priorización del trabajo
Hoy la priorización vive dispersa (Notion/PBI en paid, compromisos por persona en cada Syncro). Falta un **único backlog priorizado** con owner y objetivo trimestral.

### Recursos necesarios
- Diseño (Diego Lunelli, freelance) para rebranding y material visual.
- Presupuesto paid y de plataformas (Capterra/G2).
- Posible apoyo de PR (agencia Comunicai, en evaluación).

---

## 3. Decisiones a tomar (propuesta)

### 3.1 Frecuencia de seguimiento

**Propuesta:**

| Ritmo | Ritual | Duración | Contenido |
|---|---|---|---|
| Diario | Async por canal (Discord: `@paid`, `@seo`, `@marketing`) + stand-up 9:40 | — | Desbloqueos rápidos; evitar alargar reuniones |
| Semanal | **Syncro Marketing Squad** | **60 min, hard stop** | Revisión de KPIs vs objetivo + decisiones + reparto de tareas por canal |
| Semanal | Sparrings mutuos | 30–45 min | Profundizar misión de cada persona |
| Mensual | Sparring con Víctor + **Marketing Review** | 60–90 min | KPIs del mes vs objetivo, aprendizajes, ajuste de prioridades |
| Trimestral | Planificación de roadmap / OKRs | 2 h | Fijar prioridades y objetivos del trimestre |

Clave: el Syncro pasa a tener **agenda fija y hard stop**; el reporting se lee **antes** de la reunión (Pilar comparte highlights semanales) para no gastar la sesión en revisar números.

### 3.2 KPIs del equipo

**North Star:** **Demos/SQL cualificadas generadas por Marketing** (la conversión demo→cliente es ~70%, así que las demos son la palanca directa de ingresos).

KPIs por función, todos con **objetivo mensual** que se fija en el Marketing Review:

| Área | KPIs primarios | KPIs de apoyo |
|---|---|---|
| **Paid** (Jonathan, Alejandro) | MQL (fit+hit ≥50), CPL y CP-MQL por canal, ROAS/CPA | Volumen de leads, % leads cualificados vs "porra", CTR/CPM |
| **SEO/Contenido** (Marina) | Leads orgánicos, rankings top 3/10 por vertical | Autoridad de dominio, tráfico orgánico, vistas YouTube→demo |
| **Marca/PR** (Marisa) | Demos originadas en eventos/PR, customer stories publicadas | Menciones en prensa, share of voice, impresiones |
| **RevOps/Automation** (Pilar) | Conversión MQL→SQL→Demo, cobertura de atribución | Apertura/CTR de nurturing, calidad de datos del CRM |

El reporting sale de los dashboards de este repo (`dashboard_ejecutivo`, `informe_leads_semanal`) para que la fuente sea única y compartida.

### 3.3 Reuniones

- **Consolidar** en las cuatro capas de la tabla 3.1; no crear reuniones nuevas sin quitar otra.
- Cada Syncro cierra con **compromisos por persona** (owner + plazo), como ya se viene haciendo el 20-jul.
- Mover temas operativos por canal a hilos async (WhatsApp, Instantly, HubSpot, workflows) para no alargar las sesiones.

### 3.4 Prioridades del trimestre

Basadas en las decisiones vivas del equipo (jul 2026):

1. **Marca**: cerrar reposicionamiento (tecnología/autonomía con tono intermedio, sin alarma) y validar rebranding con las 10 referencias de Diego; rebrand público y nota de prensa en **septiembre**.
2. **Adquisición cualificada**: reactivar campañas paid que funcionaron en junio; lanzar y explotar **Capterra/G2**; foco en verticales con menos presión de paid (salud, legal, inmobiliaria).
3. **Conversión**: arreglar la secuencia de nurturing (correos 2 y 3), añadir formulario "pedir demo" trackeado, mejorar activación de freemiums.
4. **Medición**: consolidar fit+hit score y el reporting único; cobertura de atribución por canal.
5. **Material visual de producto** para web y ventas.

---

## 4. Acciones

### 4.1 Definir rituales del equipo
- [ ] Formalizar la cadencia de la tabla 3.1 (agenda fija + hard stop de 60 min en el Syncro). — *Owner: Marisa + Pilar*
- [ ] Establecer que el reporting semanal se comparte y se lee antes del Syncro. — *Owner: Pilar*
- [ ] Confirmar el modelo de sparrings mutuos semanales + mensual con Víctor. — *Owner: Marisa*

### 4.2 Establecer KPIs
- [ ] Cerrar el cuadro de KPIs (3.2) y fijar objetivo mensual por área en el próximo Marketing Review. — *Owner: Pilar + cada responsable de área*
- [ ] Dejar los KPIs reflejados en `dashboard_ejecutivo` como panel de seguimiento del equipo. — *Owner: Pilar*

### 4.3 Crear roadmap de Marketing
- [ ] Trasladar las prioridades del trimestre (3.4) a un backlog único priorizado con owner y objetivo. — *Owner: Marisa*
- [ ] Revisar el roadmap en el Marketing Review mensual. — *Owner: equipo*

### 4.4 Definir ownership de cada área
- [ ] Confirmar la matriz de ownership de la sección 1.1 (Marca/Contenido → Marisa; Paid → Jonathan + Alejandro; SEO → Marina; RevOps/Automation → Pilar). — *Owner: equipo + Víctor*
- [ ] Cerrar la coordinación de roles dentro de paid (Jonathan ↔ Alejandro) para evitar solapamientos. — *Owner: Jonathan*

---

## 5. Matriz de ownership (RACI resumida)

| Área | Responsable (owner) | Consultado |
|---|---|---|
| Marca, mensaje e ICP | Marisa | Víctor, equipo |
| Rebranding / identidad visual | Marisa (con Diego Lunelli) | Equipo, producto |
| Paid / performance | Jonathan + Alejandro | Pilar (atribución) |
| SEO y contenido web/YouTube | Marina | Marisa (contenido) |
| RevOps, HubSpot y reporting | Pilar | Jonathan (scoring) |
| PR, eventos y prensa | Marisa | Ventas |
| Dirección / prioridades globales | Víctor | Squad |

---

*Fuentes internas (GuruSup Brain): serie Syncro Marketing Squad (2026-06-15 → 2026-07-20), decisión de sparrings mutuos (2026-06-24), concepto Funnel de leads, modelo fit/hit score (2026-07-20), reposicionamiento de marca (2026-07-20), fichas de equipo (Marisa Silva, Marina Mas), retros de equipo (jun–jul 2026).*
