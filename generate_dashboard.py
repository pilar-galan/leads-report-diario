#!/usr/bin/env python3
"""
Genera dashboard_diario.html con datos reales de HubSpot.
Ventana: 8:30h dia anterior -> 8:30h hoy (hora Espana).
Lunes cubre fin de semana: viernes 8:30 -> lunes 8:30.

Reparto hibrido (acordado con marketing):
  - Embudo, canales, revision_ventas, estado_sql_consultoria, pipeline,
    reuniones agendadas de marketing -> AUTOMATICO desde HubSpot.
  - Barra de prioridades, flechas de flujo, aprendizajes de llamadas,
    paleta y diseno -> FIJO en este script.
"""
import os, sys, json, urllib.request, urllib.error, re
from datetime import datetime, timedelta, timezone

TOKEN = os.environ.get("HUBSPOT_TOKEN", "")
BASE  = "https://api.hubapi.com"

MESES = ["enero","febrero","marzo","abril","mayo","junio","julio",
         "agosto","septiembre","octubre","noviembre","diciembre"]
DIAS  = ["Lunes","Martes","Miércoles","Jueves","Viernes","Sábado","Domingo"]

# ── Fuentes que consideramos MARKETING (adquisición inbound) ──
MARKETING_SOURCES = {
    "PAID_SEARCH", "PAID_SOCIAL", "ORGANIC_SEARCH", "SOCIAL_MEDIA",
    "DIRECT_TRAFFIC", "REFERRALS", "OTHER_CAMPAIGNS",
}

# ── Etapas del pipeline (deal stages) ──
STAGE_LABELS = [
    ("1107496610",           "Discovery",      "pill-discov"),
    ("presentationscheduled","Demo / Reunión",  "pill-demo"),
    ("1033589123",           "Best Case",      "pill-best"),
]

LC_LABELS = {
    "lead":                   "Lead",
    "salesqualifiedlead":     "SQL-Consultoría",
    "1378463825":             "Freemium",
    "marketingqualifiedlead": "MQL",
    "opportunity":            "Oportunidad",
    "customer":               "Cliente",
}

# ── Etapa del ciclo de vida (lifecyclestage) — value -> (label, color) ──
LC_META = [
    ("subscriber",            "Suscriptor",      "var(--muted)"),
    ("lead",                  "Lead",            "var(--guru-500)"),
    ("marketingqualifiedlead","MQL",             "var(--blue)"),
    ("salesqualifiedlead",    "SQL-Consultoría", "var(--orange)"),
    ("1378463825",            "Freemium",        "var(--guru-400)"),
    ("opportunity",           "Oportunidad",     "var(--green)"),
    ("customer",              "Cliente",         "var(--green)"),
    ("other",                 "Otra etapa",      "var(--muted)"),
]

# ── Revisión ventas (propiedad revision_ventas) — orden y color ──
REV_META = [
    ("Ya gestionado",                   "var(--green)"),
    ("Pendiente de revisión",           "var(--amber)"),
    ("En revisión",                     "var(--blue)"),
    ("Aceptado para gestión comercial", "var(--orange)"),
    ("Duplicado",                       "var(--guru-400)"),
    ("No aplica / Descartado",          "var(--red)"),
    ("Test",                            "var(--muted)"),
]

# ── Canales de adquisición fijos (siempre visibles aunque estén a 0) ──
FIXED_CHANNELS = {
    "Social Ads":         {"n": 0, "sql": 0, "icon": "📣", "color": "#a855f7", "lc": {}},
    "Google Ads":         {"n": 0, "sql": 0, "icon": "🔍", "color": "#4285F4", "lc": {}},
    "Tráfico directo":    {"n": 0, "sql": 0, "icon": "🔗", "color": "#94a3b8", "lc": {}},
    "SEO Orgánico":       {"n": 0, "sql": 0, "icon": "🌿", "color": "#10b981", "lc": {}},
    "Social orgánico":    {"n": 0, "sql": 0, "icon": "🌱", "color": "#22c55e", "lc": {}},
    "Eventos / Campañas": {"n": 0, "sql": 0, "icon": "🎪", "color": "#ec4899", "lc": {}},
    "Chat web":           {"n": 0, "sql": 0, "icon": "💬", "color": "#22d3ee", "lc": {}},
}


# ────────────────────────── HubSpot API ──────────────────────────
def api_post(path, payload):
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def api_get(path):
    req = urllib.request.Request(
        BASE + path,
        headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"},
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def fetch_all(obj_type, filters, properties):
    results, after = [], None
    while True:
        payload = {"filterGroups": [{"filters": filters}], "properties": properties, "limit": 100}
        if after:
            payload["after"] = after
        data = api_post(f"/crm/v3/objects/{obj_type}/search", payload)
        results.extend(data.get("results", []))
        after = data.get("paging", {}).get("next", {}).get("after")
        if not after:
            break
    return results


def iso(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


# ────────────────────────── Clasificadores ──────────────────────────
def classify_channel(src, d1):
    """Devuelve (label, icon, color) alineado con la taxonomía de marketing."""
    d1 = d1 or ""
    if src == "PAID_SEARCH":     return ("Google Ads",         "🔍", "#4285F4")
    if src == "PAID_SOCIAL":     return ("Social Ads",         "📣", "#a855f7")
    if src == "ORGANIC_SEARCH":  return ("SEO Orgánico",       "🌿", "#10b981")
    if src == "SOCIAL_MEDIA":    return ("Social orgánico",    "🌱", "#22c55e")
    if src == "REFERRALS":       return ("Referido",           "🤝", "#a78bfa")
    if src == "OTHER_CAMPAIGNS": return ("Eventos / Campañas", "🎪", "#ec4899")
    if src == "EMAIL_MARKETING": return ("Email", "✉️", "#f97316")
    if src == "OFFLINE" and d1 == "CONVERSATIONS":
        return ("Chat web", "💬", "#22d3ee")
    if src == "DIRECT_TRAFFIC":
        # Incluye las altas por la app (freemium); se cuentan por su origen: tráfico directo
        return ("Tráfico directo", "🔗", "#94a3b8")
    return ("Otros", "•", "#64748b")


def is_marketing(src, d1):
    if src in MARKETING_SOURCES:
        return True
    if src == "OFFLINE" and (d1 or "") == "CONVERSATIONS":
        return True
    return False


def is_import(src, d1):
    return src == "OFFLINE" and (d1 or "") in ("INTEGRATION", "CRM_UI", "IMPORT")


def is_test(rev, email):
    e = (email or "").lower()
    return ((rev or "") == "Test" or e.startswith("demo@") or "prueba" in e
            or "yanoestaenelcrm" in e or "@test." in e or e.endswith(".test"))


def is_internal(email):
    return (email or "").endswith("@gurusup.com")


def is_valid_deal(name):
    n = (name or "").lower()
    return ("@" not in n and "[duplicado]" not in n
            and not n.rstrip().endswith("new deal") and "- new deal" not in n)


def clean_deal_name(name):
    n = re.sub(r'\s*-\s*nuevo tipo de objeto deal\s*$', '', name or "", flags=re.I)
    return n.strip()


def esc(t):
    return str(t).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def pct(n, base):
    return f"{round(n/base*100)}%" if base else "—"


# ────────────────────────── Llamadas ──────────────────────────
def fetch_calls_summary(start_iso, end_iso):
    """
    Llamadas registradas en la ventana (objeto Calls de HubSpot).
    Devuelve {total, completed, outbound}. Defensivo: si falla, ceros.
    """
    try:
        calls = fetch_all("calls", [
            {"propertyName": "hs_timestamp", "operator": "BETWEEN", "value": start_iso, "highValue": end_iso},
        ], ["hs_call_status", "hs_call_direction"])
    except Exception as err:
        print(f"  calls search error: {err}")
        return {"total": 0, "completed": 0, "outbound": 0}
    total     = len(calls)
    completed = sum(1 for c in calls if c["properties"].get("hs_call_status") == "COMPLETED")
    outbound  = sum(1 for c in calls if c["properties"].get("hs_call_direction") == "OUTBOUND")
    return {"total": total, "completed": completed, "outbound": outbound}


# ────────────────────────── Reuniones de marketing ──────────────────────────
def fetch_marketing_meetings(start_iso, end_iso):
    """
    Reuniones creadas en la ventana cuyo contacto asociado entró por un canal
    de marketing. Devuelve lista de dicts {company, channel}.
    Defensivo: si algo falla, devuelve lo recolectado.
    """
    out = []
    try:
        data = api_post("/crm/v3/objects/meetings/search", {
            "filterGroups": [{"filters": [
                {"propertyName": "hs_createdate", "operator": "BETWEEN",
                 "value": start_iso, "highValue": end_iso},
            ]}],
            "properties": ["hs_meeting_title"],
            "limit": 100,
        })
    except Exception as err:
        print(f"  meetings search error: {err}")
        return out

    seen = set()
    for m in data.get("results", []):
        mid = m["id"]
        try:
            assoc = api_get(f"/crm/v4/objects/meetings/{mid}/associations/contacts")
            cids = [r["toObjectId"] for r in assoc.get("results", [])]
        except Exception:
            cids = []
        for cid in cids[:1]:
            try:
                c = api_get(f"/crm/v3/objects/contacts/{cid}"
                            "?properties=hs_analytics_source,hs_analytics_source_data_1,company,firstname")
                cp  = c.get("properties", {})
                src = cp.get("hs_analytics_source") or ""
                d1  = cp.get("hs_analytics_source_data_1") or ""
            except Exception:
                continue
            if not is_marketing(src, d1):
                continue
            company = cp.get("company") or ""
            firstname = cp.get("firstname") or ""
            try:
                ca = api_get(f"/crm/v4/objects/contacts/{cid}/associations/companies")
                coids = [r["toObjectId"] for r in ca.get("results", [])]
                if coids:
                    co = api_get(f"/crm/v3/objects/companies/{coids[0]}?properties=name")
                    nm = co.get("properties", {}).get("name")
                    if nm:
                        company = nm
            except Exception:
                pass
            label, _, _ = classify_channel(src, d1)
            company = company.strip() or firstname.strip() or "Sin empresa"
            key = f"{company.lower()}|{label}"
            if key in seen:
                continue
            seen.add(key)
            out.append({"company": company, "channel": label})
    return out


def fetch_deal_company(deal_id):
    """Nombre de la empresa asociada a un deal (o None si no tiene)."""
    try:
        ca = api_get(f"/crm/v4/objects/deals/{deal_id}/associations/companies")
        coids = [r["toObjectId"] for r in ca.get("results", [])]
        if coids:
            co = api_get(f"/crm/v3/objects/companies/{coids[0]}?properties=name")
            nm = co.get("properties", {}).get("name")
            if nm:
                return nm.strip()
    except Exception:
        pass
    return None


def fetch_deal_contact_company(deal_id):
    """Fallback: empresa (texto) o nombre del contacto asociado a un deal."""
    try:
        ca = api_get(f"/crm/v4/objects/deals/{deal_id}/associations/contacts")
        cids = [r["toObjectId"] for r in ca.get("results", [])]
        if cids:
            c = api_get(f"/crm/v3/objects/contacts/{cids[0]}?properties=company,firstname")
            cp = c.get("properties", {})
            return (cp.get("company") or "").strip() or (cp.get("firstname") or "").strip()
    except Exception:
        pass
    return None


def fetch_generated_opportunities(start_iso, end_iso, is_valid_deal, clean_deal_name):
    """
    Oportunidades (deals) creadas en la ventana, de canales de marketing,
    con independencia de si siguen abiertas. Devuelve lista de dicts
    {company, channel} para el KPI del embudo superior.
    """
    out = []
    try:
        deals = fetch_all("deals", [
            {"propertyName": "pipeline", "operator": "EQ", "value": "default"},
            {"propertyName": "createdate", "operator": "BETWEEN", "value": start_iso, "highValue": end_iso},
        ], ["dealname", "hs_analytics_source", "hs_analytics_source_data_1", "createdate"])
    except Exception as err:
        print(f"  generated-opportunities search error: {err}")
        return out

    seen = set()
    for dl in deals:
        p = dl["properties"]
        name = p.get("dealname", "")
        if not is_valid_deal(name):
            continue
        src = p.get("hs_analytics_source") or ""
        d1  = p.get("hs_analytics_source_data_1") or ""
        if is_import(src, d1) or not is_marketing(src, d1):
            continue
        label, _, _ = classify_channel(src, d1)
        company = fetch_deal_company(dl["id"])
        if not company:
            company = fetch_deal_contact_company(dl["id"])
        company = (company or clean_deal_name(name) or "Sin empresa").strip() or "Sin empresa"
        key = f"{company.lower()}|{label}|{dl['id']}"
        if key in seen:
            continue
        seen.add(key)
        out.append({"company": company, "channel": label})
    return out


def fetch_generated_clients(start_iso, end_iso):
    """
    Contactos que pasaron a Cliente en la ventana y entraron por un canal
    de marketing. Devuelve lista de dicts {company, channel}.
    """
    out = []
    try:
        contacts = fetch_all("contacts", [
            {"propertyName": "createdate", "operator": "BETWEEN", "value": start_iso, "highValue": end_iso},
            {"propertyName": "lifecyclestage", "operator": "EQ", "value": "customer"},
        ], ["email", "firstname", "company", "hs_analytics_source", "hs_analytics_source_data_1"])
    except Exception as err:
        print(f"  generated-clients search error: {err}")
        return out

    seen = set()
    for c in contacts:
        p = c["properties"]
        src = p.get("hs_analytics_source") or ""
        d1  = p.get("hs_analytics_source_data_1") or ""
        if not is_marketing(src, d1):
            continue
        label, _, _ = classify_channel(src, d1)
        company = (p.get("company") or "").strip()
        if not company:
            email = p.get("email") or ""
            company = (email.split("@")[-1].split(".")[0].capitalize() if "@" in email
                       else p.get("firstname") or "Sin empresa")
        key = f"{company.lower()}|{label}|{c['id']}"
        if key in seen:
            continue
        seen.add(key)
        out.append({"company": company, "channel": label})
    return out


# ────────────────────────── Main ──────────────────────────
def main():
    if not TOKEN:
        print("ERROR: falta HUBSPOT_TOKEN", file=sys.stderr)
        sys.exit(1)

    tz_spain = timezone(timedelta(hours=2))
    es_now   = datetime.now(timezone.utc).astimezone(tz_spain)

    # Overrides opcionales por variables de entorno (informes ad-hoc, p. ej. mensual)
    gen_start = os.environ.get("GEN_START")   # ISO, p. ej. 2026-06-01T00:00:00
    gen_end   = os.environ.get("GEN_END")     # ISO, p. ej. 2026-07-01T00:00:00
    out_file  = os.environ.get("GEN_OUTPUT", "dashboard_diario.html")
    title     = os.environ.get("GEN_TITLE",  "GuruSup · Dashboard Diario")
    period_ov = os.environ.get("GEN_PERIOD")
    fecha_ov  = os.environ.get("GEN_FECHA")

    is_monthly = bool(gen_start and gen_end)

    if gen_start and gen_end:
        start  = datetime.fromisoformat(gen_start).replace(tzinfo=tz_spain)
        es_now = datetime.fromisoformat(gen_end).replace(tzinfo=tz_spain)
        start_iso = iso(start)
        end_iso   = iso(es_now)
        fecha_larga = fecha_ov or "Informe mensual"
        periodo_txt = period_ov or (f"{start.day} {MESES[start.month-1][:3]} → "
                                    f"{es_now.day} {MESES[es_now.month-1][:3]} {es_now.year}")
    else:
        # Ancla a las 8:00. Lunes cubre el fin de semana (viernes 8:00 → lunes ~9:00).
        today_8   = es_now.replace(hour=8, minute=0, second=0, microsecond=0)
        days_back = 3 if es_now.weekday() == 0 else 1
        start     = today_8 - timedelta(days=days_back)
        start_iso = iso(start)
        end_iso   = iso(es_now)
        fecha_larga = f"{DIAS[es_now.weekday()]}, {es_now.day} de {MESES[es_now.month-1]} de {es_now.year}"
        periodo_txt = (f"{start.day} {MESES[start.month-1][:3]} {start.strftime('%H:%M')} → "
                       f"{es_now.day} {MESES[es_now.month-1][:3]} {es_now.strftime('%H:%M')} (hora España)")
        if es_now.weekday() == 0:
            periodo_txt += " · incluye fin de semana"

    win_filters = [
        {"propertyName": "createdate", "operator": "BETWEEN", "value": start_iso, "highValue": end_iso},
        {"propertyName": "email", "operator": "NOT_CONTAINS_TOKEN", "value": "gurusup.com"},
    ]
    raw = fetch_all("contacts", win_filters, [
        "email", "firstname", "company", "lifecyclestage", "hs_analytics_source",
        "hs_analytics_source_data_1", "revision_ventas", "estado_sql_consultoria",
        "hs_lead_status",
    ])

    real = []
    imports = tests = internal = 0
    for c in raw:
        p     = c["properties"]
        email = p.get("email") or ""
        src   = p.get("hs_analytics_source") or ""
        d1    = p.get("hs_analytics_source_data_1") or ""
        if is_internal(email): internal += 1; continue
        if is_test(p.get("revision_ventas"), email): tests += 1; continue
        if is_import(src, d1): imports += 1; continue
        real.append({
            "src": src, "d1": d1,
            "lc":  p.get("lifecyclestage") or "",
            "rev": p.get("revision_ventas") or "",
            "sql_state": p.get("estado_sql_consultoria") or "",
            "lead_state": p.get("hs_lead_status") or "",
            "email": email,
            "firstname": p.get("firstname") or "",
            "company": p.get("company") or "",
        })

    total  = len(real)
    n_lead = sum(1 for l in real if l["lc"] == "lead")
    n_sql  = sum(1 for l in real if l["lc"] == "salesqualifiedlead")
    n_free = sum(1 for l in real if l["lc"] == "1378463825" or l["sql_state"] == "Freemium")

    # Canales
    chan = {}
    for l in real:
        label, icon, color = classify_channel(l["src"], l["d1"])
        if label not in chan:
            chan[label] = {"n": 0, "sql": 0, "icon": icon, "color": color, "lc": {}}
        chan[label]["n"] += 1
        if l["lc"] == "salesqualifiedlead":
            chan[label]["sql"] += 1
        lc_lbl = LC_LABELS.get(l["lc"], l["lc"] or "—")
        chan[label]["lc"][lc_lbl] = chan[label]["lc"].get(lc_lbl, 0) + 1
    for fc_label, fc_data in FIXED_CHANNELS.items():
        if fc_label not in chan:
            chan[fc_label] = dict(fc_data)
    channels = sorted(chan.items(), key=lambda x: (-x[1]["n"], x[0]))

    # Revisión ventas (con desglose por etapa: lead / SQL / freemium)
    rev_counts = {}
    rev_lc = {}
    for l in real:
        key = l["rev"] if l["rev"] else "Pendiente de revisión"
        rev_counts[key] = rev_counts.get(key, 0) + 1
        b = rev_lc.setdefault(key, {"lead": 0, "sql": 0, "free": 0})
        if l["lc"] == "salesqualifiedlead":
            b["sql"] += 1
        elif l["lc"] == "1378463825" or l["sql_state"] == "Freemium":
            b["free"] += 1
        else:
            b["lead"] += 1

    # Etapa del ciclo de vida
    lc_counts = {}
    for l in real:
        lc_counts[l["lc"]] = lc_counts.get(l["lc"], 0) + 1

    # Tabla de SQL para "Llamadas"
    sql_rows = []
    for l in real:
        if l["lc"] == "salesqualifiedlead":
            label, _, _ = classify_channel(l["src"], l["d1"])
            name = l["firstname"] or (l["email"].split("@")[0] if l["email"] else "—")
            sql_rows.append({"name": name, "company": l["company"],
                             "channel": label, "state": l["sql_state"] or "Pendiente"})
    sql_rows.sort(key=lambda r: r["channel"])

    n_sql_pendientes = sum(1 for r in sql_rows if r["state"] == "Pendiente")
    calls_summary = {"total": 0, "completed": 0, "outbound": 0} if is_monthly else fetch_calls_summary(start_iso, end_iso)

    # Reuniones de marketing (auto)
    meetings = fetch_marketing_meetings(start_iso, end_iso)
    n_meetings = len(meetings)
    meeting_companies = " · ".join(
        f"<strong>{esc(m['company'])}</strong> <span style=\"opacity:.7\">({esc(m['channel'])})</span>"
        for m in meetings) or "—"

    # Pipeline (solo marketing)
    deal_filters = [
        {"propertyName": "pipeline",     "operator": "EQ", "value": "default"},
        {"propertyName": "hs_is_closed", "operator": "EQ", "value": "false"},
    ]
    all_deals = fetch_all("deals", deal_filters,
                          ["dealname", "dealstage", "createdate",
                           "hs_analytics_source", "hs_analytics_source_data_1"])

    mkt_deals = []
    for dl in all_deals:
        p = dl["properties"]
        if not is_valid_deal(p.get("dealname", "")):
            continue
        src = p.get("hs_analytics_source") or ""
        d1  = p.get("hs_analytics_source_data_1") or ""
        if not is_marketing(src, d1):
            continue
        label, icon, _ = classify_channel(src, d1)
        mkt_deals.append({
            "id": dl["id"],
            "name": clean_deal_name(p.get("dealname", "—")) or "—",
            "stage": p.get("dealstage", ""),
            "created": (p.get("createdate") or "")[:10],
            "channel": f"{icon} {label}",
        })

    start_day      = start_iso[:10]
    nuevos_deals   = [d for d in mkt_deals if d["created"] and d["created"] >= start_day]
    demos_pipeline = [d for d in mkt_deals if d["stage"] == "presentationscheduled"]

    chan_dist = {}
    for d in mkt_deals:
        chan_dist[d["channel"]] = chan_dist.get(d["channel"], 0) + 1

    # Oportunidades y clientes generados en el período, solo marketing (embudo comercial)
    generated_opps = fetch_generated_opportunities(start_iso, end_iso, is_valid_deal, clean_deal_name)
    n_opps_generated = len(generated_opps)
    opps_generated_companies = " · ".join(
        f"<strong>{esc(o['company'])}</strong> <span style=\"opacity:.7\">({esc(o['channel'])})</span>"
        for o in generated_opps) or "—"

    generated_clients = fetch_generated_clients(start_iso, end_iso) if is_monthly else []
    n_clients_generated = len(generated_clients)
    clients_generated_companies = " · ".join(
        f"<strong>{esc(o['company'])}</strong> <span style=\"opacity:.7\">({esc(o['channel'])})</span>"
        for o in generated_clients) or "—"

    data = {
        "title": title, "is_monthly": is_monthly,
        "fecha_larga": fecha_larga, "periodo_txt": periodo_txt,
        "total": total, "n_lead": n_lead, "n_sql": n_sql, "n_free": n_free,
        "pct_lead": pct(n_lead, total), "pct_sql": pct(n_sql, total), "pct_free": pct(n_free, total),
        "n_meetings": n_meetings, "meeting_companies": meeting_companies,
        "n_opps_generated": n_opps_generated, "opps_generated_companies": opps_generated_companies,
        "n_clients_generated": n_clients_generated, "clients_generated_companies": clients_generated_companies,
        "channels": channels, "rev_counts": rev_counts, "rev_lc": rev_lc, "lc_counts": lc_counts,
        "sql_rows": sql_rows, "mkt_deals": mkt_deals,
        "n_sql_pendientes": n_sql_pendientes, "calls_summary": calls_summary,
        "nuevos_deals": len(nuevos_deals), "demos_pipeline": len(demos_pipeline),
        "nuevos_ids": {d["id"] for d in nuevos_deals}, "chan_dist": chan_dist,
        "imports": imports, "tests": tests, "internal": internal,
        "generado": es_now.strftime("%d %b %Y · %H:%M"),
    }

    html = render(data)
    with open(out_file, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"OK · contactos={total} leads={n_lead} sql={n_sql} free={n_free} "
          f"reuniones={n_meetings} deals_mkt={len(mkt_deals)} imports={imports} tests={tests}")


def render(d):
    # Canales
    ch_cards = ""
    for label, c in d["channels"]:
        p = pct(c["n"], d["total"]) if c["n"] > 0 else "—"
        sql = c.get("sql", 0)
        dim = "" if c["n"] > 0 else ";opacity:.45"
        ch_cards += (f'<div class="ch-card" style="--chc:{c["color"]}{dim}">'
                     f'<div class="ch-icon">{c["icon"]}</div>'
                     f'<div class="ch-num">{c["n"]}</div>'
                     f'<div class="ch-label">{esc(label)}</div>'
                     f'<div class="ch-pct">{p} del total</div>'
                     f'<div class="ch-sql">🎯 {sql} SQL</div></div>\n')

    # Revisión ventas
    rev_blocks = ""
    for key, color in REV_META:
        n = d["rev_counts"].get(key, 0)
        dim = "" if n > 0 else ";opacity:.4"
        bd = d.get("rev_lc", {}).get(key, {})
        parts = []
        if bd.get("lead"): parts.append(f'{bd["lead"]} lead')
        if bd.get("sql"):  parts.append(f'{bd["sql"]} SQL')
        if bd.get("free"): parts.append(f'{bd["free"]} freem')
        desc = f'<div class="rb-desc">{" · ".join(parts)}</div>' if (n > 0 and parts) else ''
        rev_blocks += (f'<div class="rev-block" style="--rbc:{color}{dim}">'
                       f'<div class="rb-num">{n}</div>'
                       f'<div class="rb-name">{esc(key)}</div>{desc}</div>\n')

    # Etapa del ciclo de vida (solo etapas con contactos)
    lc_blocks = ""
    known = {m[0] for m in LC_META if m[0] != "other"}
    other_n = sum(n for k, n in d["lc_counts"].items() if k and k not in known)
    for value, label, color in LC_META:
        n = other_n if value == "other" else d["lc_counts"].get(value, 0)
        if n == 0:
            continue
        lc_blocks += (f'<div class="rev-block" style="--rbc:{color}">'
                      f'<div class="rb-num">{n}</div>'
                      f'<div class="rb-name">{esc(label)}</div></div>\n')
    if not lc_blocks:
        lc_blocks = '<div class="rb-desc" style="color:var(--muted)">Sin datos de ciclo de vida</div>'

    # Tabla llamadas
    if d["sql_rows"]:
        call_rows = ""
        for r in d["sql_rows"]:
            emp = esc(r["company"]) if r["company"] else "—"
            call_rows += (f'<tr><td><strong>{esc(r["name"])}</strong></td>'
                          f'<td>{emp} · <em>{esc(r["channel"])}</em></td>'
                          f'<td><span class="pill pill-demo">{esc(r["state"])}</span></td></tr>')
    else:
        call_rows = '<tr><td colspan="3" style="color:var(--muted)">Sin SQL-Consultoría en el período</td></tr>'

    # Pipeline
    by_stage = {}
    for deal in d["mkt_deals"]:
        by_stage.setdefault(deal["stage"], []).append(deal)
    deal_rows = ""
    for st_id, label, pill in STAGE_LABELS:
        group = by_stage.get(st_id, [])
        if not group:
            continue
        group = sorted(group, key=lambda x: x["channel"])  # agrupar por canal dentro de la etapa
        deal_rows += f'<tr class="stage-divider"><td colspan="3">{esc(label)} · {len(group)} deals</td></tr>'
        for deal in group:
            new_tag = ' <span class="new-tag">NUEVO</span>' if deal["id"] in d["nuevos_ids"] else ""
            deal_rows += (f'<tr data-name="{esc(deal["name"].lower())}">'
                          f'<td><strong>{esc(deal["name"])}</strong>{new_tag}</td>'
                          f'<td>{esc(deal["channel"])}</td>'
                          f'<td><span class="pill {pill}">{esc(label)}</span></td></tr>')
    chan_dist_txt = " · ".join(f"{n} {esc(lbl)}" for lbl, n in
                               sorted(d["chan_dist"].items(), key=lambda x: -x[1])) or "—"

    cs = d["calls_summary"]

    # Embudo(s): informe mensual separa comercial y producto/freemium; el diario mantiene el embudo único.
    if d["is_monthly"]:
        funnel_section = f"""  <div class="section-label">Embudo comercial · {esc(d["periodo_txt"])}</div>
  <div class="funnel funnel-row">
    <div class="f-card f-c-default">
      <div class="fc-label">Contactos creados</div>
      <div class="fc-value">{d["total"]}</div>
      <div class="fc-sub">Total del período</div>
    </div>
    <div class="f-arrow"></div>
    <div class="f-card f-c-default">
      <div class="fc-label">Leads</div>
      <div class="fc-value">{d["n_lead"]}</div>
      <div class="fc-sub">{d["pct_lead"]} del total de contactos</div>
    </div>
    <div class="f-arrow"></div>
    <div class="f-card f-c-orange">
      <div class="fc-label">SQL Consultoría Demo</div>
      <div class="fc-value">{d["n_sql"]}</div>
      <div class="fc-sub">{d["pct_sql"]} del total de contactos</div>
    </div>
    <div class="f-arrow"></div>
    <div class="f-card f-c-green">
      <div class="fc-label">Reuniones agendadas</div>
      <div class="fc-value">{d["n_meetings"]}</div>
      <div class="fc-sub">de canales de marketing</div>
    </div>
    <div class="f-arrow"></div>
    <div class="f-card f-c-purple">
      <div class="fc-label">Oportunidades</div>
      <div class="fc-value">{d["n_opps_generated"]}</div>
      <div class="fc-sub">de canales de marketing</div>
      <div class="fc-opp-total">{d["opps_generated_companies"]}</div>
    </div>
    <div class="f-arrow"></div>
    <div class="f-card f-c-green">
      <div class="fc-label">Clientes</div>
      <div class="fc-value">{d["n_clients_generated"]}</div>
      <div class="fc-sub">de canales de marketing</div>
      <div class="fc-opp-total">{d["clients_generated_companies"]}</div>
    </div>
  </div>

  <div class="section-label" style="margin-top:20px;">
    <span class="funnel-row-label" style="text-transform:none;letter-spacing:normal;font-size:12px;">
      Embudo de producto · Freemium
      <span class="badge badge-amber">🧪 En definición</span>
    </span>
  </div>
  <div class="funnel funnel-row">
    <div class="f-card f-c-default">
      <div class="fc-label">Contactos creados</div>
      <div class="fc-value">{d["total"]}</div>
      <div class="fc-sub">Total del período</div>
    </div>
    <div class="f-arrow"></div>
    <div class="f-card f-c-default">
      <div class="fc-label">Leads</div>
      <div class="fc-value">{d["n_lead"]}</div>
      <div class="fc-sub">{d["pct_lead"]} del total de contactos</div>
    </div>
    <div class="f-arrow"></div>
    <div class="f-card f-c-default">
      <div class="fc-label">Freemium</div>
      <div class="fc-value">{d["n_free"]}</div>
      <div class="fc-sub">{d["pct_free"]} del total de contactos</div>
    </div>
  </div>
  <div class="alert alert-muted" style="margin-top:10px;margin-bottom:0;">
    <span>ℹ️</span>
    <div>El proceso de producto/freemium está en definición: en cuanto haya oportunidades, reuniones o clientes que vengan del uso freemium, se añadirán como pasos adicionales de este embudo.</div>
  </div>"""
    else:
        funnel_section = f"""  <div class="section-label">Embudo de conversión · {esc(d["periodo_txt"])}</div>
  <div class="funnel">
    <div class="f-card f-c-default">
      <div class="fc-label">Contactos creados</div>
      <div class="fc-value">{d["total"]}</div>
      <div class="fc-sub">Total del período</div>
    </div>
    <div class="f-arrow"></div>
    <div class="f-card f-c-default">
      <div class="fc-label">Leads</div>
      <div class="fc-value">{d["n_lead"]}</div>
      <div class="fc-sub">{d["pct_lead"]} del total de contactos</div>
    </div>
    <div class="f-arrow"></div>
    <div class="f-card f-c-orange">
      <div class="fc-label">SQL Consultoría</div>
      <div class="fc-value">{d["n_sql"]}</div>
      <div class="fc-sub">{d["pct_sql"]} del total de contactos</div>
    </div>
    <div class="f-arrow"></div>
    <div class="f-card f-c-default">
      <div class="fc-label">Freemium</div>
      <div class="fc-value">{d["n_free"]}</div>
      <div class="fc-sub">{d["pct_free"]} del total de contactos</div>
    </div>
    <div class="f-arrow"></div>
    <div class="f-card f-c-green">
      <div class="fc-label">Reuniones agendadas</div>
      <div class="fc-value">{d["n_meetings"]}</div>
      <div class="fc-sub">de canales de marketing</div>
      <div class="fc-opp-total">{d["meeting_companies"]}</div>
    </div>
    <div class="f-arrow"></div>
    <div class="f-card f-c-purple">
      <div class="fc-label">Oportunidades generadas</div>
      <div class="fc-value">{d["n_opps_generated"]}</div>
      <div class="fc-sub">de canales de marketing</div>
      <div class="fc-opp-total">{d["opps_generated_companies"]}</div>
    </div>
  </div>"""

    if d["is_monthly"]:
        calls_section = ""
    else:
        calls_section = f"""  <div class="flow-arrow">↓<small>A cada SQL se le llama por teléfono → estado de las llamadas</small></div>

  <div class="section-label">Llamadas y previsión · seguimiento comercial</div>
  <div class="card" style="padding:16px 20px;">
    <div class="rev-blocks">
      <div class="rev-block" style="--rbc:var(--green)"><div class="rb-num">{cs["total"]}</div><div class="rb-name">Llamadas registradas</div><div class="rb-desc">{cs["completed"]} completadas · HubSpot Calls</div></div>
      <div class="rev-block" style="--rbc:var(--amber)"><div class="rb-num">{d["n_sql_pendientes"]}</div><div class="rb-name">Previsión de llamadas</div><div class="rb-desc">SQL pendientes de contactar · de {len(d["sql_rows"])} del período</div></div>
    </div>
  </div>

  <div class="section-label">Llamadas y seguimiento comercial · aprendizajes para marketing</div>
  <div class="card">
    <div class="card-header">
      <span class="card-title">SQL Consultoría del período · empresa, canal y estado</span>
      <span class="badge badge-green">📞 Seguimiento comercial</span>
    </div>
    <table class="table">
      <thead><tr><th>SQL</th><th>Empresa · canal</th><th>Estado SQL</th></tr></thead>
      <tbody>{call_rows}</tbody>
    </table>
    <div class="alert alert-muted" style="margin-top:14px;margin-bottom:0;align-items:flex-start;">
      <span>💡</span>
      <div><strong style="color:var(--guru-300);">Aprendizajes para marketing:</strong>
      <br>• <strong>Brand = intención alta</strong>: los SQL de campaña de marca avanzan rápido a oportunidad/demo.
      <br>• <strong>PMAX / genérico = menor calidad</strong>: más volumen pero peor cualificación → revisar segmentación y creatividades.
      <br>• <strong>Campañas por industria/agentes</strong>: traen volumen de SQL; medir su conversión a demo.
      <br>• <strong>SLA de ventas</strong>: llamada en los primeros 15 min cuando hay teléfono.
      <br><span style="color:var(--muted);font-size:11px;">Estado tomado de la propiedad «Estado SQL Consultoría» de HubSpot. Llamadas registradas vía HubSpot Calls (no vinculadas 1:1 a cada SQL aún).</span></div>
    </div>
  </div>"""

    return TEMPLATE.format(
        title=esc(d["title"]),
        fecha_larga=esc(d["fecha_larga"]), periodo_txt=esc(d["periodo_txt"]),
        total=d["total"], n_lead=d["n_lead"], pct_lead=d["pct_lead"],
        n_sql=d["n_sql"], pct_sql=d["pct_sql"], n_free=d["n_free"], pct_free=d["pct_free"],
        n_meetings=d["n_meetings"], meeting_companies=d["meeting_companies"],
        n_opps_generated=d["n_opps_generated"], opps_generated_companies=d["opps_generated_companies"],
        ch_cards=ch_cards, rev_blocks=rev_blocks, lc_blocks=lc_blocks,
        call_rows=call_rows, deal_rows=deal_rows,
        mkt_total=len(d["mkt_deals"]), nuevos_deals=d["nuevos_deals"],
        demos_pipeline=d["demos_pipeline"], chan_dist_txt=chan_dist_txt,
        n_calls=cs["total"], n_calls_completed=cs["completed"],
        n_sql_pendientes=d["n_sql_pendientes"], n_sql_total=len(d["sql_rows"]),
        funnel_section=funnel_section, calls_section=calls_section,
        generado=esc(d["generado"]),
    )


TEMPLATE = r"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<style>
:root {{
  --guru-900:#0a0618; --guru-800:#110e2a; --guru-500:#FF6B5B; --guru-400:#E55A4C; --guru-300:#FAE5DC;
  --surface:#161330; --card:#1e1b42; --border:#2e2a5a;
  --green:#10b981; --amber:#f59e0b; --red:#ef4444; --blue:#3b82f6; --orange:#f97316;
  --text:#f0edff; --text-2:#c4bfe0; --muted:#7b76a0;
}}
*,*::before,*::after {{ box-sizing:border-box; margin:0; padding:0; }}
html {{ scroll-behavior:smooth; font-size:15px; }}
body {{ background:var(--guru-900); color:var(--text); font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','Inter',sans-serif; line-height:1.5; min-height:100vh; }}

.header {{ position:sticky; top:0; z-index:100; background:rgba(17,14,42,.96); backdrop-filter:blur(16px); border-bottom:1px solid var(--border); padding:0 24px; }}
.header-inner {{ display:flex; align-items:center; gap:16px; padding:14px 0 12px; flex-wrap:wrap; }}
.logo-box {{ width:40px; height:40px; background:linear-gradient(135deg,var(--guru-500),var(--guru-400)); border-radius:10px; display:flex; align-items:center; justify-content:center; font-weight:800; font-size:15px; color:#fff; flex-shrink:0; box-shadow:0 0 16px rgba(255,107,91,.4); }}
.header-title {{ flex:1; min-width:180px; }}
.header-title h1 {{ font-size:16px; font-weight:700; color:var(--text); }}
.header-title p {{ font-size:12px; color:var(--muted); }}
.live-badge {{ background:rgba(16,185,129,.12); border:1px solid rgba(16,185,129,.3); color:var(--green); font-size:11px; font-weight:600; padding:4px 10px; border-radius:20px; display:flex; align-items:center; gap:5px; white-space:nowrap; }}
.live-dot {{ width:6px; height:6px; border-radius:50%; background:var(--green); animation:pulse 2s infinite; }}
@keyframes pulse {{ 0%,100%{{opacity:1}} 50%{{opacity:.3}} }}
.sync-bar {{ font-size:11px; color:var(--muted); padding:5px 24px 6px; border-top:1px solid rgba(46,42,90,.6); background:rgba(17,14,42,.7); }}

.main {{ max-width:1160px; margin:0 auto; padding:24px 20px 60px; }}
.section-label {{ font-size:11px; font-weight:700; letter-spacing:.1em; text-transform:uppercase; color:var(--muted); margin:32px 0 14px; }}
.section-label:first-child {{ margin-top:0; }}

.funnel {{ display:flex; align-items:stretch; gap:0; }}
.f-arrow {{ display:flex; align-items:center; justify-content:center; width:34px; flex-shrink:0; font-size:30px; opacity:.8; }}
.f-arrow::after {{ content:'›'; color:var(--guru-400); font-weight:700; }}
.f-card {{ flex:1; background:var(--card); border:1px solid var(--border); border-radius:10px; padding:16px 16px 14px; position:relative; overflow:hidden; min-width:0; display:flex; flex-direction:column; gap:4px; }}
.f-card::before {{ content:''; position:absolute; top:0; left:0; right:0; height:3px; background:var(--fc,var(--guru-500)); border-radius:10px 10px 0 0; }}
.fc-label {{ font-size:11px; color:var(--muted); font-weight:700; text-transform:uppercase; letter-spacing:.07em; }}
.fc-value {{ font-size:48px; font-weight:800; line-height:1; color:var(--fv,var(--text)); margin-top:4px; }}
.fc-sub {{ font-size:13px; color:var(--text-2); font-weight:600; margin-top:6px; }}
.fc-opp-total {{ font-size:12px; color:var(--muted); margin-top:8px; padding-top:8px; border-top:1px solid var(--border); }}
.fc-opp-total strong {{ color:var(--text-2); }}
.f-c-default {{ --fc:var(--guru-500); --fv:var(--text); }}
.f-c-orange {{ --fc:var(--orange); --fv:var(--orange); }}
.f-c-green {{ --fc:var(--green); --fv:var(--green); }}
.f-c-purple {{ --fc:#a78bfa; --fv:#a78bfa; }}

.channels-grid {{ display:grid; grid-template-columns:repeat(7,1fr); gap:10px; }}
@media(max-width:900px){{ .channels-grid {{ grid-template-columns:repeat(3,1fr); }} }}
@media(max-width:550px){{ .channels-grid {{ grid-template-columns:repeat(2,1fr); }} }}
.ch-card {{ background:var(--card); border:1px solid var(--border); border-radius:10px; padding:14px 14px 12px; position:relative; overflow:hidden; }}
.ch-card::before {{ content:''; position:absolute; top:0; left:0; right:0; height:3px; background:var(--chc,var(--guru-500)); border-radius:10px 10px 0 0; }}
.ch-icon {{ font-size:18px; margin-bottom:6px; }}
.ch-num {{ font-size:30px; font-weight:800; line-height:1; color:var(--chc,var(--text)); }}
.ch-label {{ font-size:11px; font-weight:600; color:var(--text-2); margin-top:4px; }}
.ch-pct {{ font-size:11px; color:var(--muted); margin-top:2px; }}
.ch-sql {{ font-size:12px; font-weight:800; color:var(--orange); margin-top:5px; }}

.rev-blocks {{ display:flex; gap:10px; flex-wrap:wrap; }}
.rev-block {{ flex:1; min-width:130px; background:rgba(255,255,255,.03); border:1px solid var(--border); border-radius:10px; padding:16px 16px 14px; position:relative; overflow:hidden; }}
.rev-block::before {{ content:''; position:absolute; top:0; left:0; right:0; height:3px; background:var(--rbc,var(--border)); border-radius:10px 10px 0 0; }}
.rb-num {{ font-size:26px; font-weight:800; line-height:1; color:var(--rbc,var(--muted)); margin-bottom:6px; }}
.rb-name {{ font-size:12px; font-weight:600; color:var(--rbc,var(--muted)); }}
.rb-desc {{ font-size:11px; color:var(--muted); margin-top:3px; }}

.card {{ background:var(--card); border:1px solid var(--border); border-radius:12px; padding:20px 22px; margin-bottom:12px; }}
.card-header {{ display:flex; align-items:center; justify-content:space-between; margin-bottom:16px; }}
.card-title {{ font-size:14px; font-weight:700; color:var(--text); }}
.badge {{ font-size:11px; font-weight:700; padding:3px 10px; border-radius:20px; letter-spacing:.04em; }}
.badge-green {{ background:rgba(16,185,129,.15); color:var(--green); border:1px solid rgba(16,185,129,.3); }}
.badge-amber {{ background:rgba(245,158,11,.15); color:var(--amber); border:1px solid rgba(245,158,11,.3); }}
.funnel-row {{ margin-bottom:10px; }}
.funnel-row-label {{ font-size:12px; font-weight:700; color:var(--text-2); margin-bottom:10px; display:flex; align-items:center; gap:8px; }}
.table {{ width:100%; border-collapse:collapse; }}
.table th {{ font-size:11px; font-weight:700; color:var(--muted); text-transform:uppercase; letter-spacing:.06em; padding:0 12px 10px 0; text-align:left; border-bottom:1px solid var(--border); }}
.table td {{ font-size:13px; color:var(--text-2); padding:10px 12px 10px 0; border-bottom:1px solid rgba(46,42,90,.5); vertical-align:middle; }}
.table tr:last-child td {{ border-bottom:none; }}
.table td strong {{ color:var(--text); font-weight:600; }}
.table tr.stage-divider td {{ background:rgba(255,255,255,.03); font-size:10px; font-weight:700; letter-spacing:.08em; text-transform:uppercase; color:var(--muted); padding:6px 0; border-bottom:1px solid var(--border); }}
.pill {{ display:inline-block; font-size:11px; font-weight:600; padding:3px 9px; border-radius:20px; white-space:nowrap; }}
.pill-demo {{ background:rgba(16,185,129,.15); color:var(--green); }}
.pill-discov {{ background:rgba(255,107,91,.15); color:#F5D5C8; }}
.pill-best {{ background:rgba(245,158,11,.15); color:var(--amber); }}
.new-tag {{ font-size:10px; font-weight:700; padding:2px 7px; border-radius:10px; background:rgba(16,185,129,.2); color:var(--green); letter-spacing:.04em; text-transform:uppercase; }}

.alert {{ border-radius:8px; padding:10px 14px; font-size:12px; margin-bottom:14px; display:flex; align-items:flex-start; gap:8px; }}
.alert-green {{ background:rgba(16,185,129,.06); border:1px solid rgba(16,185,129,.2); color:#6ee7b7; }}
.alert-muted {{ background:rgba(123,118,160,.06); border:1px solid rgba(123,118,160,.2); color:var(--muted); }}

.flow-arrow {{ text-align:center; margin:2px 0 14px; color:var(--guru-400); font-size:26px; line-height:1; }}
.flow-arrow small {{ display:block; font-size:11px; color:var(--muted); font-weight:600; margin-top:3px; }}

@media(max-width:600px){{
  .header {{ padding:0 14px; }}
  .header-inner {{ gap:10px; padding:12px 0 10px; }}
  .header-title {{ min-width:0; }}
  .header-title h1 {{ font-size:14px; line-height:1.25; }}
  .header-title p {{ font-size:10px; line-height:1.35; }}
  .logo-box {{ width:34px; height:34px; font-size:13px; }}
  .live-badge {{ display:none; }}
  .sync-bar {{ padding:5px 14px 6px; }}
  .main {{ padding:18px 14px 50px; }}
  .funnel {{ flex-direction:column; gap:8px; }}
  .f-arrow {{ width:100%; height:20px; transform:rotate(90deg); }}
  .f-card {{ padding:14px 16px 13px; }}
  .fc-value {{ font-size:40px; }}
  .fc-opp-total {{ font-size:13px; }}
  .rev-block {{ flex:1 1 calc(50% - 5px); min-width:calc(50% - 5px); }}
  .rb-num {{ font-size:23px; }}
  .flow-arrow {{ font-size:24px; margin:2px 0 12px; }}
  .flow-arrow small {{ font-size:10px; padding:0 8px; }}
  .alert {{ padding:10px 12px; font-size:12px; line-height:1.5; }}
  #emp-search {{ font-size:16px; }}
  .card {{ padding:16px 14px; overflow-x:auto; }}
  .card-header {{ flex-wrap:wrap; gap:8px; }}
  .table {{ min-width:300px; }}
  .section-label {{ font-size:10px; margin-top:26px; }}
}}
@media(max-width:380px){{
  .channels-grid {{ grid-template-columns:1fr; }}
  .rev-block {{ flex:1 1 100%; min-width:100%; }}
  .fc-value {{ font-size:36px; }}
}}

#gs-gate {{ position:fixed; inset:0; z-index:9999; background:#0a0618; display:flex; align-items:center; justify-content:center; }}
#gs-gate .box {{ background:#1e1b42; border:1px solid #2e2a5a; border-radius:16px; padding:40px 36px; width:340px; text-align:center; }}
#gs-gate .logo {{ width:48px; height:48px; border-radius:12px; margin:0 auto 20px; background:linear-gradient(135deg,#ff6b5b,#ff8b7d); display:flex; align-items:center; justify-content:center; font-weight:800; font-size:17px; color:#fff; }}
#gs-gate h2 {{ font-size:18px; font-weight:700; color:#f0edff; margin-bottom:4px; }}
#gs-gate p {{ font-size:13px; color:#7b76a0; margin-bottom:24px; }}
#gs-gate input {{ width:100%; padding:11px 14px; border-radius:8px; border:1px solid #2e2a5a; background:#161330; color:#f0edff; font-size:15px; margin-bottom:12px; outline:none; letter-spacing:.08em; }}
#gs-gate input:focus {{ border-color:#ff6b5b; }}
#gs-gate button {{ width:100%; padding:11px; border-radius:8px; border:none; cursor:pointer; background:linear-gradient(135deg,#ff6b5b,#ff8b7d); color:#fff; font-size:15px; font-weight:700; }}
#gs-gate .err {{ color:#ef4444; font-size:12px; margin-top:8px; display:none; }}
</style>
<script>
(function(){{
  if(sessionStorage.getItem('gs_ok')==='1') return;
  document.addEventListener('DOMContentLoaded', function(){{
    var gate=document.getElementById('gs-gate'), inp=document.getElementById('gs-pwd'),
        err=document.getElementById('gs-err'), btn=document.getElementById('gs-btn');
    gate.style.display='flex';
    function check(){{ if(inp.value==='radar2026'){{ sessionStorage.setItem('gs_ok','1'); gate.style.display='none'; }}
      else {{ err.style.display='block'; inp.value=''; inp.focus(); }} }}
    btn.addEventListener('click', check);
    inp.addEventListener('keydown', function(e){{ if(e.key==='Enter') check(); }});
  }});
}})();
</script>
</head>
<body>

<div id="gs-gate" style="display:none">
  <div class="box">
    <div class="logo">GS</div>
    <h2>GuruSup · Dashboard Diario</h2>
    <p>Acceso restringido</p>
    <input id="gs-pwd" type="password" placeholder="Contraseña" autofocus>
    <button id="gs-btn">Entrar</button>
    <div id="gs-err" class="err">Contraseña incorrecta</div>
  </div>
</div>

<div class="header">
  <div class="header-inner">
    <div class="logo-box">GS</div>
    <div class="header-title">
      <h1>{title}</h1>
      <p>{fecha_larga} · {periodo_txt}</p>
    </div>
    <span class="live-badge"><span class="live-dot"></span>Live · HubSpot</span>
  </div>
  <div class="sync-bar">Datos del período · generado el {generado}</div>
</div>

<div class="main">

{funnel_section}

  <div class="section-label">Canales de adquisición · {total} contactos</div>
  <div class="channels-grid">{ch_cards}</div>

  <div class="section-label">Leads en revisión de ventas · {total} contactos</div>
  <div class="card" style="padding:16px 20px;">
    <div class="alert alert-green" style="margin:0 0 12px;align-items:flex-start;">
      <span>🎯</span>
      <div>
        <strong style="color:var(--guru-300);">La prioridad de revisión son los SQL Consultoría</strong> —contactos que han <strong>pedido una demo</strong>. Orden de prioridad de ventas:
        <br>• <strong style="color:var(--text-2);">Máxima prioridad: SQL de Paid</strong> — pagamos por ellos y traen intención, pero el coste es alto, así que hay que <strong>sacar conclusiones para optimizar las campañas</strong>.
        <br>• <strong style="color:var(--text-2);">Siguiente prioridad: SQL del resto de canales</strong> (siempre que sean SQL).
        <br>• Cuando haya <strong>teléfono de contacto, se les llama en los primeros 15 minutos</strong>.
      </div>
    </div>
    <div style="font-size:12px;color:var(--text);opacity:.85;padding:2px 4px 12px;line-height:1.55;">
      ℹ️ Los <strong>freemium y leads</strong> no se tratan de forma directa: se gestionan por <strong>automatizaciones</strong> y tienen menor prioridad para ventas.
    </div>
    <div class="rev-blocks">{rev_blocks}</div>
  </div>

{calls_section}

  <div class="section-label">Oportunidades activas · Pipeline de ventas · solo canales de marketing</div>
  <div class="card">
    <div class="card-header">
      <span class="card-title">Empresas en pipeline · por canal de marketing y etapa</span>
      <span class="badge badge-green">{mkt_total} oportunidades de marketing</span>
    </div>
    <input type="text" id="emp-search" onkeyup="filtrarEmpresas()" placeholder="🔍 Buscar empresa…"
      style="width:100%;padding:10px 14px;border-radius:8px;border:1px solid var(--border);background:var(--surface);color:var(--text);font-size:14px;margin-bottom:14px;outline:none;">
    <table class="table" id="emp-table">
      <thead><tr><th>Empresa</th><th>Canal</th><th>Etapa</th></tr></thead>
      <tbody>{deal_rows}</tbody>
    </table>
    <div id="emp-empty" style="display:none;padding:14px 0;font-size:13px;color:var(--muted);text-align:center;">Sin resultados</div>
    <div class="rev-blocks" style="margin-top:16px;">
      <div class="rev-block" style="--rbc:var(--guru-300)"><div class="rb-num">{mkt_total}</div><div class="rb-name">Oportunidades en pipeline</div><div class="rb-desc">Solo canales de marketing</div></div>
      <div class="rev-block" style="--rbc:var(--green)"><div class="rb-num">{demos_pipeline}</div><div class="rb-name">En demo / reunión</div><div class="rb-desc">Etapa presentación</div></div>
      <div class="rev-block" style="--rbc:var(--amber)"><div class="rb-num">{nuevos_deals}</div><div class="rb-name">Nuevas oportunidades</div><div class="rb-desc">Creadas en el período</div></div>
    </div>
    <div class="alert alert-muted" style="margin-top:14px;margin-bottom:0;align-items:flex-start;">
      <span>ℹ️</span>
      <div>Solo oportunidades cuyo contacto entró por un <strong>canal de marketing</strong> (Paid Search/Social, SEO, directo, social orgánico, referencias, chat web o eventos). Se excluyen deals de extensión de Sales, integraciones, alta manual e importación. Reparto por canal: {chan_dist_txt}.</div>
    </div>
  </div>

  <div style="margin-top:40px; text-align:center; font-size:12px; color:var(--muted);">
    GuruSup · Dashboard Diario · generado el {generado} (hora España)
  </div>

</div>
<script>
(function(){{
  window.filtrarEmpresas=function(){{
    var q=document.getElementById('emp-search').value.toLowerCase().trim();
    var rows=document.querySelectorAll('#emp-table tbody tr:not(.stage-divider)');
    var visibles=0;
    rows.forEach(function(r){{
      var name=r.querySelector('td strong');
      var match=name && name.textContent.toLowerCase().indexOf(q)!==-1;
      r.style.display=(!q||match)?'':'none';
      if(!q||match) visibles++;
    }});
    document.querySelectorAll('#emp-table tbody tr.stage-divider').forEach(function(div){{
      var next=div.nextElementSibling, has=false;
      while(next && !next.classList.contains('stage-divider')){{
        if(next.style.display!=='none') has=true;
        next=next.nextElementSibling;
      }}
      div.style.display=(has||!q)?'':'none';
    }});
    var empty=document.getElementById('emp-empty');
    if(empty) empty.style.display=visibles===0?'block':'none';
  }};
}})();
</script>
</body>
</html>"""


if __name__ == "__main__":
    main()
