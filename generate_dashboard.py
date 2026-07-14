#!/usr/bin/env python3
"""
Genera dashboard_diario.html con datos reales de HubSpot.

Estructura:
  1. Dos embudos (pirámide invertida) ACUMULADOS desde 1 jun:
     - Comercial: Contactos -> Leads -> SQL -> Reunión -> Oportunidad -> Cliente
     - Freemium:  Contactos -> Freemium -> Agenda -> Oportunidad -> Cliente
  2. Tres gráficos evolutivos acumulados desde 1 jun (contactos, SQL, oportunidades).
  3. Contactos generados últimas 24h (funnel con flechas y % de conversión) + freemium.
  4. Canales de adquisición (24h) con desglose lead/SQL/freemium.
  5. Seguimiento de ventas · estado de los SQL (24h).
  6. Pipeline de ventas (periodo).

Ventanas: los embudos y gráficos se calculan desde HIST_START (1 jun) hasta ahora.
El resumen 24h, canales y estados usan la ventana diaria.
Overrides por env: GEN_START/GEN_END/GEN_OUTPUT/GEN_TITLE/GEN_PERIOD/GEN_FECHA/GEN_HIST_START.
"""
import os, sys, json, time, urllib.request, urllib.error, re
from datetime import datetime, timedelta, timezone, date

TOKEN = os.environ.get("HUBSPOT_TOKEN", "")
BASE  = "https://api.hubapi.com"

MESES = ["enero","febrero","marzo","abril","mayo","junio","julio",
         "agosto","septiembre","octubre","noviembre","diciembre"]
MESES3 = ["ene","feb","mar","abr","may","jun","jul","ago","sep","oct","nov","dic"]
DIAS  = ["Lunes","Martes","Miércoles","Jueves","Viernes","Sábado","Domingo"]

FUNNEL_START_DEFAULT = "2026-01-01T00:00:00"   # embudos acumulados desde 1 ene (anual)
CHART_START_DEFAULT  = "2026-01-01T00:00:00"   # gráficos evolutivos anuales desde 1 ene

MARKETING_SOURCES = {
    "PAID_SEARCH", "PAID_SOCIAL", "ORGANIC_SEARCH", "SOCIAL_MEDIA",
    "DIRECT_TRAFFIC", "REFERRALS", "OTHER_CAMPAIGNS",
}

# Rango del ciclo de vida (para contar "alcanzó etapa X")
LC_RANK = {
    "subscriber": 0, "lead": 1, "marketingqualifiedlead": 2,
    "salesqualifiedlead": 3, "opportunity": 4, "customer": 5,
    # Etapas de precualificación por volumen (van a ventas) = SQL
    "1394675094": 3,  # >3000Consultas
    "1394675095": 3,  # <3000Consultas
    "1394675096": 3,  # NoSabeNumeroConversaciones
}
# Etapas que se consideran SQL (para conteos y tabla de seguimiento)
SQL_STAGES = {"salesqualifiedlead", "1394675094", "1394675095", "1394675096"}

STAGE_LABELS = [
    ("1107496610",           "Discovery",      "pill-discov"),
    ("presentationscheduled","Demo / Reunión",  "pill-demo"),
    ("1033589123",           "Best Case",      "pill-best"),
]

# Rango de etapas de deal (para el embudo por empresas)
DEAL_RANK = {"1107496610": 1, "presentationscheduled": 2, "1033589123": 3, "closedwon": 4}

# Unificación de razones de descarte/descalificación (contacto razon_descarte_sql + deal motivo_de_descalificacion)
UNIFY_DESCARTE = {
    # razon_descarte_sql (contactos)
    "Lead accidental (no recuerda registrarse, clic por error, curiosidad, broma": "Lead accidental / no recuerda",
    "Volumen <500 → Freemium": "Volumen insuficiente",
    "Timing — \"ahora no es prioridad\"": "Timing / no es prioridad",
    "Caso de uso equivocado (esperan mensajería masiva)": "Caso de uso / no target",
    "Competidor con integración vertical nativa": "Competidor",
    "Intención no cualificada / sin autoridad": "Sin autoridad / no cualificado",
    "Build vs buy (\"lo hacemos nosotros\")": "Build vs buy",
    "Precio": "Precio / presupuesto",
    # motivo_de_descalificacion (deals)
    "No interés": "Timing / no es prioridad",
    "No target": "Caso de uso / no target",
    "No hay presu": "Precio / presupuesto",
    "No hay volumen": "Volumen insuficiente",
    "Contato incorrecto": "Sin autoridad / no cualificado",
    "Test": "Test",
    "Otros": "Otros",
}

LC_LABELS = {
    "lead": "Lead", "salesqualifiedlead": "SQL-Consultoría", "1378463825": "Freemium",
    "marketingqualifiedlead": "MQL", "opportunity": "Oportunidad", "customer": "Cliente",
}

REV_META = [
    ("Ya gestionado",                   "var(--green)"),
    ("Pendiente de revisión",           "var(--amber)"),
    ("En revisión",                     "var(--blue)"),
    ("Aceptado para gestión comercial", "var(--orange)"),
    ("Duplicado",                       "var(--guru-400)"),
    ("No aplica / Descartado",          "var(--red)"),
    ("Test",                            "var(--muted)"),
]

FIXED_CHANNELS = {
    "Social Ads":         {"icon": "📣", "color": "#a855f7"},
    "Google Ads":         {"icon": "🔍", "color": "#4285F4"},
    "Tráfico directo":    {"icon": "🔗", "color": "#94a3b8"},
    "SEO Orgánico":       {"icon": "🌿", "color": "#10b981"},
    "Social orgánico":    {"icon": "🌱", "color": "#22c55e"},
    "Eventos / Campañas": {"icon": "🎪", "color": "#ec4899"},
    "Chat web":           {"icon": "💬", "color": "#22d3ee"},
}


# ─────────────── HubSpot API (con reintentos ante 429) ───────────────
def _open(req, tries=6):
    for a in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            if e.code == 429 and a < tries - 1:
                ra = e.headers.get("Retry-After")
                time.sleep(float(ra) if ra else min(2 ** a, 10))
                continue
            raise
        except urllib.error.URLError:
            if a < tries - 1:
                time.sleep(min(2 ** a, 10)); continue
            raise


def api_post(path, payload):
    req = urllib.request.Request(BASE + path, data=json.dumps(payload).encode(),
        headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}, method="POST")
    return _open(req)


def api_get(path):
    req = urllib.request.Request(BASE + path,
        headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}, method="GET")
    return _open(req)


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
        time.sleep(0.25)  # evita ráfagas que disparan el rate limit
    return results


def iso(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


# ─────────────── Clasificadores ───────────────
def classify_channel(src, d1):
    d1 = d1 or ""
    if src == "PAID_SEARCH":     return ("Google Ads", "🔍", "#4285F4")
    if src == "PAID_SOCIAL":     return ("Social Ads", "📣", "#a855f7")
    if src == "ORGANIC_SEARCH":  return ("SEO Orgánico", "🌿", "#10b981")
    if src == "SOCIAL_MEDIA":    return ("Social orgánico", "🌱", "#22c55e")
    if src == "REFERRALS":       return ("Referido", "🤝", "#a78bfa")
    if src == "OTHER_CAMPAIGNS": return ("Eventos / Campañas", "🎪", "#ec4899")
    if src == "EMAIL_MARKETING": return ("Email", "✉️", "#f97316")
    if src == "OFFLINE" and d1 == "CONVERSATIONS":
        return ("Chat web", "💬", "#22d3ee")
    if src == "DIRECT_TRAFFIC":
        return ("Tráfico directo", "🔗", "#94a3b8")
    return ("Otros", "•", "#64748b")


def is_marketing(src, d1):
    return src in MARKETING_SOURCES or (src == "OFFLINE" and (d1 or "") == "CONVERSATIONS")


def is_import(src, d1):
    # INTEGRATION = altas de la app (freemium); NO se excluyen, se reclasifican a freemium
    return src == "OFFLINE" and (d1 or "") in ("CRM_UI", "IMPORT")


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


def rank(lc):
    return LC_RANK.get(lc, 0)


def is_free(c):
    return c["lc"] == "1378463825" or c["sql_state"] == "Freemium"


def funnel_counts(lst):
    return {
        "total": len(lst),
        "lead": sum(1 for c in lst if rank(c["lc"]) >= 1),
        "lead_pure": sum(1 for c in lst if rank(c["lc"]) in (1, 2)),  # lead/MQL, aún no SQL
        "mql": sum(1 for c in lst if rank(c["lc"]) >= 2),  # alcanzaron MQL (acumulativo)
        "sql":  sum(1 for c in lst if rank(c["lc"]) >= 3),
        "opp":  sum(1 for c in lst if rank(c["lc"]) >= 4),
        "cli":  sum(1 for c in lst if rank(c["lc"]) >= 5),
        "free": sum(1 for c in lst if is_free(c)),
    }


# ─────────────── Reuniones de marketing ───────────────
def fetch_marketing_meetings(start_iso, end_iso):
    """Devuelve [{cid, name, channel, created}] de reuniones creadas en el rango
    cuyo contacto asociado entró por marketing. Defensivo."""
    out = []
    try:
        data = api_post("/crm/v3/objects/meetings/search", {
            "filterGroups": [{"filters": [
                {"propertyName": "hs_createdate", "operator": "BETWEEN", "value": start_iso, "highValue": end_iso},
            ]}],
            "properties": ["hs_meeting_title", "hs_createdate"],
            "limit": 100,
        })
    except Exception as err:
        print(f"  meetings search error: {err}")
        return out
    seen = set()
    for m in data.get("results", []):
        mid = m["id"]
        created = (m.get("properties", {}).get("hs_createdate") or "")[:10]
        try:
            assoc = api_get(f"/crm/v4/objects/meetings/{mid}/associations/contacts")
            cids = [r["toObjectId"] for r in assoc.get("results", [])]
        except Exception:
            cids = []
        for cid in cids[:1]:
            if cid in seen:
                continue
            try:
                c = api_get(f"/crm/v3/objects/contacts/{cid}"
                            "?properties=hs_analytics_source,hs_analytics_source_data_1,company,firstname")
                cp = c.get("properties", {})
                src = cp.get("hs_analytics_source") or ""
                d1 = cp.get("hs_analytics_source_data_1") or ""
            except Exception:
                continue
            if not is_marketing(src, d1):
                continue
            seen.add(cid)
            label, _, _ = classify_channel(src, d1)
            name = (cp.get("firstname") or cp.get("company") or "Sin nombre").strip()
            out.append({"cid": cid, "name": name, "channel": label, "created": created})
    return out


SDR_OWNERS = ["92703778", "92703779"]  # Agustín Di Nardo · Juan Manuel (Juanma) Jura

def count_sdr_calls(start_iso, end_iso):
    """Nº de llamadas de los SDR (Agustín/Juanma) en el rango (por hs_timestamp)."""
    try:
        res = fetch_all("calls", [
            {"propertyName": "hubspot_owner_id", "operator": "IN", "values": SDR_OWNERS},
            {"propertyName": "hs_timestamp", "operator": "BETWEEN", "value": start_iso, "highValue": end_iso},
        ], ["hs_timestamp"])
        return len(res)
    except Exception as e:
        print(f"  sdr calls error: {e}")
        return 0


def count_meetings_held(start_iso, end_iso):
    """Nº de reuniones REALIZADAS (celebradas) en el rango (start_time ya pasado)."""
    try:
        res = fetch_all("meetings", [
            {"propertyName": "hs_meeting_start_time", "operator": "BETWEEN", "value": start_iso, "highValue": end_iso},
        ], ["hs_meeting_start_time"])
        return len(res)
    except Exception as e:
        print(f"  meetings held error: {e}")
        return 0


def parse_hs_dt(v):
    """Convierte un valor de fecha de HubSpot (epoch ms o ISO) a datetime UTC."""
    if not v:
        return None
    v = str(v)
    try:
        if v.isdigit():
            return datetime.fromtimestamp(int(v) / 1000, timezone.utc)
        return datetime.fromisoformat(v.replace("Z", "+00:00"))
    except Exception:
        return None


def _chunks(lst, n=100):
    for i in range(0, len(lst), n):
        yield lst[i:i + n]


def deal_meeting_starts(deal_ids):
    """{deal_id: [datetime, ...]} con las horas de inicio de las reuniones asociadas a cada deal."""
    out = {}
    if not deal_ids:
        return out
    # 1) Asociaciones deal -> meetings (v4 batch)
    d2m, mids = {}, set()
    for chunk in _chunks(deal_ids):
        try:
            res = api_post("/crm/v4/associations/deals/meetings/batch/read",
                           {"inputs": [{"id": str(i)} for i in chunk]})
        except Exception as e:
            print(f"  assoc deals->meetings error: {e}"); continue
        for r in res.get("results", []):
            did = str(r.get("from", {}).get("id"))
            ms = [str(t.get("toObjectId")) for t in r.get("to", []) if t.get("toObjectId")]
            d2m[did] = ms; mids.update(ms)
        time.sleep(0.2)
    # 2) Hora de inicio de cada meeting (v3 batch read)
    starts = {}
    for chunk in _chunks(list(mids)):
        try:
            res = api_post("/crm/v3/objects/meetings/batch/read",
                           {"properties": ["hs_meeting_start_time"],
                            "inputs": [{"id": m} for m in chunk]})
        except Exception as e:
            print(f"  meetings batch read error: {e}"); continue
        for m in res.get("results", []):
            dt = parse_hs_dt(m.get("properties", {}).get("hs_meeting_start_time"))
            if dt:
                starts[m["id"]] = dt
        time.sleep(0.2)
    for did, ms in d2m.items():
        out[did] = sorted(starts[m] for m in ms if m in starts)
    return out


# ─────────────── SVG chart ───────────────
def svg_cumulative(cum, daily, labels, color):
    """cum: lista acumulada; daily: incremento diario; labels: 'DD mmm' por día."""
    if not cum:
        return '<div style="color:var(--muted);font-size:12px;padding:20px 0">Sin datos</div>'
    W, H = 720, 200
    pl, pr, pt, pb = 44, 14, 16, 30
    n = len(cum)
    maxv = max(cum) or 1
    pw, ph = W - pl - pr, H - pt - pb
    def X(i): return pl + (pw * i / (n - 1 if n > 1 else 1))
    def Y(v): return pt + ph * (1 - v / maxv)
    line = " ".join(f"{X(i):.1f},{Y(v):.1f}" for i, v in enumerate(cum))
    area = f"{pl},{pt+ph} " + line + f" {X(n-1):.1f},{pt+ph}"
    # ticks de eje Y (0, medio, max)
    yt = "".join(
        f'<text x="{pl-6}" y="{Y(maxv*f)+4:.0f}" text-anchor="end" fill="#7b76a0" font-size="10">{round(maxv*f)}</text>'
        f'<line x1="{pl}" y1="{Y(maxv*f):.0f}" x2="{W-pr}" y2="{Y(maxv*f):.0f}" stroke="#2e2a5a" stroke-width="1" opacity=".5"/>'
        for f in (0, .5, 1))
    # líneas y etiquetas de mes (cambio de mes en labels 'D mmm')
    months = ""
    prev_m = None
    for i, lb in enumerate(labels):
        m = lb.split()[-1]
        if m != prev_m:
            months += (f'<line x1="{X(i):.0f}" y1="{pt}" x2="{X(i):.0f}" y2="{pt+ph}" stroke="#2e2a5a" stroke-width="1" opacity=".55"/>'
                       f'<text x="{X(i)+3:.0f}" y="{pt+11}" fill="#9a95c0" font-size="10" font-weight="700">{m}</text>')
            prev_m = m
    # top-2 saltos (mayores incrementos diarios) = fechas destacadas
    dots = ""
    if daily:
        top = sorted(range(n), key=lambda i: daily[i], reverse=True)
        top = [i for i in top if daily[i] > 0][:2]
        for i in top:
            dots += (f'<circle cx="{X(i):.1f}" cy="{Y(cum[i]):.1f}" r="4" fill="{color}"/>'
                     f'<text x="{X(i):.0f}" y="{Y(cum[i])-8:.0f}" text-anchor="middle" fill="{color}" '
                     f'font-size="10" font-weight="700">{labels[i].split()[0]} +{daily[i]}</text>')
    # etiquetas de eje X (primero y último)
    xt = "".join(
        f'<text x="{X(i):.0f}" y="{H-8}" text-anchor="{a}" fill="#7b76a0" font-size="10">{labels[i]}</text>'
        for i, a in ((0, "start"), (n-1, "end")))
    return (f'<svg viewBox="0 0 {W} {H}" width="100%" preserveAspectRatio="xMidYMid meet" '
            f'style="display:block">'
            f'<defs><linearGradient id="g{color[1:]}" x1="0" y1="0" x2="0" y2="1">'
            f'<stop offset="0" stop-color="{color}" stop-opacity=".30"/>'
            f'<stop offset="1" stop-color="{color}" stop-opacity="0"/></linearGradient></defs>'
            f'{yt}{months}'
            f'<polygon points="{area}" fill="url(#g{color[1:]})"/>'
            f'<polyline points="{line}" fill="none" stroke="{color}" stroke-width="2.5" '
            f'stroke-linejoin="round" stroke-linecap="round"/>'
            f'{dots}{xt}</svg>')


# ─────────────── Main ───────────────
def main():
    if not TOKEN:
        print("ERROR: falta HUBSPOT_TOKEN", file=sys.stderr)
        sys.exit(1)

    tz = timezone(timedelta(hours=2))
    es_now = datetime.now(timezone.utc).astimezone(tz)

    gen_start = os.environ.get("GEN_START")
    gen_end   = os.environ.get("GEN_END")
    out_file  = os.environ.get("GEN_OUTPUT", "dashboard_diario.html")
    title     = os.environ.get("GEN_TITLE",  "GuruSup · Dashboard Diario")
    period_ov = os.environ.get("GEN_PERIOD")
    fecha_ov  = os.environ.get("GEN_FECHA")
    funnel_start_s = os.environ.get("GEN_HIST_START", FUNNEL_START_DEFAULT)
    chart_start_s  = os.environ.get("GEN_CHART_START", CHART_START_DEFAULT)

    if gen_start and gen_end:
        start  = datetime.fromisoformat(gen_start).replace(tzinfo=tz)
        es_now = datetime.fromisoformat(gen_end).replace(tzinfo=tz)
        fecha_larga = fecha_ov or "Informe"
        periodo_txt = period_ov or (f"{start.day} {MESES3[start.month-1]} → "
                                    f"{es_now.day} {MESES3[es_now.month-1]} {es_now.year}")
    else:
        today_9   = es_now.replace(hour=9, minute=0, second=0, microsecond=0)
        days_back = 3 if es_now.weekday() == 0 else 1
        start     = today_9 - timedelta(days=days_back)
        fecha_larga = f"{DIAS[es_now.weekday()]}, {es_now.day} de {MESES[es_now.month-1]} de {es_now.year}"
        periodo_txt = (f"{start.day} {MESES3[start.month-1]} {start.strftime('%H:%M')} → "
                       f"{es_now.day} {MESES3[es_now.month-1]} {es_now.strftime('%H:%M')} (hora España)")
        if es_now.weekday() == 0:
            periodo_txt += " · incluye fin de semana"

    start_iso = iso(start)
    end_iso   = iso(es_now)
    funnel_start = datetime.fromisoformat(funnel_start_s).replace(tzinfo=tz)
    funnel_iso   = iso(funnel_start)
    chart_start  = datetime.fromisoformat(chart_start_s).replace(tzinfo=tz)
    chart_iso    = iso(chart_start)

    # Histórico desde 1 ene (gráficos anuales; embudos y diario son subconjuntos)
    hraw = fetch_all("contacts", [
        {"propertyName": "createdate", "operator": "BETWEEN", "value": chart_iso, "highValue": end_iso},
        {"propertyName": "email", "operator": "NOT_CONTAINS_TOKEN", "value": "gurusup.com"},
    ], ["email", "firstname", "company", "lifecyclestage", "hs_analytics_source",
        "hs_analytics_source_data_1", "revision_ventas", "estado_sql_consultoria",
        "hs_lead_status", "createdate"])

    hist = []
    imports = tests = internal = 0
    for c in hraw:
        p = c["properties"]
        email = p.get("email") or ""
        src = p.get("hs_analytics_source") or ""
        d1 = p.get("hs_analytics_source_data_1") or ""
        lc = p.get("lifecyclestage") or ""
        if is_internal(email): internal += 1; continue
        if is_test(p.get("revision_ventas"), email): tests += 1; continue
        # Las importaciones (CRM_UI / IMPORT) se excluyen SALVO que sean freemium
        if is_import(src, d1) and lc != "1378463825":
            imports += 1; continue
        # Altas por la integración de la app = freemium (aunque estén mal cualificadas como opportunity)
        if src == "OFFLINE" and (d1 or "") == "INTEGRATION":
            lc = "1378463825"
        hist.append({
            "src": src, "d1": d1, "lc": lc,
            "rev": p.get("revision_ventas") or "",
            "sql_state": p.get("estado_sql_consultoria") or "",
            "lead_state": p.get("hs_lead_status") or "",
            "email": email, "firstname": p.get("firstname") or "", "company": p.get("company") or "",
            "created": (p.get("createdate") or "")[:10],
            "created_full": p.get("createdate") or "",
        })

    daily = [c for c in hist if c["created_full"] >= start_iso]
    hist_fun = [c for c in hist if c["created_full"] >= funnel_iso]   # embudos: desde 1 jun

    fstart, dstart = funnel_iso[:10], start_iso[:10]

    # ── Oportunidades y Clientes = contactos en opportunity/customer, DEDUPLICADOS por empresa ──
    # (el token no tiene permiso de lectura del objeto companies → usamos contactos únicos por compañía)
    def compkey(c):
        return c["company"].strip().lower() or c["email"].strip().lower() or id(c)
    def uniq_companies(lc_value, since):
        return len({compkey(c) for c in hist if c["lc"] == lc_value and c["created"] >= since})
    opp_cum = uniq_companies("opportunity", fstart)
    cli_cum = uniq_companies("customer", fstart)
    opp_day = uniq_companies("opportunity", dstart)
    cli_day = uniq_companies("customer", dstart)

    # ── Deals · reunión agendada (demo+) y tabla de pipeline (abiertos) ──
    DEMO_PLUS = {"presentationscheduled", "1033589123", "1119432966"}  # needs-validation, best case, close won
    # Pipelines para distinguir Brain (GuruSup/Company Brain) de ventas normales
    try:
        pdefs = api_get("/crm/v3/pipelines/deals").get("results", [])
        PL_LABEL = {p["id"]: (p.get("label") or "") for p in pdefs}
    except Exception as e:
        print(f"  pipelines error: {e}"); PL_LABEL = {}
    def is_brain_pl(pid):
        return "brain" in PL_LABEL.get(pid, "").lower()
    all_deals = fetch_all("deals", [
        {"propertyName": "hs_is_closed", "operator": "EQ", "value": "false"},
    ], ["dealname", "dealstage", "pipeline", "createdate", "hs_is_closed",
        "hs_analytics_source", "hs_analytics_source_data_1"])

    def valid_deal(n):
        n = (n or "").lower()
        return "@" not in n and "[duplicado]" not in n and not n.rstrip().endswith("new deal") and "- new deal" not in n
    def clean_deal(n):
        return re.sub(r'\s*-\s*nuevo tipo de objeto deal\s*$', '', n or "", flags=re.I).strip()

    deals = []            # todos los deals válidos abiertos (para reunión)
    open_deals = []       # abiertos marketing (para tabla pipeline)
    brain_count = ventas_count = 0
    for dl in all_deals:
        p = dl["properties"]
        if not valid_deal(p.get("dealname", "")):
            continue
        stage = p.get("dealstage", ""); pid = p.get("pipeline", "")
        created = (p.get("createdate") or "")[:10]
        src, d1 = p.get("hs_analytics_source") or "", p.get("hs_analytics_source_data_1") or ""
        deals.append({"stage": stage, "created": created})
        if is_marketing(src, d1):
            if is_brain_pl(pid): brain_count += 1
            else: ventas_count += 1
            icon = classify_channel(src, d1)[1]; label = classify_channel(src, d1)[0]
            open_deals.append({"id": dl["id"], "name": clean_deal(p.get("dealname", "—")) or "—",
                               "stage": stage, "created": created, "channel": f"{icon} {label}",
                               "brain": is_brain_pl(pid)})

    # Fecha de la reunión (discovery/demo) programada para cada deal del pipeline
    mtg = deal_meeting_starts([d["id"] for d in open_deals])
    now_utc = es_now.astimezone(timezone.utc)
    for od in open_deals:
        starts = mtg.get(od["id"], [])
        upcoming = [s for s in starts if s >= now_utc]
        chosen = upcoming[0] if upcoming else (starts[-1] if starts else None)
        od["mtg_future"] = bool(upcoming)           # True si es una reunión futura
        od["mtg_sort"] = chosen.timestamp() if chosen else float("inf")
        if chosen:
            ch_es = chosen.astimezone(tz)
            od["mtg_txt"] = f"{ch_es.day} {MESES3[ch_es.month-1]} · {ch_es.strftime('%H:%M')}"
        else:
            od["mtg_txt"] = ""

    reunion_cum = sum(1 for d in deals if d["stage"] in DEMO_PLUS and d["created"] >= fstart)
    reunion_day = sum(1 for d in deals if d["stage"] in DEMO_PLUS and d["created"] >= dstart)
    calls_day = count_sdr_calls(start_iso, end_iso)   # llamadas de Agustín/Juanma en 24h

    # Reuniones (calendario) del día -> nombres (ventana diaria, ligero)
    meetings = fetch_marketing_meetings(start_iso, end_iso)
    daily_meets = [m for m in meetings if m["created"] >= dstart]
    meet_names = " · ".join(f"<strong>{esc(m['name'])}</strong> ({esc(m['channel'])})" for m in daily_meets) or "—"

    cum = funnel_counts(hist_fun)
    dd  = funnel_counts(daily)

    # ── Disposición de los SQL (estado de gestión por «Revisión ventas») ──
    def rev_group(rev):
        r = rev or ""
        if r in ("Ya gestionado", "Aceptado para gestión comercial", "En revisión"):
            return "gestionado"
        if r == "No aplica / Descartado":
            return "descartado"
        if r in ("Duplicado", "Test"):
            return "excluido"
        return "pendiente"   # «Pendiente de revisión» o sin asignar
    sql_stage_contacts = [c for c in hist_fun if c["lc"] in SQL_STAGES]
    sql_disp = {"total": len(sql_stage_contacts), "gestionado": 0,
                "pendiente": 0, "descartado": 0, "excluido": 0}
    for c in sql_stage_contacts:
        sql_disp[rev_group(c["rev"])] += 1
    # Contactos que ya avanzaron a Oportunidad/Cliente (rank>=4)
    sql_disp["avanzados"] = sum(1 for c in hist_fun if rank(c["lc"]) >= 4)

    # Oportunidades y clientes = EMPRESAS (ciclo de vida); reunión = deals en demo+
    agenda_cum, cum["opp"], cum["cli"] = reunion_cum, opp_cum, cli_cum
    # Reuniones agendadas (24h) = demos agendadas + llamadas de los SDR (Agustín/Juanma)
    agenda_day, dd["opp"], dd["cli"] = reunion_day + calls_day, opp_day, cli_day

    # ── Gráficos acumulados por día (anual, desde 1 ene) ──
    d0 = chart_start.date()
    dN = es_now.date()
    days = []
    dcur = d0
    while dcur <= dN:
        days.append(dcur)
        dcur += timedelta(days=1)
    idx = {d.isoformat(): i for i, d in enumerate(days)}
    def series(items, pred, keyf=None):
        daily_inc = [0]*len(days)
        seen = set()
        for it in sorted(items, key=lambda x: x["created"]) if keyf else items:
            if it["created"] in idx and pred(it):
                if keyf:
                    k = keyf(it)
                    if k in seen:
                        continue
                    seen.add(k)
                daily_inc[idx[it["created"]]] += 1
        cumv, run = [], 0
        for v in daily_inc:
            run += v; cumv.append(run)
        return cumv, daily_inc
    labels = [f"{d.day} {MESES3[d.month-1]}" for d in days]
    ch_leads = series(hist, lambda c: rank(c["lc"]) >= 1)
    ch_sql   = series(hist, lambda c: rank(c["lc"]) >= 3)
    ch_opp   = series(hist, lambda c: c["lc"] == "opportunity", compkey)  # empresas oportunidad
    ch_cli   = series(hist, lambda c: c["lc"] == "customer", compkey)     # empresas cliente

    def peak_insight(items, pred, origin=True):
        """Mejor pico (día de mayor incremento) de CADA mes, con su origen dominante."""
        from collections import Counter
        inc = [0]*len(days)
        chc = [Counter() for _ in days]
        cmp = [Counter() for _ in days]
        for it in items:
            if it["created"] in idx and pred(it):
                i = idx[it["created"]]; inc[i] += 1
                if origin and it.get("src"):
                    chc[i][classify_channel(it["src"], it["d1"])[0]] += 1
                    if it["d1"]:
                        cmp[i][it["d1"]] += 1
        # mejor día por mes
        best = {}  # month -> index
        for i, day in enumerate(days):
            if inc[i] <= 0:
                continue
            m = day.month
            if m not in best or inc[i] > inc[best[m]]:
                best[m] = i
        if not best:
            return "Sin picos relevantes en el período."
        parts = []
        for m in sorted(best):
            i = best[m]; day = days[i]; delta = inc[i]
            s = f'<strong>{MESES3[day.month-1]} {day.day}</strong> +{delta}'
            tc = chc[i].most_common(1)
            if tc:
                s += f' · {round(tc[0][1]/delta*100)}% {esc(tc[0][0])}'
            parts.append(s)
        return "📌 Mejor pico por mes: " + " · ".join(parts)

    # ── Canales (diario) con desglose lead/SQL/freemium ──
    chan = {}
    for c in daily:
        label, icon, color = classify_channel(c["src"], c["d1"])
        e = chan.setdefault(label, {"n": 0, "lead": 0, "sql": 0, "free": 0, "icon": icon, "color": color})
        e["n"] += 1
        if c["lc"] in SQL_STAGES: e["sql"] += 1
        elif is_free(c): e["free"] += 1
        else: e["lead"] += 1
    for lbl, fd in FIXED_CHANNELS.items():
        if lbl not in chan:
            chan[lbl] = {"n": 0, "lead": 0, "sql": 0, "free": 0, "icon": fd["icon"], "color": fd["color"]}
    channels = sorted(chan.items(), key=lambda x: (-x[1]["n"], x[0]))

    # ── SQL del día (seguimiento de ventas) ──
    sql_rows = []
    for c in daily:
        if c["lc"] in SQL_STAGES:
            label, _, _ = classify_channel(c["src"], c["d1"])
            name = c["firstname"] or (c["email"].split("@")[0] if c["email"] else "—")
            sql_rows.append({"name": name, "company": c["company"], "channel": label,
                             "state": c["sql_state"] or "Pendiente", "rev": c["rev"] or "Pendiente de revisión"})
    sql_rows.sort(key=lambda r: r["channel"])

    # ── Razón de descarte/descalificación UNIFICADA (contacto razon_descarte_sql + deal motivo_de_descalificacion) ──
    drz = {}
    def add_reason(raw):
        if not raw:
            return
        label = UNIFY_DESCARTE.get(raw, raw)
        drz[label] = drz.get(label, 0) + 1
    # Acumulado desde el 1 de enero (chart_iso): contactos/deals creados en el período con razón registrada.
    try:
        for c in fetch_all("contacts",
                           [{"propertyName": "razon_descarte_sql", "operator": "HAS_PROPERTY"},
                            {"propertyName": "createdate", "operator": "GTE", "value": chart_iso}],
                           ["razon_descarte_sql"]):
            add_reason(c["properties"].get("razon_descarte_sql"))
    except Exception as e:
        print(f"  razon_descarte_sql error: {e}")
    try:
        for dl in fetch_all("deals",
                            [{"propertyName": "motivo_de_descalificacion", "operator": "HAS_PROPERTY"},
                             {"propertyName": "createdate", "operator": "GTE", "value": chart_iso}],
                            ["motivo_de_descalificacion"]):
            add_reason(dl["properties"].get("motivo_de_descalificacion"))
    except Exception as e:
        print(f"  motivo_de_descalificacion error: {e}")
    descarte = sorted(drz.items(), key=lambda x: -x[1])

    # ── Pipeline (deals abiertos, solo marketing) ──
    nuevos_ids = {d["id"] for d in open_deals if d["created"] >= dstart}
    demos_pipeline = sum(1 for d in open_deals if d["stage"] == "presentationscheduled")
    chan_dist = {}
    for d in open_deals:
        chan_dist[d["channel"]] = chan_dist.get(d["channel"], 0) + 1

    data = {
        "title": title, "fecha_larga": fecha_larga, "periodo_txt": periodo_txt,
        "fun_label": f"{funnel_start.day} {MESES3[funnel_start.month-1]} {funnel_start.year} → hoy",
        "chart_label": f"{d0.day} {MESES3[d0.month-1]} {d0.year} → hoy",
        "cum": cum, "agenda_cum": agenda_cum, "dd": dd, "agenda_day": agenda_day, "calls_day": calls_day,
        "meet_names": meet_names,
        "svg_leads": svg_cumulative(*ch_leads, labels, "#FF6B5B"),
        "svg_sql": svg_cumulative(*ch_sql, labels, "#f59e0b"),
        "svg_opp": svg_cumulative(*ch_opp, labels, "#10b981"),
        "svg_cli": svg_cumulative(*ch_cli, labels, "#22d3ee"),
        "peak_leads": peak_insight(hist, lambda c: rank(c["lc"]) >= 1),
        "peak_sql": peak_insight(hist, lambda c: rank(c["lc"]) >= 3),
        "peak_opp": peak_insight(hist, lambda c: c["lc"] == "opportunity"),
        "peak_cli": peak_insight(hist, lambda c: c["lc"] == "customer"),
        "channels": channels, "sql_rows": sql_rows, "sql_disp": sql_disp,
        "mkt_deals": open_deals, "mkt_total": len(open_deals),
        "nuevos_ids": nuevos_ids, "nuevos_deals": len(nuevos_ids),
        "demos_pipeline": demos_pipeline, "chan_dist": chan_dist, "descarte": descarte,
        "brain_count": brain_count, "ventas_count": ventas_count,
        "excl_tests": tests, "excl_internal": internal, "excl_imports": imports,
        "generado": es_now.strftime("%d %b %Y · %H:%M"),
    }
    html = render(data)
    with open(out_file, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"OK · hist_contactos={cum['total']} sql={cum['sql']} opp={cum['opp']} cli={cum['cli']} "
          f"| dia_contactos={dd['total']} lead={dd['lead']} sql={dd['sql']} free={dd['free']} "
          f"agenda_dia={agenda_day} deals={len(open_deals)} empresas_opp={opp_cum} empresas_cli={cli_cum}")


# ─────────────── Render ───────────────
def render(d):
    cum, dd = d["cum"], d["dd"]

    # ── Pirámides (embudo completo desde Contactos) ──
    def txt_color(hexc):
        h = hexc.lstrip("#"); r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        return "#3a0f08" if (0.299*r + 0.587*g + 0.114*b) > 165 else "#fff"
    def pyramid(steps, palette, split):
        top = steps[0][1] or 1
        rows = ""
        for i, (label, val, note) in enumerate(steps):
            w = max(40, round(val / top * 100)) if top else 40
            color = palette[min(i, len(palette)-1)]
            note_html = f'<div class="pyr-conv">{note}</div>' if note else ""
            # marca de separación entre grupo acumulativo y evolutivo
            if i == split:
                note_html = '<div class="pyr-split">↓ empiezan a convertir (evolutivo)</div>' + note_html
            rows += (f'{note_html}<div class="pyr-row"><div class="pyr-bar" '
                     f'style="width:{w}%;background:{color};color:{txt_color(color)}">'
                     f'<span class="pyr-val">{val}</span> <span class="pyr-lbl">{esc(label)}</span>'
                     f'</div></div>')
        return rows

    # Acumulativos (casi directos) en tono CLARO · evolutivos (convierten) en tono FUERTE oscuro→claro
    # Ventas: Contactos/Leads/MQL (claro) | SQL/Oportunidad/Cliente (fuerte)
    sales_pal = ["#FBD5CE", "#F7C0B7", "#F3ABA0",   # acumulativos (salmón claro)
                 "#B23320", "#E8543F", "#FF8B7D"]   # evolutivos (salmón fuerte oscuro→claro)
    # Freemium: Contactos/Freemium (claro) | Oportunidad/Cliente (fuerte)
    free_pal  = ["#BFEAF4", "#8FDDEE",                                 # acumulativos (teal claro)
                 "#0E7490", "#22D3EE"]                                 # evolutivos (teal oscuro→claro)

    t = cum["total"]
    sales_steps = [
        ("Contactos", t, ""),
        ("Leads", cum["lead"], f'{pct(cum["lead"], t)} del total'),
        ("MQL", cum["mql"], f'{pct(cum["mql"], cum["lead"])} de leads'),
        ("SQL Consultoría", cum["sql"], f'{pct(cum["sql"], cum["lead"])} de leads'),
        ("Oportunidad", cum["opp"], f'▼ {pct(cum["opp"], cum["sql"])} de SQL'),
        ("Cliente", cum["cli"], f'▼ {pct(cum["cli"], cum["opp"])} de oport.'),
    ]
    free_steps = [
        ("Contactos", t, ""),
        ("Freemium", cum["free"], f'{pct(cum["free"], t)} del total'),
        ("Oportunidad", 0, "—"),
        ("Cliente", 0, "—"),
    ]
    sales_pyr = pyramid(sales_steps, sales_pal, split=3)   # SQL en adelante = evolutivo
    free_pyr = pyramid(free_steps, free_pal, split=2)       # Oportunidad en adelante = evolutivo

    # ── Flujo del contacto al cliente (proceso + estados + conversión) ──
    sd = d["sql_disp"]
    flow_stages = [
        ("Contactos", t, "", "Todos los que entran en el CRM. Excluye test, empleados @gurusup e importaciones.", "", "#7b76a0"),
        ("Leads", cum["lead"], pct(cum["lead"], t), "Muestran interés real: descargan contenido, rellenan formulario o escriben por el chat.", "del total", "#F3ABA0"),
        ("MQL", cum["mql"], pct(cum["mql"], cum["lead"]), "Cualificados por marketing: encajan con el perfil objetivo.", "de leads", "#EF8A78"),
        ("SQL", cum["sql"], pct(cum["sql"], cum["lead"]), "Piden demo o cualifican por volumen de consultas (>3.000 · <3.000 · «no lo sé»).", "de leads", "#E8543F"),
        ("Oportunidad", cum["opp"], pct(cum["opp"], cum["sql"]), "Empresas con un deal activo en el pipeline de ventas.", "de SQL · empresas", "#C0392B"),
        ("Cliente", cum["cli"], pct(cum["cli"], cum["opp"]), "Empresas que han cerrado como cliente.", "de oport. · empresas", "#8E2A1E"),
    ]
    flow_html = '<div class="flow-track">'
    for i, (name, val, conv, why, base, color) in enumerate(flow_stages):
        if i > 0:
            flow_html += f'<div class="flow-arrow"><span class="fa-pct">{conv}</span><span class="fa-base">{base}</span></div>'
        flow_html += (f'<div class="fstage" style="border-top-color:{color}">'
                      f'<div class="fs-count" style="color:{color}">{val}</div>'
                      f'<div class="fs-name">{esc(name)}</div>'
                      f'<div class="fs-why">{esc(why)}</div></div>')
    flow_html += '</div>'

    # Rama: estado / disposición de los SQL
    st = sd["total"] or 1
    resueltos = sd["gestionado"] + sd["descartado"] or 1
    top_raz = " · ".join(f'{esc(r)} ({n})' for r, n in d["descarte"][:3]) or "sin razón registrada"
    flow_branch = (
        '<div class="flow-branch">'
        f'<div class="fb-head">📌 De los <b>{sd["total"]} SQL</b>, ¿en qué punto están?</div>'
        '<div class="fb-states">'
        f'<div class="fb-state ok"><div class="fbs-n">{sd["gestionado"]}</div><div class="fbs-l">🟢 Gestionados</div>'
        f'<div class="fbs-p">{pct(sd["gestionado"], st)} de los SQL</div><small>contactados por ventas (llamada / email)</small></div>'
        f'<div class="fb-state pend"><div class="fbs-n">{sd["pendiente"]}</div><div class="fbs-l">🟡 Pendientes</div>'
        f'<div class="fbs-p">{pct(sd["pendiente"], st)} de los SQL</div><small>aún sin revisar / asignar</small></div>'
        f'<div class="fb-state bad"><div class="fbs-n">{sd["descartado"]}</div><div class="fbs-l">🔴 Descartados</div>'
        f'<div class="fbs-p">{pct(sd["descartado"], st)} de los SQL</div><small>no cualifican</small></div>'
        '</div>'
        '<div class="fb-demo">📅 <b>Agendar demo:</b> los SQL gestionados se citan por 📞 <b>llamada</b> o ✉️ <b>email que agenda en calendario</b> (Agustín / Juanma) → si cualifican pasan a <b>Oportunidad</b>.</div>'
        '<div class="fb-conv">'
        f'<div class="fbc ok">✅ <b>{pct(cum["opp"], cum["sql"])}</b> de los SQL pasan a <b>Oportunidad</b></div>'
        f'<div class="fbc bad">❌ <b>{pct(sd["descartado"], resueltos)}</b> de los SQL resueltos se <b>descartan</b></div>'
        '</div>'
        f'<div class="fb-raz">🔍 <b>Principales razones de descarte:</b> {top_raz}. <span class="fb-raz-more">(detalle completo más abajo)</span></div>'
        '</div>')
    flow_full = flow_html + flow_branch

    # Resumen 24h · KPIs (% sobre el total de contactos, NO es un embudo)
    dtot = dd["total"]
    def dcard(label, val, sub, cls="f-c-default"):
        return f'<div class="f-card {cls}"><div class="fc-label">{label}</div><div class="fc-value">{val}</div><div class="fc-sub">{sub}</div></div>'
    day_cards = "".join([
        dcard("Contactos", dtot, "últimas 24h"),
        dcard("Leads", dd["lead_pure"], f'{pct(dd["lead_pure"], dtot)} del total'),
        dcard("SQL Consultoría", dd["sql"], f'{pct(dd["sql"], dtot)} del total', "f-c-orange"),
        dcard("Freemium", dd["free"], f'{pct(dd["free"], dtot)} del total', "f-c-teal"),
        dcard("Reuniones y llamadas", d["agenda_day"], f'{max(d["agenda_day"]-d["calls_day"],0)} agendadas · {d["calls_day"]} llamadas', "f-c-green"),
        dcard("Oportunidades", dd["opp"], f'{pct(dd["opp"], dtot)} del total'),
    ])
    day_funnel = day_cards

    # Canales
    ch_cards = ""
    for label, c in d["channels"]:
        p = pct(c["n"], dd["total"]) if c["n"] > 0 else "—"
        dim = "" if c["n"] > 0 else ";opacity:.45"
        parts = []
        if c["lead"]: parts.append(f'{c["lead"]} lead')
        if c["sql"]:  parts.append(f'{c["sql"]} SQL')
        if c["free"]: parts.append(f'{c["free"]} freem')
        br = " · ".join(parts) or "—"
        note = '<div class="ch-note">🍪 No aceptaron cookies (origen no rastreable)</div>' if label == "Otros" else ""
        ch_cards += (f'<div class="ch-card" style="--chc:{c["color"]}{dim}">'
                     f'<div class="ch-icon">{c["icon"]}</div><div class="ch-num">{c["n"]}</div>'
                     f'<div class="ch-label">{esc(label)}</div>'
                     f'<div class="ch-pct">{p} del total</div>'
                     f'<div class="ch-sql">{br}</div>{note}</div>\n')

    # Estado SQL (tabla)
    if d["sql_rows"]:
        call_rows = ""
        for r in d["sql_rows"]:
            emp = esc(r["company"]) if r["company"] else "—"
            desc = "" if r["rev"] != "No aplica / Descartado" else ' · <span style="color:var(--red)">descartado</span>'
            call_rows += (f'<tr><td><strong>{esc(r["name"])}</strong></td>'
                          f'<td>{emp} · <em>{esc(r["channel"])}</em></td>'
                          f'<td><span class="pill pill-demo">{esc(r["state"])}</span>{desc}</td></tr>')
    else:
        call_rows = '<tr><td colspan="3" style="color:var(--muted)">Sin SQL en el período</td></tr>'

    # Razones de descarte SQL (ordenadas por volumen)
    proceso = ('<br><br>⚙️ Se registran automáticamente tras el contacto de Agustín (ver «Flujo de precualificación»). '
               'Si la razón no se reconoce, salta una <strong>alerta para validar/añadir una nueva razón</strong> identificada por IA. '
               'Acumulativo desde el 1 de enero.')
    if d["descarte"]:
        mx = d["descarte"][0][1]; tot = sum(n for _, n in d["descarte"])
        top_reason, top_n = d["descarte"][0]
        # Cabecera con los tres datos clave de un vistazo
        descarte_html = (
            '<div class="drz-head">'
            f'<div class="drz-stat"><b>{tot}</b><span>descartes totales<br>desde el 1 de enero</span></div>'
            f'<div class="drz-stat"><b>{len(d["descarte"])}</b><span>razones distintas<br>registradas</span></div>'
            f'<div class="drz-stat drz-stat-top"><b>{pct(top_n, tot)}</b><span>razón principal<br>{esc(top_reason)}</span></div>'
            '</div>')
        for i, (reason, n) in enumerate(d["descarte"]):
            w = max(6, round(n / mx * 100))
            top = " drz-bar-top" if i == 0 else ""
            descarte_html += (f'<div class="drz-row"><div class="drz-rank">{i+1}</div>'
                              f'<div class="drz-l">{esc(reason)}</div>'
                              f'<div class="drz-barwrap"><div class="drz-bar{top}" style="width:{w}%"></div></div>'
                              f'<div class="drz-n">{n} <span class="drz-pct">{pct(n, tot)}</span></div></div>')
        descarte_note = (f'Volumen total: <strong>{tot}</strong> descartes con razón registrada <strong>desde el 1 de enero</strong> · '
                         'ordenados de mayor a menor peso, con su % sobre el total. '
                         'Unifica «Razón descarte SQL» (contacto) y «Motivo de descalificación» (deal).' + proceso)
    else:
        descarte_html = ('<div style="color:var(--muted);font-size:13px;padding:6px 0">Aún no hay descartes '
                         'registrados. Se poblará automáticamente según ventas los registre.</div>')
        descarte_note = ('Catálogo de razones definidas: precio/presupuesto · volumen insuficiente · caso de uso/no target · '
                         'sin autoridad/no cualificado · timing · competidor · build vs buy · lead accidental.' + proceso)

    # Pipeline
    by_stage = {}
    for deal in d["mkt_deals"]:
        by_stage.setdefault(deal["stage"], []).append(deal)
    deal_rows = ""
    for st_id, label, pill in STAGE_LABELS:
        # Ordenadas por fecha de reunión, de más cercana a más lejana (sin fecha al final)
        group = sorted(by_stage.get(st_id, []), key=lambda x: (x.get("mtg_sort", float("inf")), x["channel"]))
        if not group:
            continue
        deal_rows += f'<tr class="stage-divider"><td colspan="4">{esc(label)} · {len(group)} deals</td></tr>'
        for deal in group:
            nt = ' <span class="new-tag">NUEVO</span>' if deal["id"] in d["nuevos_ids"] else ""
            if deal.get("mtg_txt"):
                cls = "dt-next" if deal.get("mtg_future") else "dt-past"
                fecha_td = f'<td class="{cls}">{esc(deal["mtg_txt"])}</td>'
            else:
                fecha_td = '<td class="dt-none">—</td>'
            deal_rows += (f'<tr data-name="{esc(deal["name"].lower())}"><td><strong>{esc(deal["name"])}</strong>{nt}</td>'
                          f'<td>{esc(deal["channel"])}</td><td><span class="pill {pill}">{esc(label)}</span></td>'
                          f'{fecha_td}</tr>')
    chan_dist_txt = " · ".join(f"{n} {esc(lbl)}" for lbl, n in sorted(d["chan_dist"].items(), key=lambda x: -x[1])) or "—"

    return TEMPLATE.format(
        title=esc(d["title"]), fecha_larga=esc(d["fecha_larga"]), periodo_txt=esc(d["periodo_txt"]),
        fun_label=esc(d["fun_label"]), chart_label=esc(d["chart_label"]),
        sales_pyr=sales_pyr, free_pyr=free_pyr, flow_full=flow_full,
        svg_leads=d["svg_leads"], svg_sql=d["svg_sql"], svg_opp=d["svg_opp"], svg_cli=d["svg_cli"],
        peak_leads=d["peak_leads"], peak_sql=d["peak_sql"], peak_opp=d["peak_opp"], peak_cli=d["peak_cli"],
        day_funnel=day_funnel, d_free=dd["free"], d_free_pct=pct(dd["free"], dd["total"]), d_total=dd["total"],
        meet_names=d["meet_names"], calls_day=d["calls_day"], ch_cards=ch_cards, call_rows=call_rows,
        descarte_html=descarte_html, descarte_note=descarte_note, deal_rows=deal_rows,
        mkt_total=d["mkt_total"], nuevos_deals=d["nuevos_deals"], demos_pipeline=d["demos_pipeline"],
        brain_count=d["brain_count"], ventas_count=d["ventas_count"],
        chan_dist_txt=chan_dist_txt,
        excl_tests=d["excl_tests"], excl_internal=d["excl_internal"], excl_imports=d["excl_imports"],
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
  --guru-900:#0a0618; --guru-500:#FF6B5B; --guru-400:#E55A4C; --guru-300:#FAE5DC;
  --surface:#161330; --card:#1e1b42; --border:#2e2a5a;
  --green:#10b981; --amber:#f59e0b; --red:#ef4444; --blue:#3b82f6; --orange:#f97316;
  --teal:#22d3ee; --text:#f0edff; --text-2:#c4bfe0; --muted:#7b76a0;
}}
*,*::before,*::after {{ box-sizing:border-box; margin:0; padding:0; }}
html {{ font-size:15px; }}
body {{ background:var(--guru-900); color:var(--text); font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','Inter',sans-serif; line-height:1.5; min-height:100vh; }}
.header {{ position:sticky; top:0; z-index:100; background:rgba(17,14,42,.96); backdrop-filter:blur(16px); border-bottom:1px solid var(--border); padding:0 24px; }}
.header-inner {{ display:flex; align-items:center; gap:16px; padding:14px 0 12px; flex-wrap:wrap; }}
.logo-box {{ width:40px; height:40px; background:linear-gradient(135deg,var(--guru-500),var(--guru-400)); border-radius:10px; display:flex; align-items:center; justify-content:center; font-weight:800; font-size:15px; color:#fff; flex-shrink:0; box-shadow:0 0 16px rgba(255,107,91,.4); }}
.header-title {{ flex:1; min-width:180px; }}
.header-title h1 {{ font-size:16px; font-weight:700; }}
.header-title p {{ font-size:12px; color:var(--muted); }}
.live-badge {{ background:rgba(16,185,129,.12); border:1px solid rgba(16,185,129,.3); color:var(--green); font-size:11px; font-weight:600; padding:4px 10px; border-radius:20px; display:flex; align-items:center; gap:5px; white-space:nowrap; }}
.live-dot {{ width:6px; height:6px; border-radius:50%; background:var(--green); animation:pulse 2s infinite; }}
@keyframes pulse {{ 0%,100%{{opacity:1}} 50%{{opacity:.3}} }}
.sync-bar {{ font-size:11px; color:var(--muted); padding:5px 24px 6px; border-top:1px solid rgba(46,42,90,.6); background:rgba(17,14,42,.7); }}
.main {{ max-width:1160px; margin:0 auto; padding:24px 20px 60px; }}
.section-label {{ font-size:11px; font-weight:700; letter-spacing:.1em; text-transform:uppercase; color:var(--muted); margin:32px 0 14px; }}
.section-label:first-child {{ margin-top:0; }}
.glossary {{ background:var(--card); border:1px solid var(--border); border-radius:12px; padding:4px 18px; margin-bottom:26px; }}
.glossary summary {{ cursor:pointer; list-style:none; padding:12px 0; font-size:14px; font-weight:700; color:var(--text); display:flex; align-items:center; gap:8px; }}
.glossary summary::-webkit-details-marker {{ display:none; }}
.glossary summary::after {{ content:"▸"; margin-left:auto; color:var(--muted); transition:transform .2s; }}
.glossary[open] summary::after {{ transform:rotate(90deg); }}
.glossary .gl-ico {{ font-size:16px; }}
.glossary .gl-hint {{ font-weight:400; font-size:11px; color:var(--muted); }}
.gl-grid {{ display:grid; grid-template-columns:repeat(2,1fr); gap:10px; padding:6px 0 16px; }}
@media(max-width:760px){{ .gl-grid {{ grid-template-columns:1fr; }} }}
.gl-card {{ background:rgba(255,255,255,.03); border:1px solid var(--border); border-radius:9px; padding:11px 13px; }}
.gl-card b {{ display:block; font-size:13px; color:var(--guru-300); margin-bottom:3px; }}
.gl-card .gl-en {{ font-weight:400; font-size:11px; color:var(--muted); }}
.gl-card span {{ font-size:12px; color:var(--text-2); line-height:1.45; }}

/* Banda etapas de ciclo de vida */
.lc-band {{ display:flex; flex-wrap:wrap; align-items:center; gap:20px; background:var(--card); border:1px solid var(--border); border-radius:14px; padding:18px 22px; }}
.lc-total {{ display:flex; align-items:center; gap:14px; padding-right:20px; border-right:1px solid var(--border); }}
.lc-total .n {{ font-size:46px; font-weight:800; line-height:1; color:var(--guru-300); }}
.lc-total .t {{ font-size:12px; font-weight:700; color:var(--text-2); text-transform:uppercase; letter-spacing:.06em; line-height:1.3; }}
.lc-total .t span {{ font-weight:600; color:var(--muted); text-transform:none; letter-spacing:0; }}
.lc-stages {{ display:flex; gap:12px; flex-wrap:wrap; flex:1; }}
.lc-stage {{ flex:1; min-width:120px; background:rgba(255,255,255,.03); border:1px solid var(--border); border-radius:10px; padding:12px 14px; position:relative; overflow:hidden; }}
.lc-stage::before {{ content:''; position:absolute; top:0; left:0; bottom:0; width:3px; background:var(--sc,var(--guru-500)); }}
.lc-stage .lc-n {{ font-size:26px; font-weight:800; line-height:1; color:var(--sc,var(--text)); }}
.lc-stage .lc-l {{ font-size:12px; font-weight:600; color:var(--text-2); margin-top:4px; }}
.lc-stage .lc-s {{ font-size:11px; color:var(--muted); margin-top:2px; }}
/* Separador de flujo */
.flow-sep {{ display:flex; align-items:center; gap:14px; margin:22px 2px 20px; }}
.flow-sep::before, .flow-sep::after {{ content:''; flex:1; height:1px; background:linear-gradient(90deg,transparent,var(--border),var(--border),transparent); }}
.flow-sep span {{ font-size:10px; font-weight:700; letter-spacing:.1em; text-transform:uppercase; color:var(--muted); white-space:nowrap; }}
.evo-banner {{ display:flex; align-items:center; justify-content:space-between; gap:14px; flex-wrap:wrap;
  margin:38px 0 18px; padding:16px 20px; border-radius:14px;
  background:linear-gradient(100deg, rgba(255,107,91,.16), rgba(34,211,238,.12));
  border:1px solid rgba(255,107,91,.35); box-shadow:0 0 24px rgba(255,107,91,.10); }}
.evo-l {{ display:flex; align-items:center; gap:14px; }}
.evo-ico {{ font-size:26px; }}
.evo-t {{ font-size:16px; font-weight:800; color:var(--text); letter-spacing:.01em; }}
.evo-s {{ font-size:12px; color:var(--text-2); margin-top:2px; }}
.evo-badge {{ font-size:11px; font-weight:800; letter-spacing:.08em; padding:6px 12px; border-radius:20px;
  background:var(--guru-500); color:#fff; white-space:nowrap; box-shadow:0 2px 8px rgba(255,107,91,.35); }}
@media(max-width:600px){{ .flow-sep span {{ white-space:normal; text-align:center; }} }}

/* Dos embudos */
.funnels-2 {{ display:grid; grid-template-columns:1fr 1fr; gap:18px; }}
@media(max-width:760px){{ .funnels-2 {{ grid-template-columns:1fr; }} }}
.funnels-1 {{ display:block; }}
.funnels-1 .fn-box {{ max-width:720px; margin:0 auto; }}
.fn-box {{ background:var(--card); border:1px solid var(--border); border-radius:14px; padding:18px 18px 20px; }}
.fn-title {{ font-size:13px; font-weight:800; margin-bottom:4px; }}
.fn-note {{ font-size:11px; color:var(--muted); margin-bottom:14px; }}
.pyramid {{ display:flex; flex-direction:column; align-items:center; }}
.pyr-row {{ width:100%; display:flex; justify-content:center; }}
.pyr-bar {{ border-radius:8px; padding:11px 12px; text-align:center; color:#fff; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; box-shadow:0 2px 8px rgba(0,0,0,.25); text-shadow:0 1px 2px rgba(0,0,0,.4); }}
.pyr-val {{ font-size:19px; font-weight:800; }}
.pyr-lbl {{ font-size:12px; font-weight:600; opacity:.95; }}
.pyr-conv {{ font-size:11px; font-weight:700; color:var(--muted); margin:5px 0; }}
.pyr-split {{ font-size:10px; font-weight:800; letter-spacing:.06em; text-transform:uppercase; color:var(--guru-300); margin:10px 0 6px; padding-top:8px; border-top:1px dashed var(--border); }}
.fn-highlight {{ margin-top:14px; background:rgba(34,211,238,.08); border:1px solid rgba(34,211,238,.25); color:#a5f3fc; border-radius:8px; padding:10px 12px; font-size:11px; line-height:1.5; }}
/* ── Flujo del contacto al cliente ── */
.flow-track {{ display:flex; align-items:stretch; gap:6px; overflow-x:auto; padding:4px 2px 10px; }}
.fstage {{ flex:1 1 0; min-width:135px; background:rgba(255,255,255,.03); border:1px solid var(--border); border-top:3px solid var(--muted); border-radius:10px; padding:12px 12px 13px; }}
.fs-count {{ font-size:26px; font-weight:800; line-height:1.05; }}
.fs-name {{ font-size:13px; font-weight:700; color:var(--text); margin:2px 0 6px; }}
.fs-why {{ font-size:11px; color:var(--muted); line-height:1.4; }}
.flow-arrow {{ flex:0 0 auto; align-self:center; display:flex; flex-direction:column; align-items:center; justify-content:center; padding:0 2px; }}
.flow-arrow::before {{ content:"→"; font-size:16px; color:var(--muted); }}
.fa-pct {{ font-size:12px; font-weight:800; color:var(--guru-300); }}
.fa-base {{ font-size:9px; color:var(--muted); white-space:nowrap; }}
.flow-branch {{ margin-top:16px; border-top:1px dashed var(--border); padding-top:16px; }}
.fb-head {{ font-size:13px; font-weight:700; margin-bottom:12px; }}
.fb-states {{ display:grid; grid-template-columns:repeat(3,1fr); gap:10px; }}
@media(max-width:640px){{ .fb-states {{ grid-template-columns:1fr; }} .flow-track {{ flex-direction:column; }} .flow-arrow::before {{ content:"↓"; }} .fstage {{ min-width:0; }} }}
.fb-state {{ border:1px solid var(--border); border-radius:10px; padding:12px 13px; background:rgba(255,255,255,.03); }}
.fb-state.ok {{ border-color:rgba(16,185,129,.35); background:rgba(16,185,129,.07); }}
.fb-state.pend {{ border-color:rgba(245,158,11,.35); background:rgba(245,158,11,.07); }}
.fb-state.bad {{ border-color:rgba(239,68,68,.35); background:rgba(239,68,68,.07); }}
.fbs-n {{ font-size:28px; font-weight:800; color:var(--text); line-height:1; }}
.fbs-l {{ font-size:13px; font-weight:700; margin-top:3px; }}
.fbs-p {{ font-size:11px; color:var(--muted); font-weight:600; }}
.fb-state small {{ display:block; font-size:11px; color:var(--muted); margin-top:5px; line-height:1.35; }}
.fb-demo {{ margin-top:14px; background:rgba(255,107,91,.07); border:1px solid rgba(255,107,91,.28); border-radius:9px; padding:11px 13px; font-size:12px; line-height:1.5; color:var(--text-2); }}
.fb-conv {{ display:flex; gap:10px; margin-top:12px; flex-wrap:wrap; }}
.fbc {{ flex:1; min-width:200px; border-radius:9px; padding:12px 14px; font-size:13px; }}
.fbc.ok {{ background:rgba(16,185,129,.1); border:1px solid rgba(16,185,129,.35); color:#a7f3d0; }}
.fbc.bad {{ background:rgba(239,68,68,.1); border:1px solid rgba(239,68,68,.35); color:#fecaca; }}
.fb-raz {{ margin-top:12px; font-size:12px; color:var(--text-2); line-height:1.5; }}
.fb-raz-more {{ color:var(--muted); }}

/* Gráficos */
.charts-2 {{ display:grid; grid-template-columns:repeat(2,1fr); gap:16px; }}
@media(max-width:720px){{ .charts-2 {{ grid-template-columns:1fr; }} }}
.chart-card {{ background:var(--card); border:1px solid var(--border); border-radius:12px; padding:16px 16px 10px; }}
.chart-card h3 {{ font-size:13px; font-weight:700; margin-bottom:2px; }}
.peak-note {{ font-size:11px; color:var(--text-2); margin-top:6px; padding-top:8px; border-top:1px solid var(--border); line-height:1.5; }}
.peak-note strong {{ color:var(--guru-300); }}
.chart-card .sub {{ font-size:10px; color:var(--muted); margin-bottom:8px; }}

/* Funnel horizontal 24h */
.funnel {{ display:flex; align-items:stretch; gap:0; }}
.f-arrow {{ display:flex; align-items:center; justify-content:center; width:30px; flex-shrink:0; }}
.f-arrow::after {{ content:'›'; color:var(--guru-400); font-weight:700; font-size:28px; }}
.f-card {{ flex:1; background:var(--card); border:1px solid var(--border); border-radius:10px; padding:14px 14px 12px; position:relative; overflow:hidden; min-width:0; }}
.f-card::before {{ content:''; position:absolute; top:0; left:0; right:0; height:3px; background:var(--fc,var(--guru-500)); }}
.fc-label {{ font-size:10px; color:var(--muted); font-weight:700; text-transform:uppercase; letter-spacing:.06em; }}
.fc-value {{ font-size:38px; font-weight:800; line-height:1; margin-top:4px; color:var(--fv,var(--text)); }}
.fc-sub {{ font-size:11px; color:var(--text-2); font-weight:600; margin-top:6px; }}
.f-c-default {{ --fc:var(--guru-500); --fv:var(--text); }}
.f-c-orange {{ --fc:var(--orange); --fv:var(--orange); }}
.f-c-green {{ --fc:var(--green); --fv:var(--green); }}
.f-c-teal {{ --fc:var(--teal); --fv:var(--teal); }}
.day-kpis {{ display:grid; grid-template-columns:repeat(6,1fr); gap:10px; }}
@media(max-width:900px){{ .day-kpis {{ grid-template-columns:repeat(3,1fr); }} }}
@media(max-width:520px){{ .day-kpis {{ grid-template-columns:repeat(2,1fr); }} }}
.free-kpi {{ margin-top:12px; background:var(--card); border:1px solid var(--border); border-radius:10px; padding:14px 16px; display:flex; align-items:baseline; gap:12px; }}
.free-kpi .fk-num {{ font-size:32px; font-weight:800; color:var(--teal); }}
.free-kpi .fk-txt {{ font-size:12px; color:var(--text-2); }}

.channels-grid {{ display:grid; grid-template-columns:repeat(7,1fr); gap:10px; }}
@media(max-width:900px){{ .channels-grid {{ grid-template-columns:repeat(3,1fr); }} }}
@media(max-width:550px){{ .channels-grid {{ grid-template-columns:repeat(2,1fr); }} }}
.ch-card {{ background:var(--card); border:1px solid var(--border); border-radius:10px; padding:14px 12px; position:relative; overflow:hidden; }}
.ch-card::before {{ content:''; position:absolute; top:0; left:0; right:0; height:3px; background:var(--chc,var(--guru-500)); }}
.ch-icon {{ font-size:17px; margin-bottom:5px; }}
.ch-num {{ font-size:28px; font-weight:800; line-height:1; color:var(--chc,var(--text)); }}
.ch-label {{ font-size:11px; font-weight:600; color:var(--text-2); margin-top:4px; }}
.ch-pct {{ font-size:10px; color:var(--muted); margin-top:2px; }}
.ch-sql {{ font-size:11px; font-weight:700; color:var(--text-2); margin-top:5px; }}
.ch-note {{ font-size:10px; color:var(--muted); margin-top:5px; line-height:1.35; font-style:italic; }}

.card {{ background:var(--card); border:1px solid var(--border); border-radius:12px; padding:20px 22px; margin-bottom:12px; }}
.card-header {{ display:flex; align-items:center; justify-content:space-between; margin-bottom:16px; }}
.card-title {{ font-size:14px; font-weight:700; }}
.badge {{ font-size:11px; font-weight:700; padding:3px 10px; border-radius:20px; }}
.badge-green {{ background:rgba(16,185,129,.15); color:var(--green); border:1px solid rgba(16,185,129,.3); }}
.table {{ width:100%; border-collapse:collapse; }}
.table th {{ font-size:11px; font-weight:700; color:var(--muted); text-transform:uppercase; letter-spacing:.06em; padding:0 12px 10px 0; text-align:left; border-bottom:1px solid var(--border); }}
.table td {{ font-size:13px; color:var(--text-2); padding:10px 12px 10px 0; border-bottom:1px solid rgba(46,42,90,.5); }}
.table td strong {{ color:var(--text); font-weight:600; }}
.table tr.stage-divider td {{ background:rgba(255,255,255,.03); font-size:10px; font-weight:700; text-transform:uppercase; color:var(--muted); padding:6px 0; }}
.pill {{ display:inline-block; font-size:11px; font-weight:600; padding:3px 9px; border-radius:20px; white-space:nowrap; }}
.pill-demo {{ background:rgba(16,185,129,.15); color:var(--green); }}
.pill-discov {{ background:rgba(255,107,91,.15); color:#F5D5C8; }}
.pill-best {{ background:rgba(245,158,11,.15); color:var(--amber); }}
.dt-next {{ font-weight:700; color:var(--guru-300); white-space:nowrap; }}
.dt-past {{ color:var(--muted); white-space:nowrap; }}
.dt-none {{ color:var(--muted); }}
.new-tag {{ font-size:10px; font-weight:700; padding:2px 7px; border-radius:10px; background:rgba(16,185,129,.2); color:var(--green); text-transform:uppercase; }}
.alert {{ border-radius:8px; padding:10px 14px; font-size:12px; margin-top:14px; display:flex; align-items:flex-start; gap:8px; }}
.alert-muted {{ background:rgba(123,118,160,.06); border:1px solid rgba(123,118,160,.2); color:var(--muted); }}
.caption {{ font-size:11px; color:var(--muted); margin-top:8px; line-height:1.6; }}
.drz-head {{ display:flex; gap:12px; margin-bottom:18px; flex-wrap:wrap; }}
.drz-stat {{ flex:1; min-width:150px; background:rgba(255,255,255,.03); border:1px solid var(--border); border-radius:10px; padding:12px 14px; }}
.drz-stat b {{ display:block; font-size:26px; font-weight:800; color:var(--text); line-height:1.1; }}
.drz-stat span {{ font-size:11px; color:var(--muted); line-height:1.35; display:block; margin-top:4px; }}
.drz-stat-top {{ background:rgba(255,107,91,.08); border-color:rgba(255,107,91,.35); }}
.drz-stat-top b {{ color:var(--guru-300); }}
.drz-row {{ display:flex; align-items:center; gap:10px; margin-bottom:9px; }}
.drz-rank {{ flex:0 0 22px; height:22px; line-height:22px; text-align:center; font-size:11px; font-weight:800; color:var(--muted); background:rgba(255,255,255,.05); border-radius:6px; }}
.drz-l {{ flex:0 0 38%; font-size:12px; color:var(--text-2); line-height:1.35; }}
.drz-barwrap {{ flex:1; background:rgba(255,255,255,.05); border-radius:5px; height:14px; overflow:hidden; }}
.drz-bar {{ height:14px; border-radius:5px; background:linear-gradient(90deg,var(--guru-500),var(--guru-400)); }}
.drz-bar-top {{ background:linear-gradient(90deg,#FF6B5B,#FF8A65); box-shadow:0 0 10px rgba(255,107,91,.35); }}
.drz-n {{ flex:0 0 74px; text-align:right; font-size:14px; font-weight:800; color:var(--guru-300); }}
.drz-pct {{ font-size:11px; color:var(--muted); font-weight:600; }}
@media(max-width:600px){{ .drz-l {{ flex-basis:46%; font-size:11px; }} .drz-stat b {{ font-size:22px; }} }}
/* Flujo de precualificación */
.preq {{ background:var(--card); border:1px solid var(--border); border-radius:14px; padding:20px; }}
.preq-top {{ text-align:center; font-size:15px; font-weight:700; color:var(--text); background:rgba(255,107,91,.12); border:1px solid rgba(255,107,91,.3); border-radius:10px; padding:12px; }}
.preq-arrow {{ text-align:center; font-size:11px; color:var(--muted); font-weight:700; letter-spacing:.04em; margin:10px 0; }}
.preq-branches {{ display:grid; grid-template-columns:1fr 1fr; gap:14px; }}
@media(max-width:640px){{ .preq-branches {{ grid-template-columns:1fr; }} }}
.preq-card {{ border-radius:12px; padding:16px; border:1px solid var(--border); }}
.preq-sales {{ background:rgba(255,107,91,.08); border-color:rgba(255,107,91,.35); }}
.preq-free {{ background:rgba(34,211,238,.08); border-color:rgba(34,211,238,.3); }}
.preq-h {{ font-size:13px; font-weight:800; margin-bottom:7px; }}
.preq-sales .preq-h {{ color:var(--guru-300); }}
.preq-free .preq-h {{ color:var(--teal); }}
.preq-b {{ font-size:12px; color:var(--text-2); line-height:1.55; }}
.preq-tag {{ display:inline-block; font-size:10px; font-weight:800; text-transform:uppercase; letter-spacing:.05em; padding:2px 8px; border-radius:20px; margin-bottom:8px; }}
.preq-sales .preq-tag {{ background:rgba(255,107,91,.2); color:var(--guru-300); }}
.preq-free .preq-tag {{ background:rgba(34,211,238,.18); color:var(--teal); }}

@media(max-width:600px){{
  .header {{ padding:0 14px; }} .header-title h1 {{ font-size:14px; }} .header-title p {{ font-size:10px; }}
  .live-badge {{ display:none; }} .main {{ padding:18px 14px 50px; }}
  .funnel {{ flex-direction:column; gap:8px; }} .f-arrow {{ width:100%; height:20px; transform:rotate(90deg); }}
  .fc-value {{ font-size:32px; }} .card {{ padding:16px 14px; overflow-x:auto; }} .table {{ min-width:300px; }}
  .section-label {{ font-size:10px; margin-top:26px; }}
}}
#gs-gate {{ position:fixed; inset:0; z-index:9999; background:#0a0618; display:flex; align-items:center; justify-content:center; }}
#gs-gate .box {{ background:#1e1b42; border:1px solid #2e2a5a; border-radius:16px; padding:40px 36px; width:340px; text-align:center; }}
#gs-gate .logo {{ width:48px; height:48px; border-radius:12px; margin:0 auto 20px; background:linear-gradient(135deg,#ff6b5b,#ff8b7d); display:flex; align-items:center; justify-content:center; font-weight:800; color:#fff; }}
#gs-gate h2 {{ font-size:18px; font-weight:700; margin-bottom:4px; }} #gs-gate p {{ font-size:13px; color:#7b76a0; margin-bottom:24px; }}
#gs-gate input {{ width:100%; padding:11px 14px; border-radius:8px; border:1px solid #2e2a5a; background:#161330; color:#f0edff; font-size:15px; margin-bottom:12px; outline:none; letter-spacing:.08em; }}
#gs-gate button {{ width:100%; padding:11px; border-radius:8px; border:none; cursor:pointer; background:linear-gradient(135deg,#ff6b5b,#ff8b7d); color:#fff; font-size:15px; font-weight:700; }}
#gs-gate .err {{ color:#ef4444; font-size:12px; margin-top:8px; display:none; }}
</style>
<script>
(function(){{
  if(sessionStorage.getItem('gs_ok')==='1') return;
  document.addEventListener('DOMContentLoaded', function(){{
    var g=document.getElementById('gs-gate'), i=document.getElementById('gs-pwd'),
        e=document.getElementById('gs-err'), b=document.getElementById('gs-btn');
    g.style.display='flex';
    function ck(){{ if(i.value==='radar2026'){{ sessionStorage.setItem('gs_ok','1'); g.style.display='none'; }}
      else {{ e.style.display='block'; i.value=''; i.focus(); }} }}
    b.addEventListener('click', ck); i.addEventListener('keydown', function(ev){{ if(ev.key==='Enter') ck(); }});
  }});
}})();
</script>
</head>
<body>
<div id="gs-gate" style="display:none"><div class="box"><div class="logo">GS</div>
  <h2>GuruSup · Dashboard Diario</h2><p>Acceso restringido</p>
  <input id="gs-pwd" type="password" placeholder="Contraseña" autofocus><button id="gs-btn">Entrar</button>
  <div id="gs-err" class="err">Contraseña incorrecta</div></div></div>

<div class="header"><div class="header-inner"><div class="logo-box">GS</div>
  <div class="header-title"><h1>{title}</h1><p>{fecha_larga} · {periodo_txt}</p></div>
  <span class="live-badge"><span class="live-dot"></span>Live · HubSpot</span></div>
  <div class="sync-bar">Generado el {generado} · embudos acumulados {fun_label} · gráficos anuales {chart_label}</div></div>

<div class="main">

  <details class="glossary">
    <summary><span class="gl-ico">📖</span> Minidiccionario · qué significa cada término <span class="gl-hint">(pulsa para desplegar)</span></summary>
    <div class="gl-grid">
      <div class="gl-card"><b>Contacto</b><span>Cualquier registro que entra en el CRM en el período. Excluye tests, empleados @gurusup e importaciones (salvo freemium).</span></div>
      <div class="gl-card"><b>Lead</b><span>Contacto con interés real que avanza en el ciclo de vida (etapa «lead» o superior). Es una métrica <em>acumulativa</em>: incluye a los que ya pasaron a etapas posteriores.</span></div>
      <div class="gl-card"><b>MQL <span class="gl-en">· Marketing Qualified Lead</span></b><span>Lead cualificado por marketing: encaja con el perfil objetivo, pero todavía no está listo para que ventas lo trabaje.</span></div>
      <div class="gl-card"><b>SQL <span class="gl-en">· Sales Qualified Lead</span></b><span>Lead validado como oportunidad real de negocio: pide demo y cualifica (p. ej. por volumen de consultas/mes). Se mide como <strong>% sobre leads</strong>.</span></div>
      <div class="gl-card"><b>Oportunidad</b><span>Empresa (no contacto) con un deal activo en el pipeline de ventas. Se cuenta como <strong>empresa única</strong>.</span></div>
      <div class="gl-card"><b>Cliente</b><span>Empresa que ha cerrado como cliente (customer). También se cuenta como empresa única.</span></div>
      <div class="gl-card"><b>Reunión agendada (al período)</b><span>Demos/discovery agendadas en la ventana de tiempo, más las llamadas de los SDR (Agustín/Juanma) del período.</span></div>
      <div class="gl-card"><b>Freemium</b><span>Alta gratuita por la app (autoservicio). No forma parte del embudo comercial; por eso no cuenta como lead ni oportunidad.</span></div>
      <div class="gl-card"><b>Descarte / descualificación</b><span>SQL que no avanza. Se registra siempre el <strong>motivo</strong> (precio, volumen, timing, etc.) para analizar patrones.</span></div>
      <div class="gl-card"><b>Pipeline</b><span>Conjunto de oportunidades (empresas) abiertas por etapa: Discovery → Demo/Reunión → Best Case → Cliente.</span></div>
    </div>
  </details>

  <div class="section-label">Contactos generados · últimas 24h</div>
  <div class="day-kpis">{day_funnel}</div>
  <div class="caption">ℹ️ No es un embudo: cada valor es el <strong>% sobre el total de contactos</strong> generados en las últimas 24h. · <strong>Reuniones y llamadas</strong> = reuniones agendadas (demos) + llamadas de los SDR (Agustín/Juanma): <strong>{calls_day}</strong> llamadas hoy · Reuniones hoy: {meet_names}</div>

  <div class="section-label">Canales de adquisición · últimas 24h</div>
  <div class="channels-grid">{ch_cards}</div>

  <div class="section-label">Flujo de precualificación de nuevos contactos</div>
  <div class="preq">
    <div class="preq-top">📩 Nuevo contacto pide <strong>demo</strong> → se evalúa su <strong>volumen de consultas/mes</strong></div>
    <div class="preq-arrow">▼ ▼ ▼</div>
    <div class="preq-branches">
      <div class="preq-card preq-sales">
        <div class="preq-tag">A ventas</div>
        <div class="preq-h">➕ +3.000 consultas/mes · o «no conozco el volumen»</div>
        <div class="preq-b">Pasa <strong>directo a Agustín</strong> (responsable de seguimiento inbound) con la <strong>preferencia de canal de contacto</strong>. Contacto por llamada o email; si no cualifica, se registra la <strong>razón de descarte</strong>.</div>
      </div>
      <div class="preq-card preq-free">
        <div class="preq-tag">Automatizado</div>
        <div class="preq-h">➖ −3.000 consultas/mes</div>
        <div class="preq-b"><strong>Email automatizado</strong> de agradecimiento y se <strong>descarta</strong>. Ya no se deriva a Freemium.</div>
      </div>
    </div>
  </div>

  <div class="section-label">Seguimiento de ventas · estado de los SQL · últimas 24h</div>
  <div class="card">
    <div class="card-header"><span class="card-title">SQL del período · empresa, canal y estado</span>
      <span class="badge badge-green">📞 Seguimiento comercial</span></div>
    <table class="table"><thead><tr><th>SQL</th><th>Empresa · canal</th><th>Estado</th></tr></thead>
    <tbody>{call_rows}</tbody></table>
    <div class="alert alert-muted"><span>ℹ️</span><div>Estado tomado de «Estado SQL Consultoría» y «Revisión ventas».</div></div>
  </div>

  <div class="section-label">Razones de descarte / descualificación de SQL · acumulado desde el 1 de enero</div>
  <div class="card">
    <div class="drz">{descarte_html}</div>
    <div class="alert alert-muted"><span>💬</span><div>{descarte_note}</div></div>
  </div>

  <div class="evo-banner">
    <div class="evo-l"><span class="evo-ico">📈</span><div><div class="evo-t">Evolutivo anual · datos acumulados</div><div class="evo-s">Todo lo que sigue suma el histórico desde el 1 de enero de 2026</div></div></div>
    <span class="evo-badge">ACUMULADO · {chart_label}</span>
  </div>

  <div class="section-label">Flujo del contacto al cliente · proceso y conversión · acumulado {fun_label}</div>
  <div class="fn-box">
    <div class="fn-title">🔄 Del contacto al cliente</div>
    <div class="fn-note">Cada etapa, por qué se clasifica así, su volumen y el % de conversión respecto a la etapa anterior</div>
    {flow_full}
  </div>
  <div class="caption">ℹ️ Cómo leer el embudo: <strong>«Leads» y «MQL» son acumulativos</strong> —incluyen a los contactos que ya avanzaron a etapas posteriores (SQL, oportunidad o cliente)—, por eso cada etapa es menor que la anterior. <strong>«Oportunidad» y «Cliente» se cuentan como empresas únicas</strong> (una por compañía), no como contactos; por eso no suman contra los contactos/leads. <strong>MQL y SQL se calculan como % sobre leads</strong> (no sobre el total de contactos, que incluye freemium y no forma parte del embudo comercial).
    <br><br><strong>¿Qué contactos NO llegan a Lead?</strong>
    <br>• Ya excluidos <em>antes</em> de contar (no están en el total): <strong>{excl_tests}</strong> test/prueba · <strong>{excl_internal}</strong> internos @gurusup (empleados) · <strong>{excl_imports}</strong> de integraciones/importaciones <em>(salvo freemium, que sí se cuentan)</em>.
    <br>• Dentro de los contactos contados, los que no pasan a Lead son sobre todo <strong>freemium</strong> (altas por la app) y <strong>suscriptores / sin etapa asignada</strong>.</div>

  <div class="section-label">Evolución anual acumulada · {chart_label}</div>
  <div class="charts-2">
    <div class="chart-card"><h3>Leads generados</h3><div class="sub">acumulado diario · anual</div>{svg_leads}<div class="peak-note">{peak_leads}</div></div>
    <div class="chart-card"><h3>SQL Consultoría</h3><div class="sub">acumulado diario · anual</div>{svg_sql}<div class="peak-note">{peak_sql}</div></div>
    <div class="chart-card"><h3>Oportunidades <span style="font-weight:400;color:var(--muted)">· empresas</span></h3><div class="sub">acumulado diario · anual</div>{svg_opp}<div class="peak-note">{peak_opp}</div></div>
    <div class="chart-card"><h3>Clientes <span style="font-weight:400;color:var(--muted)">· empresas</span></h3><div class="sub">acumulado diario · anual</div>{svg_cli}<div class="peak-note">{peak_cli}</div></div>
  </div>

  <div class="section-label">Oportunidades activas · Pipeline de ventas · solo canales de marketing</div>
  <div class="card">
    <div class="card-header"><span class="card-title">Empresas en pipeline · por canal y etapa</span>
      <span class="badge badge-green">{mkt_total} oportunidades de marketing</span></div>
    <div style="font-size:12px;color:var(--text-2);margin:-6px 0 14px;line-height:1.5;">
      🧠 <strong style="color:var(--guru-300)">{brain_count}</strong> en Pipeline <strong>Brain</strong> (GuruSup / Company Brain) ·
      💼 <strong style="color:var(--guru-300)">{ventas_count}</strong> en <strong>ventas normales</strong></div>
    <input type="text" id="emp-search" onkeyup="filtrarEmpresas()" placeholder="🔍 Buscar empresa…"
      style="width:100%;padding:10px 14px;border-radius:8px;border:1px solid var(--border);background:var(--surface);color:var(--text);font-size:14px;margin-bottom:14px;outline:none;">
    <table class="table" id="emp-table"><thead><tr><th>Empresa</th><th>Canal</th><th>Etapa</th><th>📅 Reunión</th></tr></thead>
    <tbody>{deal_rows}</tbody></table>
    <div id="emp-empty" style="display:none;padding:14px 0;font-size:13px;color:var(--muted);text-align:center;">Sin resultados</div>
    <div class="alert alert-muted"><span>ℹ️</span><div>Solo oportunidades cuyo contacto entró por canal de marketing. Reparto por canal: {chan_dist_txt}. Dentro de cada etapa se ordenan por <strong>fecha de reunión</strong> (discovery/demo), de la más próxima a la más lejana; en <span class="dt-next">salmón</span> las reuniones futuras.</div></div>
  </div>

  <div style="margin-top:40px;text-align:center;font-size:12px;color:var(--muted);">
    GuruSup · Dashboard Diario · generado el {generado} (hora España)
  </div>
</div>
<script>
window.filtrarEmpresas=function(){{
  var q=document.getElementById('emp-search').value.toLowerCase().trim();
  var rows=document.querySelectorAll('#emp-table tbody tr:not(.stage-divider)'), vis=0;
  rows.forEach(function(r){{ var n=r.querySelector('td strong'); var m=n&&n.textContent.toLowerCase().indexOf(q)!==-1;
    r.style.display=(!q||m)?'':'none'; if(!q||m) vis++; }});
  document.querySelectorAll('#emp-table tbody tr.stage-divider').forEach(function(dv){{
    var nx=dv.nextElementSibling, has=false;
    while(nx&&!nx.classList.contains('stage-divider')){{ if(nx.style.display!=='none') has=true; nx=nx.nextElementSibling; }}
    dv.style.display=(has||!q)?'':'none'; }});
  var em=document.getElementById('emp-empty'); if(em) em.style.display=vis===0?'block':'none';
}};
</script>
</body>
</html>"""


if __name__ == "__main__":
    main()
