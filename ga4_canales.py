#!/usr/bin/env python3
"""
Imprime una tabla de sesiones por canal de adquisición desde GA4.

Uso en local (con el .env ya configurado, ver README):

    python3 ga4_canales.py            # últimos 7 días
    python3 ga4_canales.py 30daysAgo  # rango personalizado (date_from)

Requiere las 4 variables de entorno de GA4 (ver .env.example).
"""
import sys

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from ga4_client import run_report


def sesiones_por_canal(date_from="7daysAgo", date_to="today"):
    rows = run_report(
        date_from=date_from,
        date_to=date_to,
        metrics=["sessions"],
        dimensions=["sessionDefaultChannelGroup"],
    )
    rows.sort(key=lambda r: int(r["sessions"]), reverse=True)
    return rows


def main():
    date_from = sys.argv[1] if len(sys.argv) > 1 else "7daysAgo"
    date_to = sys.argv[2] if len(sys.argv) > 2 else "today"

    rows = sesiones_por_canal(date_from, date_to)
    total = sum(int(r["sessions"]) for r in rows)

    print(f"\nSesiones por canal · {date_from} → {date_to}\n")
    print(f"{'Canal':<28}{'Sesiones':>10}{'%':>8}")
    print("-" * 46)
    for r in rows:
        canal = r["sessionDefaultChannelGroup"] or "(sin asignar)"
        sesiones = int(r["sessions"])
        pct = f"{sesiones / total * 100:.1f}%" if total else "—"
        print(f"{canal:<28}{sesiones:>10}{pct:>8}")
    print("-" * 46)
    print(f"{'TOTAL':<28}{total:>10}{'100%':>8}\n")


if __name__ == "__main__":
    main()
