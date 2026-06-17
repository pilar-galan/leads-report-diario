# leads-report-diario

Automatizaciones de reporting diario de GuruSup:

- **`generate_dashboard.py`** — genera `dashboard_diario.html` con datos reales de HubSpot.
- **`radar_ia.py`** — resumen diario de noticias IA/CX y envío a Discord.
- **`ga4_client.py`** — cliente reutilizable de la API de Google Analytics 4.

## Cliente GA4 en local

Para usar la API de GA4 desde tu máquina:

1. **Instala las dependencias:**

   ```bash
   pip install -r requirements.txt
   ```

2. **Crea un fichero `.env`** (a partir de `.env.example`) con los 4 valores
   de la cuenta de servicio (Pilar te los pasa por DM):

   ```
   GA4_PROPERTY_ID=...
   GA4_PROJECT_ID=...
   GA4_CLIENT_EMAIL=...
   GA4_PRIVATE_KEY="-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----\n"
   ```

   > El `.env` está en `.gitignore`, así que nunca se sube al repositorio.

3. **Úsalo desde cualquier script:**

   ```python
   from dotenv import load_dotenv
   load_dotenv()
   from ga4_client import run_report

   rows = run_report(date_from="7daysAgo", metrics=["sessions", "totalUsers"])
   print(rows)
   ```

   También puedes pasar dimensiones, rango de fechas y límite:

   ```python
   rows = run_report(
       date_from="2026-06-01",
       date_to="today",
       metrics=["sessions", "totalUsers"],
       dimensions=["date", "country"],
       limit=100,
   )
   ```

   Cada fila es un `dict` con el nombre de cada dimensión/métrica como clave.

4. **Comprobación rápida** desde la terminal:

   ```bash
   python3 ga4_client.py
   ```
