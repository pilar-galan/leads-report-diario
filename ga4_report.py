#!/usr/bin/env python3
"""
Lectura de datos de Google Analytics 4 (GA4) vía Google Analytics Data API
(analyticsdata v1beta), usando una cuenta de servicio (Service Account).

Diseñado para ser OPCIONAL: si no hay credenciales o la librería no está
instalada, fetch_ga4() devuelve {"available": False} y el dashboard se
genera igual, sin la sección de GA4. Así el workflow nunca se rompe.

Variables de entorno:
  GA4_PROPERTY_ID  → ID numérico de la propiedad GA4 (ej. "123456789")
  GA4_SA_JSON      → contenido del JSON de la cuenta de servicio (string)
                     (alternativa: GA4_SA_FILE con la ruta a un fichero .json)
"""
import os
import json

# Nombres de canal de GA4 (sessionDefaultChannelGroup) → etiqueta ES + icono + color.
# Se mantienen los mismos iconos/colores que classify_channel() del dashboard
# para que la lectura visual sea coherente entre leads (HubSpot) y tráfico (GA4).
GA4_CHANNEL_META = {
    "Organic Search": ("SEO Orgánico",    "🌿", "#10b981"),
    "Paid Search":    ("Google Ads",      "🔍", "#4285F4"),
    "Paid Social":    ("Meta Ads",        "📣", "#ec4899"),
    "Organic Social": ("Social orgánico", "📱", "#38bdf8"),
    "Email":          ("Email",           "✉️", "#f97316"),
    "Referral":       ("Referido",        "🤝", "#a78bfa"),
    "Direct":         ("Web directo",     "🔗", "#94a3b8"),
    "Display":        ("Display",         "🖼️", "#f59e0b"),
    "Affiliates":     ("Afiliados",       "🔗", "#a78bfa"),
    "Unassigned":     ("Sin asignar",     "❓", "#7b76a0"),
}


def _load_credentials_info():
    """Devuelve el dict de credenciales de la cuenta de servicio, o None."""
    raw = os.environ.get("GA4_SA_JSON", "").strip()
    if raw:
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            print("GA4: GA4_SA_JSON no es un JSON válido", flush=True)
            return None
    path = os.environ.get("GA4_SA_FILE", "").strip()
    if path and os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return None


def _client():
    """Crea el cliente de la GA4 Data API. Devuelve None si no es posible."""
    info = _load_credentials_info()
    if not info:
        return None
    try:
        from google.oauth2 import service_account
        from google.analytics.data_v1beta import BetaAnalyticsDataClient
    except ImportError:
        print("GA4: falta la librería 'google-analytics-data' (pip install)", flush=True)
        return None
    creds = service_account.Credentials.from_service_account_info(
        info, scopes=["https://www.googleapis.com/auth/analytics.readonly"]
    )
    return BetaAnalyticsDataClient(credentials=creds)


def _run(client, property_id, dimensions, metrics, order_metric=None, limit=10):
    """Ejecuta un RunReportRequest y devuelve las filas (o [] si falla)."""
    from google.analytics.data_v1beta.types import (
        DateRange, Dimension, Metric, RunReportRequest, OrderBy,
    )
    order_bys = []
    if order_metric:
        order_bys = [OrderBy(
            metric=OrderBy.MetricOrderBy(metric_name=order_metric), desc=True
        )]
    req = RunReportRequest(
        property=f"properties/{property_id}",
        date_ranges=[DateRange(start_date=_SD, end_date=_ED)],
        dimensions=[Dimension(name=d) for d in dimensions],
        metrics=[Metric(name=m) for m in metrics],
        order_bys=order_bys,
        limit=limit,
    )
    resp = client.run_report(req)
    return resp.rows


# Variables de rango fijadas por fetch_ga4 (las usa _run).
_SD = ""
_ED = ""


def _to_int(value):
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def fetch_ga4(start_dt, end_dt):
    """
    Devuelve un dict con datos de GA4 para el rango [start_dt, end_dt].
    Las fechas se toman a nivel de día (GA4 trabaja con días, no horas).

    Estructura devuelta:
      {
        "available": bool,
        "period":   (start_date, end_date),
        "totals":   {"sessions": int, "users": int, "key_events": int},
        "channels": [(label, icon, color, sessions, users), ...],
        "top_pages":[(page_path, views), ...],
      }
    """
    global _SD, _ED
    property_id = os.environ.get("GA4_PROPERTY_ID", "").strip()
    if not property_id:
        return {"available": False}

    client = _client()
    if client is None:
        return {"available": False}

    _SD = start_dt.strftime("%Y-%m-%d")
    _ED = end_dt.strftime("%Y-%m-%d")

    result = {
        "available": True,
        "period": (_SD, _ED),
        "totals": {"sessions": 0, "users": 0, "key_events": 0},
        "channels": [],
        "top_pages": [],
    }

    # ── Totales globales ──────────────────────────────────────────────
    try:
        rows = _run(client, property_id, [], ["sessions", "totalUsers", "keyEvents"])
        if rows:
            mv = rows[0].metric_values
            result["totals"] = {
                "sessions":   _to_int(mv[0].value),
                "users":      _to_int(mv[1].value),
                "key_events": _to_int(mv[2].value),
            }
    except Exception as ex:  # noqa: BLE001
        print(f"GA4: error leyendo totales: {ex}", flush=True)
        # Si falla la primera llamada (credenciales/propiedad/permisos),
        # no tiene sentido seguir: degradamos a no disponible.
        return {"available": False}

    # ── Canales (sesiones + usuarios por grupo de canal) ──────────────
    try:
        rows = _run(client, property_id, ["sessionDefaultChannelGroup"],
                    ["sessions", "totalUsers"], order_metric="sessions", limit=12)
        for r in rows:
            raw_label = r.dimension_values[0].value
            label, icon, color = GA4_CHANNEL_META.get(
                raw_label, (raw_label or "Otros", "❓", "#7b76a0")
            )
            sessions = _to_int(r.metric_values[0].value)
            users    = _to_int(r.metric_values[1].value)
            result["channels"].append((label, icon, color, sessions, users))
    except Exception as ex:  # noqa: BLE001
        print(f"GA4: error leyendo canales: {ex}", flush=True)

    # ── Páginas más vistas ────────────────────────────────────────────
    try:
        rows = _run(client, property_id, ["pagePath"], ["screenPageViews"],
                    order_metric="screenPageViews", limit=5)
        for r in rows:
            path  = r.dimension_values[0].value
            views = _to_int(r.metric_values[0].value)
            result["top_pages"].append((path, views))
    except Exception as ex:  # noqa: BLE001
        print(f"GA4: error leyendo páginas: {ex}", flush=True)

    return result


if __name__ == "__main__":
    # Prueba rápida en local:
    #   GA4_PROPERTY_ID=... GA4_SA_FILE=./sa.json python3 ga4_report.py
    from datetime import datetime, timedelta, timezone
    now = datetime.now(timezone.utc)
    out = fetch_ga4(now - timedelta(days=1), now)
    print(json.dumps(out, indent=2, ensure_ascii=False))
