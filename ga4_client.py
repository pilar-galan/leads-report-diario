#!/usr/bin/env python3
"""
Cliente reutilizable de la API de Google Analytics 4 (GA4 Data API).

Autenticación con una cuenta de servicio leída desde variables de entorno
(4 valores), sin necesidad de un fichero JSON de credenciales en disco:

    GA4_PROPERTY_ID   ID numérico de la propiedad GA4 (p. ej. 123456789)
    GA4_PROJECT_ID    ID del proyecto de Google Cloud
    GA4_CLIENT_EMAIL  Email de la cuenta de servicio
    GA4_PRIVATE_KEY   Clave privada de la cuenta de servicio

En local, define esos 4 valores en un fichero .env (ver .env.example) y
cárgalos antes de importar este módulo:

    from dotenv import load_dotenv
    load_dotenv()
    from ga4_client import run_report

    rows = run_report(date_from="7daysAgo", metrics=["sessions", "totalUsers"])
"""
import os

from google.oauth2 import service_account
from google.analytics.data_v1beta import BetaAnalyticsDataClient
from google.analytics.data_v1beta.types import (
    DateRange,
    Dimension,
    Metric,
    RunReportRequest,
)

_TOKEN_URI = "https://oauth2.googleapis.com/token"


def _get_credentials():
    """Construye las credenciales de cuenta de servicio desde el entorno."""
    required = ("GA4_PROJECT_ID", "GA4_CLIENT_EMAIL", "GA4_PRIVATE_KEY")
    missing = [k for k in required if not os.environ.get(k)]
    if missing:
        raise RuntimeError(
            "Faltan variables de entorno para GA4: " + ", ".join(missing) +
            ". Crea un .env (ver .env.example) o expórtalas en tu shell."
        )

    info = {
        "type": "service_account",
        "project_id": os.environ["GA4_PROJECT_ID"],
        "client_email": os.environ["GA4_CLIENT_EMAIL"],
        # Las claves privadas suelen guardarse con los saltos de línea
        # escapados (\n); los restauramos para que sean válidas.
        "private_key": os.environ["GA4_PRIVATE_KEY"].replace("\\n", "\n"),
        "token_uri": _TOKEN_URI,
    }
    scopes = ["https://www.googleapis.com/auth/analytics.readonly"]
    return service_account.Credentials.from_service_account_info(info, scopes=scopes)


def _property_id():
    pid = os.environ.get("GA4_PROPERTY_ID")
    if not pid:
        raise RuntimeError(
            "Falta la variable de entorno GA4_PROPERTY_ID "
            "(ID numérico de la propiedad GA4)."
        )
    # Aceptamos tanto "123456789" como "properties/123456789".
    return pid if pid.startswith("properties/") else f"properties/{pid}"


def run_report(
    date_from="7daysAgo",
    date_to="today",
    metrics=None,
    dimensions=None,
    limit=None,
):
    """Ejecuta un informe sobre la propiedad GA4 y devuelve filas como dicts.

    Args:
        date_from: inicio del rango. Acepta "YYYY-MM-DD", "today",
            "yesterday" o "NdaysAgo" (p. ej. "7daysAgo").
        date_to: fin del rango (mismo formato). Por defecto "today".
        metrics: lista de métricas (p. ej. ["sessions", "totalUsers"]).
        dimensions: lista opcional de dimensiones (p. ej. ["date", "country"]).
        limit: número máximo de filas a devolver (opcional).

    Returns:
        Lista de dicts; cada dict mapea el nombre de cada dimensión y métrica
        a su valor. Ejemplo:
            [{"date": "20260610", "sessions": "42", "totalUsers": "30"}, ...]
    """
    metrics = metrics or ["sessions"]
    dimensions = dimensions or []

    client = BetaAnalyticsDataClient(credentials=_get_credentials())

    request = RunReportRequest(
        property=_property_id(),
        date_ranges=[DateRange(start_date=date_from, end_date=date_to)],
        metrics=[Metric(name=m) for m in metrics],
        dimensions=[Dimension(name=d) for d in dimensions],
        limit=limit,
    )

    response = client.run_report(request)

    dim_headers = [h.name for h in response.dimension_headers]
    metric_headers = [h.name for h in response.metric_headers]

    rows = []
    for row in response.rows:
        record = {}
        for name, value in zip(dim_headers, row.dimension_values):
            record[name] = value.value
        for name, value in zip(metric_headers, row.metric_values):
            record[name] = value.value
        rows.append(record)
    return rows


if __name__ == "__main__":
    # Ejecución directa para una comprobación rápida desde la terminal:
    #   python3 ga4_client.py
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    sample = run_report(
        date_from="7daysAgo",
        metrics=["sessions", "totalUsers"],
        dimensions=["date"],
    )
    print(f"Filas devueltas: {len(sample)}")
    for r in sample[:10]:
        print(r)
