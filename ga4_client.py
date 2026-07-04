"""
Cliente GA4 reutilizable.
Requiere estas variables de entorno (en .env o GitHub Secrets):
  GSC_CLIENT_ID, GSC_CLIENT_SECRET, GA4_PROPERTY_ID, GA4_REFRESH_TOKEN
"""
import os
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

_client = None


def _get_client():
    global _client
    if _client:
        return _client
    creds = Credentials(
        token=None,
        refresh_token=os.environ["GA4_REFRESH_TOKEN"],
        token_uri="https://oauth2.googleapis.com/token",
        client_id=os.environ["GSC_CLIENT_ID"],
        client_secret=os.environ["GSC_CLIENT_SECRET"],
    )
    _client = build("analyticsdata", "v1beta", credentials=creds)
    return _client


def run_report(date_from="30daysAgo", date_to="today", metrics=None, dimensions=None, dimension_filter=None):
    """
    Ejecuta un runReport contra GA4 y devuelve las filas.

    metrics:    lista de nombres, ej. ["sessions", "totalUsers"]
    dimensions: lista de nombres, ej. ["date", "sessionDefaultChannelGroup"]
    """
    if metrics is None:
        metrics = ["sessions", "totalUsers"]
    if dimensions is None:
        dimensions = ["date"]

    property_id = os.environ["GA4_PROPERTY_ID"]
    client = _get_client()

    body = {
        "dateRanges": [{"startDate": date_from, "endDate": date_to}],
        "metrics": [{"name": m} for m in metrics],
        "dimensions": [{"name": d} for d in dimensions],
    }
    if dimension_filter:
        body["dimensionFilter"] = dimension_filter

    response = client.properties().runReport(
        property=f"properties/{property_id}",
        body=body,
    ).execute()

    return response.get("rows", [])
