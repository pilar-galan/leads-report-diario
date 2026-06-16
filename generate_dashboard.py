#!/usr/bin/env python3
"""
Genera dashboard_diario.html con datos reales de HubSpot.

Variables de entorno necesarias:
  HUBSPOT_TOKEN  -> token de una Private App de HubSpot con scopes:
                    crm.objects.contacts.read, crm.objects.deals.read

Ventana del informe (hora España):
  - Lunes: cubre desde el viernes (incluye sábado y domingo)
  - Resto: últimas 24h (desde el día hábil anterior)
"""
import os
import sys
import json
import urllib.request
import urllib.error
from datetime import datetime, timedelta, timezone

TOKEN = os.environ.get("HUBSPOT_TOKEN", "")
BASE = "https://api.hubapi.com"

MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
         "agosto", "septiembre", "octubre", "noviembre", "diciembre"]
DIAS = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]

# ── Pipeline de ventas (default) ──
DEALSTAGE_LABELS = {
    "1107496610": "Discovery",
    "presentationscheduled": "Needs Validation",
    "1033589123": "Best Case",
    "1119432966": "Close Won & Onboarding",
}
DISCOVERY_STAGE = "1107496610"

# ── Canales de adquisición (hs_analytics_source) ──
SOURCE_META = [
    ("ORGANIC_SEARCH", "SEO Orgánico", "🌿", "#10b981"),
    ("PAID_SEARCH",    "SEM / Google Ads", "🔍", "#4285F4"),
    ("DIRECT_TRAFFIC", "Tráfico directo", "🔗", "#94a3b8"),
    ("REFERRALS",      "Referido", "🤝", "#f97316"),
    ("SOCIAL_MEDIA",   "Social Media", "📱", "#ec4899"),
    ("OFFLINE",        "Offline", "🏢", "#a78bfa"),
]

# ── Estados de revisión ventas ──
REV_META = [
    ("Ya gestionado", "Ya gestionado", "Proceso completado", "var(--green)"),
    ("Pendiente de revisión", "Pendiente revisión", "Sin asignar aún", "var(--amber)"),
    ("En revisión", "En revisión activa", "En proceso ahora", "var(--blue)"),
    ("Aceptado para gestión comercial", "Aceptado gestión", "Listo para comercial", "var(--orange)"),
    ("Duplicado", "Duplicado", "Ya existía en BBDD", "var(--guru-400)"),
    ("No aplica / Descartado", "No aplica / Desc.", "Sin potencial", "var(--red)"),
    ("Test", "Test", "Cuenta de prueba", "var(--muted)"),
]


def api_post(path, payload):
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {TOKEN}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def search(object_type, filters, properties, limit=1):
    """Devuelve el total de objetos que cumplen los filtros (y la primera página)."""
    payload = {
        "filterGroups": [{"filters": filters}],
        "properties": properties,
        "limit": limit,
    }
    return api_post(f"/crm/v3/objects/{object_type}/search", payload)


def count(object_type, filters):
    return search(object_type, filters, ["hs_object_id"], limit=1).get("total", 0)


def count_all_pages(object_type, filters, properties):
    """Recupera todos los registros paginando (para agrupar en cliente)."""
    results, after = [], None
    while True:
        payload = {
            "filterGroups": [{"filters": filters}],
            "properties": properties,
            "limit": 100,
        }
        if after:
            payload["after"] = after
        data = api_post(f"/crm/v3/objects/{object_type}/search", payload)
        results.extend(data.get("results", []))
        paging = data.get("paging", {}).get("next", {})
        after = paging.get("after")
        if not after:
            break
    return results


def iso(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def main():
    if not TOKEN:
        print("ERROR: falta HUBSPOT_TOKEN", file=sys.stderr)
        sys.exit(1)

    # Hora España (UTC+2 verano).
    now = datetime.now(timezone.utc) + timedelta(hours=2)
    es_now = now.replace(tzinfo=timezone(timedelta(hours=2)))

    # Ventana: lunes cubre fin de semana (3 días atrás), resto 1 día
    days_back = 3 if es_now.weekday() == 0 else 1
    start = es_now - timedelta(days=days_back)
    start_iso = iso(start)
    end_iso = iso(es_now)

    fecha_larga = f"{DIAS[es_now.weekday()]}, {es_now.day} de {MESES[es_now.month-1]} de {es_now.year}"
    periodo_txt = (f"{start.day} {MESES[start.month-1][:3]} → {es_now.day} {MESES[es_now.month-1][:3]} "
                   f"(hora España)")
    if es_now.weekday() == 0:
        periodo_txt += " · incluye fin de semana"

    win = [
        {"propertyName": "createdate", "operator": "BETWEEN", "value": start_iso, "highValue": end_iso},
    ]
    # Excluir cuentas internas @gurusup.com
    not_internal = {"propertyName": "email", "operator": "NOT_CONTAINS_TOKEN", "value": "gurusup.com"}

    # ── EMBUDO ──
    contactos_creados = count("contacts", win + [not_internal])

    mql = count("contacts", win + [not_internal, {
        "propertyName": "lifecyclestage", "operator": "IN",
        "values": ["marketingqualifiedlead", "salesqualifiedlead", "1378463825",
                   "opportunity", "customer"]}])

    sql_freemium = count("contacts", win + [not_internal, {
        "propertyName": "lifecyclestage", "operator": "EQ", "value": "1378463825"}])
    sql_consultoria = count("contacts", win + [not_internal, {
        "propertyName": "lifecyclestage", "operator": "EQ", "value": "salesqualifiedlead"}])
    sql_total = sql_freemium + sql_consultoria

    # ── REVISIÓN VENTAS ──
    rev_contacts = count_all_pages("contacts", win + [not_internal], ["revision_ventas"])
    rev_counts = {}
    for c in rev_contacts:
        v = c["properties"].get("revision_ventas")
        if v:
            rev_counts[v] = rev_counts.get(v, 0) + 1

    # ── CANALES ──
    src_contacts = count_all_pages("contacts", win + [not_internal], ["hs_analytics_source"])
    src_counts = {}
    for c in src_contacts:
        v = c["properties"].get("hs_analytics_source")
        if v:
            src_counts[v] = src_counts.get(v, 0) + 1
    total_src = sum(src_counts.values()) or 1

    # ── DEALS (pipeline ventas, sin ruido de signups con email en el nombre) ──
    deal_filters = [
        {"propertyName": "pipeline", "operator": "EQ", "value": "default"},
        {"propertyName": "hs_is_closed", "operator": "EQ", "value": "false"},
        {"propertyName": "dealname", "operator": "NOT_CONTAINS_TOKEN", "value": "@"},
    ]
    deals = count_all_pages("deals", deal_filters, ["dealname", "dealstage", "createdate"])
    deals_activos = len(deals)
    deals_nuevos = [d for d in deals
                    if d["properties"].get("createdate", "") >= start_iso]

    # Deals cerrados perdidos en ventana, por razón
    lost_filters = [
        {"propertyName": "pipeline", "operator": "EQ", "value": "default"},
        {"propertyName": "hs_is_closed_lost", "operator": "EQ", "value": "true"},
        {"propertyName": "closedate", "operator": "BETWEEN", "value": start_iso, "highValue": end_iso},
    ]
    lost = count_all_pages("deals", lost_filters, ["dealname", "razon_de_perdida"])
    lost_counts = {}
    for d in lost:
        v = d["properties"].get("razon_de_perdida") or "Sin motivo especificado"
        lost_counts[v] = lost_counts.get(v, 0) + 1

    data = {
        "fecha_larga": fecha_larga,
        "periodo_txt": periodo_txt,
        "contactos_creados": contactos_creados,
        "mql": mql,
        "sql_total": sql_total,
        "sql_freemium": sql_freemium,
        "sql_consultoria": sql_consultoria,
        "deals_activos": deals_activos,
        "deals_nuevos": deals_nuevos,
        "deals": deals,
        "rev_counts": rev_counts,
        "src_counts": src_counts,
        "total_src": total_src,
        "lost_counts": lost_counts,
        "generado": es_now.strftime("%d %b %Y · %H:%M"),
    }
    html = render(data)
    with open("dashboard_diario.html", "w", encoding="utf-8") as f:
        f.write(html)
    print(f"OK · {contactos_creados} contactos · {sql_total} SQL · {deals_activos} deals activos")


def esc(t):
    return str(t).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def render(d):
    # Bloques de revisión ventas
    rev_blocks = ""
    for key, name, desc, color in REV_META:
        n = d["rev_counts"].get(key, 0)
        rev_blocks += f"""
      <div class="rev-block" style="--rbc:{color}">
        <div class="rb-num">{n}</div>
        <div class="rb-name">{name}</div>
        <div class="rb-desc">{desc}</div>
      </div>"""

    # Canales
    ch_cards = ""
    for src_key, label, icon, color in SOURCE_META:
        n = d["src_counts"].get(src_key, 0)
        pct = round(n / d["total_src"] * 100) if n else 0
        ch_cards += f"""
    <div class="ch-card" style="--chc:{color}"><div class="ch-icon">{icon}</div><div class="ch-num">{n}</div><div class="ch-label">{esc(label)}</div><div class="ch-pct">{pct}% del total</div></div>"""

    # Tabla de deals agrupada por etapa
    by_stage = {}
    for deal in d["deals"]:
        st = deal["properties"].get("dealstage", "")
        by_stage.setdefault(st, []).append(deal)
    nuevos_ids = {x["id"] for x in d["deals_nuevos"]}
    deal_rows = ""
    for st_id, label in DEALSTAGE_LABELS.items():
        group = by_stage.get(st_id, [])
        if not group:
            continue
        pill = "pill-discov" if st_id == DISCOVERY_STAGE else "pill-demo"
        deal_rows += f'<tr class="stage-divider"><td colspan="2">{esc(label)} — {len(group)} deals</td></tr>'
        for deal in group:
            name = esc(deal["properties"].get("dealname", "—"))
            tag = ' <span class="new-tag">NUEVO</span>' if deal["id"] in nuevos_ids else ""
            deal_rows += f'<tr><td><strong>{name}</strong>{tag}</td><td><span class="pill {pill}">{esc(label)}</span></td></tr>'

    # Razones de descarte deals
    if d["lost_counts"]:
        maxv = max(d["lost_counts"].values())
        lost_rows = ""
        for reason, n in sorted(d["lost_counts"].items(), key=lambda x: -x[1]):
            w = round(n / maxv * 100) if maxv else 0
            lost_rows += f"""
    <div class="reason-row">
      <div class="reason-label">{esc(reason)}</div>
      <div class="reason-bar-wrap"><div class="reason-bar" style="width:{w}%; background:var(--red)"></div></div>
      <div class="reason-count">{n}</div>
    </div>"""
        lost_alert = f'<div class="alert alert-muted">{sum(d["lost_counts"].values())} deals cerrados/perdidos en el período.</div>'
    else:
        lost_rows = """
    <div class="reason-row">
      <div class="reason-label">Sin deals perdidos en el período</div>
      <div class="reason-bar-wrap"><div class="reason-bar" style="width:0%"></div></div>
      <div class="reason-count">0</div>
    </div>"""
        lost_alert = '<div class="alert alert-muted">✓ Sin deals cerrados ni perdidos en este período.</div>'

    sql_breakdown = f"""
      <div class="fc-sql-breakdown">
        <div class="fc-sql-row"><span class="fc-sql-dot" style="background:var(--guru-400)"></span><span class="fc-sql-type">SQL-Freemium</span><span class="fc-sql-num">{d['sql_freemium']}</span></div>
        <div class="fc-sql-row"><span class="fc-sql-dot" style="background:var(--orange)"></span><span class="fc-sql-type">SQL-Consultoría</span><span class="fc-sql-num">{d['sql_consultoria']}</span></div>
      </div>"""

    return TEMPLATE.format(
        fecha_larga=esc(d["fecha_larga"]),
        periodo_txt=esc(d["periodo_txt"]),
        contactos=d["contactos_creados"],
        mql=d["mql"],
        sql_total=d["sql_total"],
        sql_breakdown=sql_breakdown,
        deals_nuevos=len(d["deals_nuevos"]),
        deals_activos=d["deals_activos"],
        rev_blocks=rev_blocks,
        ch_cards=ch_cards,
        deal_rows=deal_rows,
        lost_rows=lost_rows,
        lost_alert=lost_alert,
        generado=esc(d["generado"]),
    )


TEMPLATE = r"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>GuruSup · Dashboard Diario</title>
<style>
:root {{
  --guru-900:#0a0618;--guru-500:#7c3aed;--guru-400:#9d5ffa;--guru-300:#c4a2fc;
  --brand:#FF6B5B;--brand-2:#ff8f82;
  --surface:#161330;--card:#1e1b42;--border:#2e2a5a;--green:#10b981;--amber:#f59e0b;
  --red:#ef4444;--blue:#3b82f6;--orange:#f97316;--text:#f0edff;--text-2:#c4bfe0;--muted:#7b76a0;
}}
*,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
html{{font-size:15px}}
body{{background:var(--guru-900);color:var(--text);font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','Inter',sans-serif;line-height:1.5;min-height:100vh}}
.header{{position:sticky;top:0;z-index:100;background:rgba(17,14,42,.96);backdrop-filter:blur(16px);border-bottom:1px solid var(--border);padding:0 24px}}
.header-inner{{display:flex;align-items:center;gap:16px;padding:14px 0 12px;flex-wrap:wrap}}
.logo-box{{width:40px;height:40px;background:linear-gradient(135deg,var(--brand),var(--brand-2));border-radius:10px;display:flex;align-items:center;justify-content:center;font-weight:800;font-size:15px;color:#fff;flex-shrink:0;box-shadow:0 0 16px rgba(255,107,91,.4)}}
.header-title{{flex:1;min-width:180px}}
.header-title h1{{font-size:16px;font-weight:700}}
.header-title p{{font-size:12px;color:var(--muted)}}
.live-badge{{background:rgba(16,185,129,.12);border:1px solid rgba(16,185,129,.3);color:var(--green);font-size:11px;font-weight:600;padding:4px 10px;border-radius:20px;display:flex;align-items:center;gap:5px;white-space:nowrap}}
.live-dot{{width:6px;height:6px;border-radius:50%;background:var(--green);animation:pulse 2s infinite}}
@keyframes pulse{{0%,100%{{opacity:1}}50%{{opacity:.3}}}}
.main{{max-width:1160px;margin:0 auto;padding:24px 20px 60px}}
.section-label{{font-size:11px;font-weight:700;letter-spacing:.1em;text-transform:uppercase;color:var(--muted);margin-bottom:14px;margin-top:32px}}
.section-label:first-child{{margin-top:0}}
.channels-grid{{display:grid;grid-template-columns:repeat(6,1fr);gap:10px}}
@media(max-width:900px){{.channels-grid{{grid-template-columns:repeat(3,1fr)}}}}
@media(max-width:550px){{.channels-grid{{grid-template-columns:repeat(2,1fr)}}}}
.ch-card{{background:var(--card);border:1px solid var(--border);border-radius:10px;padding:14px 14px 12px;position:relative;overflow:hidden}}
.ch-card::before{{content:'';position:absolute;top:0;left:0;right:0;height:3px;background:var(--chc,var(--guru-500));border-radius:10px 10px 0 0}}
.ch-icon{{font-size:18px;margin-bottom:6px}}
.ch-num{{font-size:30px;font-weight:800;line-height:1;color:var(--chc,var(--text))}}
.ch-label{{font-size:11px;font-weight:600;color:var(--text-2);margin-top:4px}}
.ch-pct{{font-size:11px;color:var(--muted);margin-top:2px}}
.funnel{{display:flex;align-items:stretch;gap:0}}
.f-arrow{{display:flex;align-items:center;justify-content:center;width:28px;flex-shrink:0;font-size:18px;opacity:.5}}
.f-arrow::after{{content:'\203a';color:var(--muted)}}
.f-card{{flex:1;background:var(--card);border:1px solid var(--border);border-radius:10px;padding:16px 16px 14px;position:relative;overflow:hidden;min-width:0;display:flex;flex-direction:column;gap:4px}}
.f-card::before{{content:'';position:absolute;top:0;left:0;right:0;height:3px;background:var(--fc,var(--guru-500));border-radius:10px 10px 0 0}}
.fc-label{{font-size:10px;color:var(--muted);font-weight:700;text-transform:uppercase;letter-spacing:.07em}}
.fc-value{{font-size:30px;font-weight:800;line-height:1;color:var(--fv,var(--text))}}
.fc-sub{{font-size:11px;color:var(--muted);margin-top:2px}}
.fc-sql-breakdown{{margin-top:8px;padding-top:8px;border-top:1px solid var(--border);display:flex;flex-direction:column;gap:5px}}
.fc-sql-row{{display:flex;align-items:center;gap:6px;font-size:11px;color:var(--text-2)}}
.fc-sql-dot{{width:7px;height:7px;border-radius:50%;flex-shrink:0}}
.fc-sql-type{{flex:1}}
.fc-sql-num{{font-weight:700;color:var(--text)}}
.fc-opp-new{{font-size:38px;font-weight:800;color:var(--green);line-height:1}}
.fc-opp-label{{font-size:10px;color:var(--green);font-weight:700;text-transform:uppercase;letter-spacing:.06em}}
.fc-opp-total{{font-size:12px;color:var(--muted);margin-top:8px;padding-top:8px;border-top:1px solid var(--border)}}
.fc-opp-total strong{{color:var(--text-2)}}
.f-c-default{{--fc:var(--guru-500);--fv:var(--text)}}
.f-c-orange{{--fc:var(--orange);--fv:var(--orange)}}
.f-c-green{{--fc:var(--green);--fv:var(--green)}}
.f-c-muted{{--fc:#3a3660;--fv:var(--muted)}}
.rev-blocks{{display:flex;gap:10px;flex-wrap:wrap}}
.rev-block{{flex:1;min-width:130px;background:rgba(255,255,255,.03);border:1px solid var(--border);border-radius:10px;padding:16px 16px 14px;position:relative;overflow:hidden}}
.rev-block::before{{content:'';position:absolute;top:0;left:0;right:0;height:3px;background:var(--rbc,var(--border));border-radius:10px 10px 0 0}}
.rb-num{{font-size:34px;font-weight:800;line-height:1;color:var(--rbc,var(--muted));margin-bottom:6px}}
.rb-name{{font-size:12px;font-weight:600;color:var(--rbc,var(--muted))}}
.rb-desc{{font-size:11px;color:var(--muted);margin-top:3px}}
.card{{background:var(--card);border:1px solid var(--border);border-radius:12px;padding:20px 22px;margin-bottom:12px}}
.card-header{{display:flex;align-items:center;justify-content:space-between;margin-bottom:16px}}
.card-title{{font-size:14px;font-weight:700}}
.badge{{font-size:11px;font-weight:700;padding:3px 10px;border-radius:20px;letter-spacing:.04em}}
.badge-green{{background:rgba(16,185,129,.15);color:var(--green);border:1px solid rgba(16,185,129,.3)}}
.badge-muted{{background:rgba(123,118,160,.12);color:var(--muted);border:1px solid rgba(123,118,160,.25)}}
.table{{width:100%;border-collapse:collapse}}
.table th{{font-size:11px;font-weight:700;color:var(--muted);text-transform:uppercase;letter-spacing:.06em;padding:0 12px 10px 0;text-align:left;border-bottom:1px solid var(--border)}}
.table td{{font-size:13px;color:var(--text-2);padding:10px 12px 10px 0;border-bottom:1px solid rgba(46,42,90,.5);vertical-align:middle}}
.table td strong{{color:var(--text);font-weight:600}}
.table tr.stage-divider td{{background:rgba(255,255,255,.03);font-size:10px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:var(--muted);padding:6px 0;border-bottom:1px solid var(--border)}}
.pill{{display:inline-block;font-size:11px;font-weight:600;padding:3px 9px;border-radius:20px;white-space:nowrap}}
.pill-demo{{background:rgba(16,185,129,.15);color:var(--green)}}
.pill-discov{{background:rgba(124,58,237,.15);color:var(--guru-300)}}
.new-tag{{font-size:10px;font-weight:700;padding:2px 7px;border-radius:10px;background:rgba(16,185,129,.2);color:var(--green);letter-spacing:.04em;text-transform:uppercase}}
.reason-row{{display:flex;align-items:center;gap:12px;margin-bottom:10px}}
.reason-label{{font-size:13px;color:var(--text-2);min-width:220px;flex-shrink:0}}
.reason-bar-wrap{{flex:1;background:rgba(255,255,255,.05);border-radius:4px;height:6px}}
.reason-bar{{height:6px;border-radius:4px}}
.reason-count{{font-size:13px;font-weight:700;color:var(--text);min-width:28px;text-align:right}}
.alert{{border-radius:8px;padding:10px 14px;font-size:12px;margin-bottom:14px;display:flex;align-items:flex-start;gap:8px}}
.alert-muted{{background:rgba(123,118,160,.06);border:1px solid rgba(123,118,160,.2);color:var(--muted)}}
#gs-gate{{position:fixed;inset:0;z-index:9999;background:#0a0618;display:flex;align-items:center;justify-content:center}}
#gs-gate .box{{background:#1e1b42;border:1px solid #2e2a5a;border-radius:16px;padding:40px 36px;width:340px;text-align:center}}
#gs-gate .logo{{width:48px;height:48px;border-radius:12px;margin:0 auto 20px;background:linear-gradient(135deg,#FF6B5B,#ff8f82);display:flex;align-items:center;justify-content:center;font-weight:800;font-size:17px;color:#fff}}
#gs-gate h2{{font-size:18px;font-weight:700;color:#f0edff;margin-bottom:4px}}
#gs-gate p{{font-size:13px;color:#7b76a0;margin-bottom:24px}}
#gs-gate input{{width:100%;padding:11px 14px;border-radius:8px;border:1px solid #2e2a5a;background:#161330;color:#f0edff;font-size:15px;margin-bottom:12px;outline:none;letter-spacing:.08em}}
#gs-gate input:focus{{border-color:#FF6B5B}}
#gs-gate button{{width:100%;padding:11px;border-radius:8px;border:none;cursor:pointer;background:linear-gradient(135deg,#FF6B5B,#ff8f82);color:#fff;font-size:15px;font-weight:700}}
#gs-gate .err{{color:#ef4444;font-size:12px;margin-top:8px;display:none}}
</style>
</head>
<body>
<div id="gs-gate">
  <div class="box">
    <div class="logo">GS</div>
    <h2>GuruSup · Dashboard Diario</h2>
    <p>Acceso restringido</p>
    <input id="gs-pwd" type="password" placeholder="Contraseña" autofocus>
    <button id="gs-btn" onclick="gsCheck()">Entrar</button>
    <div id="gs-err" class="err">Contraseña incorrecta</div>
  </div>
</div>

<div class="header">
  <div class="header-inner">
    <div class="logo-box">GS</div>
    <div class="header-title">
      <h1>GuruSup · Dashboard Diario</h1>
      <p>{fecha_larga} · {periodo_txt}</p>
    </div>
    <span class="live-badge"><span class="live-dot"></span>Actualizado hoy</span>
  </div>
</div>

<div class="main">

  <div class="section-label">Embudo de conversión · {periodo_txt}</div>
  <div class="funnel">
    <div class="f-card f-c-default"><div class="fc-label">Contactos creados</div><div class="fc-value">{contactos}</div><div class="fc-sub">Lifecycle: lead</div></div>
    <div class="f-arrow"></div>
    <div class="f-card f-c-default"><div class="fc-label">MQL</div><div class="fc-value">{mql}</div><div class="fc-sub">Marketing qualified</div></div>
    <div class="f-arrow"></div>
    <div class="f-card f-c-orange"><div class="fc-label">SQLs del período</div><div class="fc-value">{sql_total}</div><div class="fc-sub">Freemium + Consultoría</div>{sql_breakdown}</div>
    <div class="f-arrow"></div>
    <div class="f-card f-c-green"><div class="fc-label">Oportunidades nuevas</div><div class="fc-opp-new">{deals_nuevos}</div><div class="fc-opp-label">en este período</div><div class="fc-opp-total"><strong>{deals_activos}</strong> oportunidades activas en total</div></div>
    <div class="f-arrow"></div>
    <div class="f-card f-c-muted"><div class="fc-label">Clientes nuevos</div><div class="fc-value" style="font-size:28px">—</div><div class="fc-sub">en este período</div></div>
  </div>

  <div class="section-label">Leads en revisión de ventas</div>
  <div class="card" style="padding:16px 20px;">
    <div class="rev-blocks">{rev_blocks}
    </div>
  </div>

  <div class="section-label">Canales de adquisición</div>
  <div class="channels-grid">{ch_cards}
  </div>

  <div class="section-label">Oportunidades activas · Pipeline de ventas</div>
  <div class="card">
    <div class="card-header"><span class="card-title">Deals activos desde Discovery en adelante</span><span class="badge badge-green">{deals_activos} deals activos</span></div>
    <table class="table">
      <thead><tr><th>Empresa</th><th>Etapa</th></tr></thead>
      <tbody>{deal_rows}</tbody>
    </table>
  </div>

  <div class="section-label">Razones de descarte · Deals / Oportunidades</div>
  <div class="card">
    <div class="card-header"><span class="card-title">Oportunidades cerradas o perdidas en el período</span></div>
    {lost_alert}{lost_rows}
  </div>

  <div style="margin-top:40px;text-align:center;font-size:12px;color:var(--muted);">
    GuruSup · Dashboard Diario generado el {generado} (hora España) · datos en vivo desde HubSpot
  </div>
</div>

<script>
function gsCheck(){{
  var inp=document.getElementById('gs-pwd');var err=document.getElementById('gs-err');
  if(inp.value==='radar2026'){{try{{sessionStorage.setItem('gs_ok','1');}}catch(e){{}}document.getElementById('gs-gate').style.display='none';}}
  else{{err.style.display='block';inp.value='';inp.focus();}}
}}
try{{if(sessionStorage.getItem('gs_ok')==='1'){{document.getElementById('gs-gate').style.display='none';}}}}catch(e){{}}
document.addEventListener('keydown',function(e){{var g=document.getElementById('gs-gate');if(e.key==='Enter'&&g&&g.style.display!=='none')gsCheck();}});
</script>
</body>
</html>"""


if __name__ == "__main__":
    main()
