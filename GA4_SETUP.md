# Conexión con Google Analytics 4 (GA4)

El dashboard puede mostrar **tráfico web de GA4** (sesiones, usuarios,
conversiones y páginas top) junto a los leads de HubSpot.

La integración es **opcional**: si los secrets de GA4 no están configurados,
el dashboard se genera igual, simplemente sin la sección de GA4.

Usamos una **cuenta de servicio (Service Account)** en lugar de OAuth, porque
el dashboard se genera en **GitHub Actions sin nadie delante** (headless): la
cuenta de servicio no caduca ni necesita consentimiento por navegador.

---

## Pasos en Google Cloud (los haces tú, una sola vez)

> ⚠️ Estos pasos requieren tu sesión de Google y acceso a tu proyecto de
> Google Cloud + tu propiedad de GA4. No se pueden automatizar desde aquí.

### 1. Habilitar la API

1. Entra en <https://console.cloud.google.com/> y elige (o crea) un proyecto.
2. Ve a **APIs y servicios → Biblioteca**.
3. Busca y **habilita**:
   - **Google Analytics Data API** (`analyticsdata.googleapis.com`) — obligatoria.
   - **Google Analytics Admin API** — opcional (solo si algún día quieres
     listar propiedades por API).

### 2. Crear la cuenta de servicio

1. Ve a **APIs y servicios → Credenciales**.
2. **Crear credenciales → Cuenta de servicio**.
3. Ponle un nombre, p. ej. `ga4-dashboard-lector`. No hace falta asignarle
   roles de IAM del proyecto (los permisos se dan en GA4, paso 4). Crea.

### 3. Descargar la clave JSON

1. Entra en la cuenta de servicio recién creada → pestaña **Claves**.
2. **Agregar clave → Crear clave nueva → JSON**. Se descarga un fichero así:

   ```json
   {
     "type": "service_account",
     "project_id": "tu-proyecto",
     "private_key_id": "....",
     "private_key": "-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----\n",
     "client_email": "ga4-dashboard-lector@tu-proyecto.iam.gserviceaccount.com",
     ...
   }
   ```

3. Apunta el valor de **`client_email`** → lo necesitas en el paso 4.
4. **Guarda este JSON en lugar seguro y NO lo subas al repo.** Va como secret.

### 4. Dar acceso de lectura a la cuenta de servicio en GA4

1. Entra en <https://analytics.google.com/> → **Administrar** (⚙️).
2. En la columna de **Propiedad**, abre **Acceso a la propiedad**.
3. **+ → Agregar usuarios**: pega el `client_email` del paso 3.
4. Rol: **Lector (Viewer)**. Desmarca el envío de email de invitación. Guarda.

### 5. Obtener el Property ID

- En GA4 → **Administrar → Configuración de la propiedad**, copia el
  **ID de propiedad** (un número, p. ej. `123456789`).
- ⚠️ No es el `G-XXXX` (ese es el Measurement ID); necesitamos el **numérico**.

---

## Configurar los secrets en GitHub

En el repo: **Settings → Secrets and variables → Actions → New repository secret**.
Crea estos dos:

| Secret             | Valor                                                        |
|--------------------|-------------------------------------------------------------|
| `GA4_PROPERTY_ID`  | El ID numérico de la propiedad (paso 5), p. ej. `123456789` |
| `GA4_SA_JSON`      | El **contenido completo** del JSON de la cuenta de servicio |

> Para `GA4_SA_JSON`, copia y pega el JSON entero (con sus saltos de línea) tal
> cual lo descargaste. GitHub lo guarda cifrado.

El workflow ya pasa ambos secrets a `generate_dashboard.py` automáticamente.

---

## Probar en local (opcional)

```bash
pip install google-analytics-data

export GA4_PROPERTY_ID=123456789
export GA4_SA_FILE=./ga4-sa.json   # ruta al JSON descargado

python3 ga4_report.py              # imprime los datos de GA4 del último día
```

Si ves un JSON con `sessions`, `channels` y `top_pages`, ¡está conectado! 🎉

> En GitHub Actions se usa `GA4_SA_JSON` (el contenido). En local es más cómodo
> `GA4_SA_FILE` (la ruta al fichero). El código admite ambas.

---

## Qué métricas muestra

- **Totales**: sesiones, usuarios y conversiones (key events) del período.
- **Canales**: sesiones + usuarios por grupo de canal por defecto de GA4
  (SEO orgánico, Google Ads, Meta Ads, directo, email…).
- **Páginas top**: las 5 páginas más vistas del período.

El período es el mismo que el del dashboard: 8:30 del día anterior → 8:30 de
hoy (los lunes incluye el fin de semana), a nivel de día.
