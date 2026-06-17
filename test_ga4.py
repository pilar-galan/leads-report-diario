#!/usr/bin/env python3
"""
Test rápido: comprueba que la conexión a GA4 funciona.
Uso local:  python test_ga4.py
"""
from dotenv import load_dotenv
load_dotenv()

from ga4_client import run_report

rows = run_report(
    date_from="7daysAgo",
    date_to="today",
    metrics=["sessions", "totalUsers"],
    dimensions=["date"],
)

print(f"Últimos 7 días — {len(rows)} filas:\n")
for row in rows:
    fecha    = row["dimensionValues"][0]["value"]
    sessions = row["metricValues"][0]["value"]
    users    = row["metricValues"][1]["value"]
    print(f"  {fecha}  |  {sessions} sesiones, {users} usuarios")
