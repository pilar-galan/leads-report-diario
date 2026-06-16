#!/usr/bin/env python3
"""
Genera dashboard_diario.html con datos reales de HubSpot.
Ventana: 8:30h dia anterior → 8:30h hoy (hora España).
Lunes cubre fin de semana: viernes 8:30 → lunes 8:30.
"""
import os, sys, json, urllib.request, urllib.error
from datetime import datetime, timedelta, timezone

TOKEN = os.environ.get("HUBSPOT_TOKEN", "")
BASE  = "https://api.hubapi.com"

MESES = ["enero","febrero","marzo","abril","mayo","junio","julio",
         "agosto","septiembre","octubre","noviembre","diciembre"]
DIAS  = ["Lunes","Martes","Miércoles","Jueves","Viernes","Sábado","Domingo"]

STAGE_LABELS = [
    ("1107496610",           "Discovery",      "pill-discov"),
    ("presentationscheduled","Demo · Reunión",  "pill-demo"),
    ("1033589123",           "Best Case",      "pill-best"),
]

LC_LABELS = {
    "lead":                   "Lead",
    "salesqualifiedlead":     "SQL-Consultoría",
    "1378463825":             "SQL-Freemium",
    "marketingqualifiedlead": "MQL",
    "opportunity":            "Opportunity",
    "customer":               "Cliente",
}

REV_META = [
    ("Ya gestionado",                   "var(--green)"),
    ("Sin revisar",                     "var(--muted)"),
    ("Duplicado",                       "var(--guru-400)"),
    ("No aplica / Descartado",          "var(--red)"),
    ("Pendiente de revisión",           "var(--amber)"),
    ("En revisión",                     "var(--blue)"),
    ("Aceptado para gestión comercial", "var(--orange)"),
]

FIXED_CHANNELS = {
    "Referido": {"n": 0, "icon": "🤝", "color": "#a78bfa", "lc": {}},
}


def api_post(path, payload):
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"},
        method="POST",
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


def classify_channel(src, d1):
    d1 = d1 or ""
    if src == "ORGANIC_SEARCH":  return ("SEO Orgánico",    "🌿", "#10b981")
    if src == "PAID_SEARCH":     return ("Google Ads",      "🔍", "#4285F4")
    if src == "PAID_SOCIAL":     return ("Meta Ads",        "📣", "#ec4899")
    if src == "SOCIAL_MEDIA":    return ("Social orgánico", "📱", "#38bdf8")
    if src == "EMAIL_MARKETING": return ("Email",           "✉️",  "#f97316")
    if src == "REFERRALS":       return ("Referido",        "🤝", "#a78bfa")
    if src == "DIRECT_TRAFFIC":
        if "meetings.hubspot" in d1: return ("Web directo",    "🔗", "#94a3b8")
        if "gurusup.com" in d1:      return ("Web directo",    "🔗", "#94a3b8")
        if "e3875d32" in d1:         return ("App / Freemium", "⚡",  "#f59e0b")
        return ("Web directo", "🔗", "#94a3b8")
    if src == "OFFLINE" and d1 == "CONVERSATIONS":
        return ("Inbox / Chat", "💬", "#06b6d4")
    return ("Otros", "❓", "#7b76a0")


def is_import(src, d1):
    return src == "OFFLINE" and (d1 or "") in ("INTEGRATION", "CRM_UI", "IMPORT")


def is_test(rev, email):
    e = (email or "").lower()
    return ((rev or "") == "Test" or e.startswith("demo@") or "prueba" in e
            or "yanoestaenelcrm" in e or "@test." in e or e.endswith(".test"))


def is_internal(email):
    return (email or "").endswith("@gurusup.com")


def esc(t):
    return str(t).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def pct(n, base):
    return f"{round(n/base*100)}%" if base else "—"


def main():
    if not TOKEN:
        print("ERROR: falta HUBSPOT_TOKEN", file=sys.stderr)
        sys.exit(1)

    tz_spain = timezone(timedelta(hours=2))
    es_now   = datetime.now(timezone.utc).astimezone(tz_spain)

    days_back = 3 if es_now.weekday() == 0 else 1
    start     = es_now - timedelta(days=days_back)
    start_iso = iso(start)
    end_iso   = iso(es_now)

    fecha_larga = f"{DIAS[es_now.weekday()]}, {es_now.day} de {MESES[es_now.month-1]} de {es_now.year}"
    periodo_txt = (f"{start.day} {MESES[start.month-1][:3]} {start.strftime('%H:%M')} → "
                   f"{es_now.day} {MESES[es_now.month-1][:3]} {es_now.strftime('%H:%M')} (hora España)")
    if start.month == es_now.month:
        periodo_corto = f"{start.day}–{es_now.day} {MESES[es_now.month-1][:3]}"
    else:
        periodo_corto = f"{start.day} {MESES[start.month-1][:3]}–{es_now.day} {MESES[es_now.month-1][:3]}"
    if es_now.weekday() == 0:
        periodo_txt   += " · incluye fin de semana"
        periodo_corto += " · incl. finde"

    win_filters = [
        {"propertyName": "createdate", "operator": "BETWEEN", "value": start_iso, "highValue": end_iso},
        {"propertyName": "email", "operator": "NOT_CONTAINS_TOKEN", "value": "gurusup.com"},
    ]
    raw = fetch_all("contacts", win_filters, [
        "email", "lifecyclestage", "hs_analytics_source",
        "hs_analytics_source_data_1", "revision_ventas",
        "email_bienvenida_enviado", "hs_email_open", "hs_email_click",
        "num_conversion_events",
    ])

    real_leads = []
    imports = tests = internal = 0
    for c in raw:
        p     = c["properties"]
        email = p.get("email") or ""
        src   = p.get("hs_analytics_source") or ""
        d1    = p.get("hs_analytics_source_data_1") or ""
        lc    = p.get("lifecyclestage") or ""
        rev   = p.get("revision_ventas") or ""
        biz   = p.get("email_bienvenida_enviado") or ""
        opens = int(p.get("hs_email_open") or 0)
        clicks= int(p.get("hs_email_click") or 0)
        convs = int(p.get("num_conversion_events") or 0)
        if is_internal(email): internal += 1; continue
        if is_test(rev, email): tests += 1; continue
        if is_import(src, d1):  imports += 1; continue
        real_leads.append({"src": src, "d1": d1, "lc": lc, "rev": rev, "email": email,
                           "biz": biz, "open": opens, "click": clicks, "conv": convs})

    total_leads      = len(real_leads)
    sql_consultoria  = sum(1 for l in real_leads if l["lc"] == "salesqualifiedlead")
    sql_freemium     = sum(1 for l in real_leads if l["lc"] == "1378463825")
    sql_total        = sql_consultoria + sql_freemium
    clientes_nuevos  = sum(1 for l in real_leads if l["lc"] == "customer")
    pct_sql_leads    = round(sql_total / total_leads * 100) if total_leads else 0
    app_sin_cualif   = sum(1 for l in real_leads
                           if "e3875d32" in l["d1"] and l["lc"] not in ("salesqualifiedlead","1378463825"))

    # Email de bienvenida (enviado a nuevos leads del período)
    mail_sent  = sum(1 for l in real_leads if l["biz"] == "si")
    mail_open  = sum(1 for l in real_leads if l["biz"] == "si" and l["open"]  > 0)
    mail_click = sum(1 for l in real_leads if l["biz"] == "si" and l["click"] > 0)
    mail_form  = sum(1 for l in real_leads if l["biz"] == "si" and l["conv"]  > 1)

    # Canales
    chan = {}
    for l in real_leads:
        label, icon, color = classify_channel(l["src"], l["d1"])
        if label not in chan: chan[label] = {"n": 0, "icon": icon, "color": color, "lc": {}}
        chan[label]["n"] += 1
        lc_lbl = LC_LABELS.get(l["lc"], l["lc"] or "—")
        chan[label]["lc"][lc_lbl] = chan[label]["lc"].get(lc_lbl, 0) + 1
    # Canales fijos (siempre visibles aunque estén a 0)
    for fc_label, fc_data in FIXED_CHANNELS.items():
        if fc_label not in chan:
            chan[fc_label] = dict(fc_data)
    channels = sorted(chan.items(), key=lambda x: (-x[1]["n"], x[0]))

    # Revisión ventas
    rev_counts = {}
    for l in real_leads:
        key = l["rev"] if l["rev"] else "Sin revisar"
        rev_counts[key] = rev_counts.get(key, 0) + 1

    ya_sql  = sum(1 for l in real_leads if l["rev"]=="Ya gestionado" and l["lc"]=="salesqualifiedlead")
    ya_free = sum(1 for l in real_leads if l["rev"]=="Ya gestionado" and l["lc"]=="1378463825")
    ya_lead = sum(1 for l in real_leads if l["rev"]=="Ya gestionado"
                  and l["lc"] not in ("salesqualifiedlead","1378463825"))
    descartados = [(l["email"], classify_channel(l["src"],l["d1"])[0])
                   for l in real_leads if l["rev"]=="No aplica / Descartado"]

    # Deals
    deal_filters = [
        {"propertyName": "pipeline",     "operator": "EQ", "value": "default"},
        {"propertyName": "hs_is_closed", "operator": "EQ", "value": "false"},
    ]
    all_deals = fetch_all("deals", deal_filters, ["dealname","dealstage","createdate"])
    deals          = [d for d in all_deals if "@" not in (d["properties"].get("dealname") or "")]
    deals_activos  = len(deals)
    nuevos_deals   = [d for d in deals if (d["properties"].get("createdate") or "") >= start_iso]
    demos_pipeline = [d for d in deals if d["properties"].get("dealstage") == "presentationscheduled"]
    nuevos_demos   = [d for d in nuevos_deals if d["properties"].get("dealstage") == "presentationscheduled"]

    data = {
        "fecha_larga":      fecha_larga,
        "periodo_txt":      periodo_txt,
        "periodo_corto":    periodo_corto,
        "total_leads":      total_leads,
        "imports":          imports,
        "tests":            tests,
        "internal":         internal,
        "mail_sent":        mail_sent,
        "mail_open":        mail_open,
        "mail_click":       mail_click,
        "mail_form":        mail_form,
        "sql_total":        sql_total,
        "sql_freemium":     sql_freemium,
        "sql_consultoria":  sql_consultoria,
        "pct_sql_leads":    pct_sql_leads,
        "clientes_nuevos":  clientes_nuevos,
        "nuevos_demos":     len(nuevos_demos),
        "deals_activos":    deals_activos,
        "nuevos_deals":     len(nuevos_deals),
        "demos_pipeline":   len(demos_pipeline),
        "deals":            deals,
        "nuevos_ids":       {x["id"] for x in nuevos_deals},
        "channels":         channels,
        "rev_counts":       rev_counts,
        "ya_sql":           ya_sql,
        "ya_free":          ya_free,
        "ya_lead":          ya_lead,
        "descartados":      descartados,
        "app_sin_cualif":   app_sin_cualif,
        "generado":         es_now.strftime("%d %b %Y · %H:%M"),
    }
    html = render(data)
    with open("dashboard_diario.html", "w", encoding="utf-8") as f:
        f.write(html)
    print(f"OK · leads={total_leads} sql={sql_total} (cons={sql_consultoria} free={sql_freemium}) "
          f"clientes={clientes_nuevos} imports={imports} tests={tests} deals={deals_activos}")


def render(d):
    # Revisión ventas — todos los estados, aunque estén a 0
    rev_blocks = ""
    for key, color in REV_META:
        n = d["rev_counts"].get(key, 0)
        sub = ""
        if key == "Ya gestionado" and n > 0:
            parts = []
            if d["ya_sql"]:  parts.append(f'<span>{d["ya_sql"]} SQL-Consultoría</span>')
            if d["ya_free"]: parts.append(f'<span>{d["ya_free"]} SQL-Freemium</span>')
            if d["ya_lead"]: parts.append(f'<span>{d["ya_lead"]} leads en seguimiento</span>')
            sub = f'<div class="rb-detail">{"".join(parts)}</div>'
        elif key == "No aplica / Descartado" and 0 < len(d["descartados"]) <= 3:
            items = [f"{esc(em)} ({esc(c)})" for em,c in d["descartados"]]
            sub = f'<div class="rb-detail"><span>{", ".join(items)}</span></div>'
        opacity = "" if n > 0 else ' style="opacity:.45"'
        rev_blocks += (f'<div class="rev-block" style="--rbc:{color}"{opacity}>'
                       f'<div class="rb-num">{n}</div>'
                       f'<div class="rb-name">{esc(key)}</div>{sub}</div>\n')

    # Canales
    ch_cards = ""
    for label, c in d["channels"]:
        p      = pct(c["n"], d["total_leads"]) if c["n"] > 0 else "—"
        lc_txt = ", ".join(f"{cnt} {lbl}" for lbl,cnt in sorted(c["lc"].items(), key=lambda x:-x[1]))
        note   = ""
        if label == "Inbox / Chat":
            note = '<div class="ch-note">*pendiente de revisar origen</div>'
        elif label == "App / Freemium":
            note = f'<div class="ch-note">Registro vía app (signup). {d["app_sin_cualif"]} pendientes de cualificar</div>'
        opacity = "" if c["n"] > 0 else ' style="opacity:.45"'
        ch_cards += (f'<div class="ch-card" style="--chc:{c["color"]}"{opacity}>'
                     f'<div class="ch-icon">{c["icon"]}</div>'
                     f'<div class="ch-num">{c["n"]}</div>'
                     f'<div class="ch-label">{esc(label)}</div>'
                     f'<div class="ch-pct">{p} de leads</div>'
                     f'<div class="ch-lc">{esc(lc_txt)}</div>{note}</div>\n')

    # Tabla deals
    by_stage = {}
    for deal in d["deals"]:
        st = deal["properties"].get("dealstage","")
        by_stage.setdefault(st,[]).append(deal)
    deal_rows = ""
    for st_id, label, pill in STAGE_LABELS:
        group = by_stage.get(st_id, [])
        if not group: continue
        deal_rows += f'<tr class="stage-divider"><td colspan="3">{esc(label)} · {len(group)} deals</td></tr>'
        for deal in group:
            name = esc(deal["properties"].get("dealname","—"))
            cd   = (deal["properties"].get("createdate","") or "")[:10]
            tag  = ' <span class="new-tag">NUEVO</span>' if deal["id"] in d["nuevos_ids"] else ""
            deal_rows += (f'<tr><td><strong>{name}</strong>{tag}</td>'
                          f'<td><span class="pill {pill}">{esc(label)}</span></td>'
                          f'<td class="td-date">{cd}</td></tr>')

    return TEMPLATE.format(
        fecha_larga    =esc(d["fecha_larga"]),
        periodo_corto  =esc(d["periodo_corto"]),
        total_leads    =d["total_leads"],
        imports        =d["imports"],
        tests          =d["tests"],
        internal       =d["internal"],
        sql_total      =d["sql_total"],
        sql_freemium   =d["sql_freemium"],
        sql_consultoria=d["sql_consultoria"],
        pct_sql_leads  =d["pct_sql_leads"],
        clientes_nuevos=d["clientes_nuevos"],
        nuevos_demos   =d["nuevos_demos"],
        rev_blocks     =rev_blocks,
        ch_cards       =ch_cards,
        mail_sent      =d["mail_sent"],
        mail_open      =d["mail_open"],
        mail_open_pct  =pct(d["mail_open"],  d["mail_sent"]),
        mail_click     =d["mail_click"],
        mail_click_pct =pct(d["mail_click"], d["mail_sent"]),
        mail_form      =d["mail_form"],
        mail_form_pct  =pct(d["mail_form"],  d["mail_sent"]),
        deal_rows      =deal_rows,
        deals_activos  =d["deals_activos"],
        nuevos_deals   =d["nuevos_deals"],
        demos_pipeline =d["demos_pipeline"],
        generado       =esc(d["generado"]),
    )


TEMPLATE = r"""<!DOCTYPE html><html lang="es"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>GuruSup · Dashboard Diario</title><style>
:root{{--guru-900:#0a0618;--guru-400:#9d5ffa;--guru-300:#c4a2fc;--brand:#FF6B5B;--brand-2:#ff8f82;
--card:#1e1b42;--border:#2e2a5a;--green:#10b981;--amber:#f59e0b;--red:#ef4444;--blue:#3b82f6;
--orange:#f97316;--text:#f0edff;--text-2:#c4bfe0;--muted:#7b76a0}}
*,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
body{{background:var(--guru-900);color:var(--text);font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;line-height:1.5;font-size:15px}}
.header{{position:sticky;top:0;z-index:100;background:rgba(17,14,42,.96);backdrop-filter:blur(16px);border-bottom:1px solid var(--border);padding:0 24px}}
.header-inner{{display:flex;align-items:center;gap:16px;padding:14px 0;flex-wrap:wrap}}
.logo-box{{width:40px;height:40px;background:linear-gradient(135deg,var(--brand),var(--brand-2));border-radius:10px;display:flex;align-items:center;justify-content:center;font-weight:800;color:#fff;box-shadow:0 0 16px rgba(255,107,91,.4)}}
.header-title{{flex:1;min-width:180px}}.header-title h1{{font-size:16px;font-weight:700}}.header-title p{{font-size:12px;color:var(--muted)}}
.live-badge{{background:rgba(16,185,129,.12);border:1px solid rgba(16,185,129,.3);color:var(--green);font-size:11px;font-weight:600;padding:4px 10px;border-radius:20px}}
.main{{max-width:1200px;margin:0 auto;padding:24px 20px 60px}}
.section-label{{font-size:11px;font-weight:700;letter-spacing:.1em;text-transform:uppercase;color:var(--muted);margin:32px 0 14px}}
.section-label:first-child{{margin-top:0}}
.funnel{{display:flex;gap:10px;flex-wrap:wrap}}
.f-card{{flex:1;min-width:220px;background:var(--card);border:1px solid var(--border);border-radius:12px;padding:18px 20px;position:relative;overflow:hidden}}
.f-card::before{{content:'';position:absolute;top:0;left:0;right:0;height:3px;background:var(--fc,var(--brand))}}
.fc-label{{font-size:10px;color:var(--muted);font-weight:700;text-transform:uppercase;letter-spacing:.07em}}
.fc-value{{font-size:44px;font-weight:800;line-height:1.1;color:var(--fv,var(--text))}}
.fc-sub{{font-size:12px;color:var(--muted);margin-top:4px}}
.fc-pct{{display:inline-block;margin-top:8px;font-size:12px;font-weight:700;color:var(--brand);background:rgba(255,107,91,.12);padding:2px 8px;border-radius:20px}}
.fc-breakdown{{display:flex;gap:16px;margin-top:12px;padding-top:12px;border-top:1px solid var(--border)}}
.fbd-item{{text-align:center}}.fbd-num{{font-size:22px;font-weight:800}}.fbd-label{{font-size:10px;color:var(--muted);margin-top:2px}}
.f-leads{{--fc:var(--brand);--fv:var(--brand)}}.f-sql{{--fc:var(--orange);--fv:var(--orange)}}.f-demo{{--fc:var(--green);--fv:var(--green)}}.f-clients{{--fc:var(--guru-400);--fv:var(--guru-300)}}
.note{{font-size:12px;color:var(--muted);margin-top:10px}}
.email-strip{{display:flex;gap:10px;flex-wrap:wrap}}
.email-stat{{flex:1;min-width:120px;background:var(--card);border:1px solid var(--border);border-radius:10px;padding:14px 16px;position:relative;overflow:hidden}}
.email-stat::before{{content:'';position:absolute;top:0;left:0;right:0;height:3px;background:var(--ec,var(--brand))}}
.es-num{{font-size:26px;font-weight:800;color:var(--ec,var(--text))}}
.es-pct{{font-size:11px;font-weight:700;color:var(--ec);opacity:.7;margin-left:3px}}
.es-label{{font-size:11px;color:var(--muted);font-weight:600;margin-top:3px}}
.rev-blocks{{display:flex;gap:10px;flex-wrap:wrap}}
.rev-block{{flex:1;min-width:140px;background:rgba(255,255,255,.03);border:1px solid var(--border);border-radius:10px;padding:14px;position:relative;overflow:hidden}}
.rev-block::before{{content:'';position:absolute;top:0;left:0;right:0;height:3px;background:var(--rbc,var(--border))}}
.rb-num{{font-size:30px;font-weight:800;color:var(--rbc,var(--muted))}}.rb-name{{font-size:11px;font-weight:600;color:var(--rbc,var(--muted));margin-top:4px}}
.rb-detail{{font-size:11px;color:var(--text-2);margin-top:8px;line-height:1.7;border-top:1px solid rgba(255,255,255,.09);padding-top:8px}}
.rb-detail span{{display:block;color:var(--text);font-weight:600}}
.channels-strip{{display:flex;gap:10px;flex-wrap:nowrap}}
@media(max-width:640px){{.channels-strip{{flex-wrap:wrap}}.channels-strip .ch-card{{min-width:calc(50% - 5px)}}}}
.ch-card{{flex:1;min-width:0;background:var(--card);border:1px solid var(--border);border-radius:10px;padding:14px;position:relative;overflow:hidden}}
.ch-card::before{{content:'';position:absolute;top:0;left:0;right:0;height:3px;background:var(--chc,var(--brand))}}
.ch-icon{{font-size:16px;margin-bottom:4px}}
.ch-num{{font-size:42px;font-weight:800;color:var(--chc,var(--text));line-height:1}}
.ch-label{{font-size:10px;font-weight:600;color:var(--text-2);margin-top:5px}}
.ch-pct{{font-size:11px;font-weight:700;color:var(--brand);margin-top:1px}}
.ch-lc{{font-size:9px;color:var(--muted);margin-top:5px;line-height:1.4}}
.ch-note{{font-size:9px;color:var(--muted);margin-top:4px;line-height:1.4;font-style:italic}}
.card{{background:var(--card);border:1px solid var(--border);border-radius:12px;padding:20px 22px;margin-bottom:12px}}
.card-header{{display:flex;align-items:center;justify-content:space-between;margin-bottom:16px}}.card-title{{font-size:14px;font-weight:700}}
.table{{width:100%;border-collapse:collapse}}
.table th{{font-size:11px;font-weight:700;color:var(--muted);text-transform:uppercase;padding:0 12px 10px 0;text-align:left;border-bottom:1px solid var(--border)}}
.table td{{font-size:13px;color:var(--text-2);padding:9px 12px 9px 0;border-bottom:1px solid rgba(46,42,90,.5)}}.table td strong{{color:var(--text)}}
.table tr.stage-divider td{{background:rgba(255,255,255,.03);font-size:10px;font-weight:700;text-transform:uppercase;color:var(--muted);padding:6px 0}}
.td-date{{font-size:11px;color:var(--muted);white-space:nowrap}}
.pill{{display:inline-block;font-size:11px;font-weight:600;padding:3px 9px;border-radius:20px}}
.pill-demo{{background:rgba(16,185,129,.15);color:var(--green)}}.pill-discov{{background:rgba(124,58,237,.15);color:var(--guru-300)}}.pill-best{{background:rgba(245,158,11,.15);color:var(--amber)}}
.new-tag{{font-size:10px;font-weight:800;padding:2px 8px;border-radius:10px;background:rgba(255,107,91,.18);color:var(--brand);text-transform:uppercase;border:1px solid rgba(255,107,91,.4)}}
.deal-footer{{display:flex;gap:32px;margin-top:18px;padding-top:16px;border-top:1px solid var(--border)}}
.df-item .df-num{{font-size:36px;font-weight:800;line-height:1}}
.df-item .df-label{{font-size:11px;color:var(--muted);margin-top:3px}}
#gs-gate{{position:fixed;inset:0;z-index:9999;background:#0a0618;display:flex;align-items:center;justify-content:center}}
#gs-gate .box{{background:#1e1b42;border:1px solid #2e2a5a;border-radius:16px;padding:40px 36px;width:340px;text-align:center}}
#gs-gate .logo{{width:48px;height:48px;border-radius:12px;margin:0 auto 20px;background:linear-gradient(135deg,#FF6B5B,#ff8f82);display:flex;align-items:center;justify-content:center;font-weight:800;font-size:17px;color:#fff}}
#gs-gate h2{{font-size:18px;font-weight:700;margin-bottom:4px}}#gs-gate p{{font-size:13px;color:#7b76a0;margin-bottom:24px}}
#gs-gate input{{width:100%;padding:11px 14px;border-radius:8px;border:1px solid #2e2a5a;background:#161330;color:#f0edff;font-size:15px;margin-bottom:12px;outline:none;letter-spacing:.08em}}
#gs-gate input:focus{{border-color:#FF6B5B}}
#gs-gate button{{width:100%;padding:11px;border-radius:8px;border:none;cursor:pointer;background:linear-gradient(135deg,#FF6B5B,#ff8f82);color:#fff;font-size:15px;font-weight:700}}
#gs-gate .err{{color:#ef4444;font-size:12px;margin-top:8px;display:none}}
</style></head><body>
<div id="gs-gate"><div class="box">
  <div class="logo">GS</div>
  <h2>GuruSup · Dashboard Diario</h2><p>Acceso restringido</p>
  <input id="gs-pwd" type="password" placeholder="Contraseña" autofocus>
  <button onclick="gsCheck()">Entrar</button>
  <div id="gs-err" class="err">Contraseña incorrecta</div>
</div></div>
<div class="header"><div class="header-inner"><div class="logo-box">GS</div>
<div class="header-title"><h1>GuruSup · Dashboard Diario</h1><p>{fecha_larga} · período {periodo_corto} · hora España</p></div>
<span class="live-badge">● Datos en vivo · HubSpot</span></div></div>
<div class="main">

  <div class="section-label">Embudo de leads</div>
  <div class="funnel">
    <div class="f-card f-leads">
      <div class="fc-label">Leads reales generados</div>
      <div class="fc-value">{total_leads}</div>
      <div class="fc-sub">Paid · Social Ads · Orgánico · App · Directo · Social orgánico</div>
    </div>
    <div class="f-card f-sql">
      <div class="fc-label">SQL totales</div>
      <div class="fc-value">{sql_total}</div>
      <div class="fc-pct">{pct_sql_leads}% de leads</div>
      <div class="fc-breakdown">
        <div class="fbd-item"><div class="fbd-num" style="color:var(--guru-300)">{sql_freemium}</div><div class="fbd-label">SQL-Freemium</div></div>
        <div class="fbd-item"><div class="fbd-num" style="color:var(--orange)">{sql_consultoria}</div><div class="fbd-label">SQL-Consultoría</div></div>
      </div>
    </div>
    <div class="f-card f-demo">
      <div class="fc-label">Reuniones agendadas · período</div>
      <div class="fc-value">{nuevos_demos}</div>
      <div class="fc-sub" style="margin-top:10px;padding-top:10px;border-top:1px solid var(--border)">Total en pipeline: <strong style="color:var(--text)">{demos_pipeline}</strong></div>
    </div>
    <div class="f-card f-clients">
      <div class="fc-label">Clientes nuevos · período</div>
      <div class="fc-value">{clientes_nuevos}</div>
      <div class="fc-sub">Deals cerrados en el período</div>
    </div>
  </div>
  <p class="note">ℹ️ Excluidos: <strong>{imports}</strong> importaciones · <strong>{tests}</strong> tests · <strong>{internal}</strong> cuenta interna.</p>

  <div class="section-label">Leads en revisión de ventas · {total_leads} leads reales</div>
  <div class="card" style="padding:16px 20px">
    <div class="rev-blocks">{rev_blocks}</div>
  </div>

  <div class="section-label">Canales de adquisición · {total_leads} leads reales</div>
  <div class="channels-strip">{ch_cards}</div>

  <div class="section-label">Email de bienvenida · enviado a nuevos leads del período</div>
  <div class="email-strip">
    <div class="email-stat" style="--ec:var(--brand)">
      <div class="es-num">{mail_sent}</div><div class="es-label">Enviados</div>
    </div>
    <div class="email-stat" style="--ec:var(--blue)">
      <div class="es-num">{mail_open}<span class="es-pct">{mail_open_pct}</span></div><div class="es-label">Abiertos</div>
    </div>
    <div class="email-stat" style="--ec:var(--orange)">
      <div class="es-num">{mail_click}<span class="es-pct">{mail_click_pct}</span></div><div class="es-label">Clics</div>
    </div>
    <div class="email-stat" style="--ec:var(--green)">
      <div class="es-num">{mail_form}<span class="es-pct">{mail_form_pct}</span></div><div class="es-label">Formulario rellenado</div>
    </div>
  </div>
  <p class="note">Aperturas y clics provienen de las métricas de email marketing de HubSpot; "Formulario rellenado" = leads con más de un envío de formulario (proxy).</p>

  <div class="section-label">Oportunidades activas · Pipeline de ventas</div>
  <div class="card">
    <div class="card-header"><span class="card-title">Deals activos (excl. freemium/signups)</span></div>
    <table class="table"><thead><tr><th>Empresa</th><th>Etapa</th><th>Entrada</th></tr></thead>
    <tbody>{deal_rows}</tbody></table>
    <div class="deal-footer">
      <div class="df-item"><div class="df-num" style="color:var(--brand)">{nuevos_deals}</div><div class="df-label">Oportunidades nuevas hoy</div></div>
      <div class="df-item"><div class="df-num" style="color:var(--green)">{demos_pipeline}</div><div class="df-label">En demo / reunión</div></div>
      <div class="df-item"><div class="df-num">{deals_activos}</div><div class="df-label">Total en pipeline</div></div>
    </div>
  </div>

  <div style="margin-top:40px;text-align:center;font-size:12px;color:var(--muted)">
    GuruSup · Dashboard Diario · generado el {generado} (hora España)
  </div>
</div>
<script>
function gsCheck(){{var inp=document.getElementById('gs-pwd');var err=document.getElementById('gs-err');
if(inp.value==='radar2026'){{try{{sessionStorage.setItem('gs_ok','1');}}catch(e){{}}document.getElementById('gs-gate').style.display='none';}}
else{{err.style.display='block';inp.value='';inp.focus();}}}}
try{{if(sessionStorage.getItem('gs_ok')==='1'){{document.getElementById('gs-gate').style.display='none';}}}}catch(e){{}}
document.addEventListener('keydown',function(e){{var g=document.getElementById('gs-gate');if(e.key==='Enter'&&g&&g.style.display!=='none')gsCheck();}});
</script></body></html>"""


if __name__ == "__main__":
    main()
