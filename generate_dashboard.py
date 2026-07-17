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

# Paid Leads Tracker (pipeline de ventas de inbound de paid · Agustín) · datos desde 1 jul
PAID_TRACKER_KEY  = os.environ.get("PAID_TRACKER_API_KEY", "")
PAID_TRACKER_BASE = "https://pipe-de-agustin.vercel.app"
PAID_TRACKER_FROM = "2026-07-01"

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
    "Volumen <500 → Freemium": "Volumen insuficiente (<3.000 consultas/mes)",
    "Menos de 3.000 consultas/mes": "Volumen insuficiente (<3.000 consultas/mes)",
    "Menos de 3000 volumen de consultas al mes": "Volumen insuficiente (<3.000 consultas/mes)",
    "Volumen menos 3k consultas (Volumen <500 → Freemium)": "Volumen insuficiente (<3.000 consultas/mes)",
    "Volumen menos 3k consultas": "Volumen insuficiente (<3.000 consultas/mes)",
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
    "No hay volumen": "Volumen insuficiente (<3.000 consultas/mes)",
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


def fetch_paid_tracker():
    """Llama al Paid Leads Tracker (pipeline de Agustín) y devuelve el report ya calculado
    desde el 1 jul. Devuelve None si no hay key o si falla la llamada (el dashboard sigue
    generándose sin esta sección)."""
    if not PAID_TRACKER_KEY:
        return None
    url = f"{PAID_TRACKER_BASE}/api/report?range=custom&from={PAID_TRACKER_FROM}"
    req = urllib.request.Request(url, headers={"X-API-Key": PAID_TRACKER_KEY}, method="GET")
    for a in range(4):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            if e.code == 429 and a < 3:
                time.sleep(min(2 ** a, 8)); continue
            print(f"[paid-tracker] HTTP {e.code}: {e.reason}", file=sys.stderr)
            return None
        except (urllib.error.URLError, ValueError) as e:
            if a < 3:
                time.sleep(min(2 ** a, 8)); continue
            print(f"[paid-tracker] error: {e}", file=sys.stderr)
            return None
    return None


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


# Fuentes que consideramos inbound web «puro» para el pipeline Brain (orgánico / formulario web / campañas)
BRAIN_INBOUND_SOURCES = {"ORGANIC_SEARCH", "PAID_SEARCH", "PAID_SOCIAL", "SOCIAL_MEDIA", "OTHER_CAMPAIGNS"}

def is_inbound_web(src):
    return src in BRAIN_INBOUND_SOURCES


# Buckets de origen del lead (según formulario / evento de conversión de HubSpot)
ORIGIN_ORDER = [
    "Sin información", "Ebook / descargable", "Blog / artículo", "Herramienta / calculadora",
    "Newsletter", "Webinar", "Formulario de demo", "Lead Ads (paid)",
    "GuruSup Brain", "Partners", "Otro formulario",
]

def classify_origin(conv, webinar=""):
    """Clasifica el origen de un contacto según su evento de conversión / formulario."""
    if webinar:
        return "Webinar"
    if not conv:
        return "Sin información"
    low = conv.lower()
    form = low.split(":")[-1].strip()   # el formulario es el último segmento «página: formulario»
    if "webinar" in low:
        return "Webinar"
    # Calculadora / herramienta: detectar en TODA la cadena (el keyword suele estar en el título de página,
    # p. ej. «...calculator | gurusup: .space-y-4»). Incluye la calculadora AHT.
    if any(k in low for k in ("calculator", "calculadora", "aht-calculator", "/tools/",
                              "template generator", "generador de plantillas", "gerador de modelos",
                              "herramienta gratuita", "free tool", "roi calculator", "savings calculator")):
        return "Herramienta / calculadora"
    if "ebook" in form:
        return "Ebook / descargable"
    if "newsletter" in form:
        return "Newsletter"
    if any(k in form for k in ("calculator", "calculadora", "generator", "generador", "roi",
                               "template", "plantilla", "herramienta", "tool", "gerador", "modelos")):
        return "Herramienta / calculadora"
    if any(k in form for k in ("lead ads", "lead generation", "facebook lead", "linkedin lead",
                               "form_cg", "formulario base", "formulario campaña", "3000consultas")):
        return "Lead Ads (paid)"
    if "brain" in low:
        return "GuruSup Brain"
    if any(k in form for k in ("partner", "socios", "afiliados", "affiliados", "partners")):
        return "Partners"
    if any(k in form for k in ("demo", "reserva", "nuevo formulario contacto", "see gurusup",
                               "ve gurusup", "vea gurusup", "demostrac", "in action", "acción",
                               "book your demo", "pre cualific")):
        return "Formulario de demo"
    if "productos blog" in form or "blog" in form:
        return "Blog / artículo"
    if form.startswith(".") or any(k in form for k in ("flex", "space-y", ".gap", ".p-6", ".mt-6", ".max-w")):
        return "Blog / artículo"
    return "Otro formulario"


def vol_bucket(num_conv, vol_mes):
    """Clasifica el volumen de consultas del SQL combinando las dos propiedades del formulario."""
    n = (num_conv or "").lower()
    v = (vol_mes or "").lower()
    if "no lo s" in n:
        return "nose"
    if "más de 3000" in n or "mas de 3000" in n:
        return "ge3000"
    if any(k in v for k in ("+10.000", "3.000-10.000", "+ 5.000", "+5.000", "2.000-5.000")):
        return "ge3000"
    if "menos de 3000" in n or any(k in v for k in ("- 3.000", "-3.000", "500-2.000", "0-500", "<500")):
        return "lt3000"
    return "sindato"


def leadads_label(conv):
    """Desglose de Lead Ads (paid): fuente (LinkedIn/Facebook) + contenido (ebook, formulario…)."""
    low = (conv or "").lower()
    plat = "LinkedIn" if "linkedin" in low else ("Facebook" if "facebook" in low else "Lead Ad")
    form = low.split(":")[-1].strip()
    if "ebook inmobil" in low:
        content = "Ebook Inmobiliarias"
    elif "ebook" in low:
        content = "Ebook (contenido)"
    elif "3000consultas" in form or "3000 consultas" in low:
        content = "Formulario +3.000 consultas"
    elif "form_cg" in form:
        content = "Formulario CG"
    elif "formulario base" in form:
        content = "Formulario base (abierto)"
    elif "formulario" in form:
        content = "Formulario genérico"
    else:
        content = (form[:26] or "sin detalle")
    return f"{plat} · {content}"


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
        "lead1": sum(1 for c in lst if rank(c["lc"]) == 1),  # solo Lead (no MQL/SQL)
        "mql_only": sum(1 for c in lst if rank(c["lc"]) == 2),  # solo MQL
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
AGUSTIN_OWNER = "92703778"             # Agustín · responsable de seguimiento inbound

# Deals mal atribuidos a marketing (heredados/comercial): se excluyen del conteo de marketing
# (siguen contando en el volumen total del pipeline). Coincidencia por subcadena en el nombre.
EXCLUDE_MKT = {"xtrim", "plenergy"}

def agustin_sql_calls(start_iso, end_iso):
    """Llamadas de AGUSTÍN en el rango, cruzadas con sus contactos SQL.
    Devuelve {'unique': nº de SQL distintos llamados, 'attempts': nº total de llamadas a SQL}."""
    res = {"unique": 0, "attempts": 0}
    try:
        calls = fetch_all("calls", [
            {"propertyName": "hubspot_owner_id", "operator": "EQ", "value": AGUSTIN_OWNER},
            {"propertyName": "hs_timestamp", "operator": "BETWEEN", "value": start_iso, "highValue": end_iso},
        ], ["hs_timestamp"])
    except Exception as e:
        print(f"  agustin calls error: {e}"); return res
    call_ids = [c["id"] for c in calls]
    if not call_ids:
        return res
    # Asociación llamada → contacto
    call2contact = {}
    for chunk in _chunks(call_ids):
        try:
            a = api_post("/crm/v4/associations/calls/contacts/batch/read",
                         {"inputs": [{"id": str(i)} for i in chunk]})
        except Exception as e:
            print(f"  assoc calls->contacts error: {e}"); continue
        for r in a.get("results", []):
            cid = str(r.get("from", {}).get("id"))
            call2contact[cid] = [str(t.get("toObjectId")) for t in r.get("to", []) if t.get("toObjectId")]
        time.sleep(0.2)
    contact_ids = {c for tos in call2contact.values() for c in tos}
    if not contact_ids:
        return res
    # Etapa de ciclo de vida de esos contactos
    stage = {}
    for chunk in _chunks(list(contact_ids)):
        try:
            b = api_post("/crm/v3/objects/contacts/batch/read",
                         {"properties": ["lifecyclestage"], "inputs": [{"id": c} for c in chunk]})
        except Exception as e:
            print(f"  contacts batch read error: {e}"); continue
        for m in b.get("results", []):
            stage[m["id"]] = m.get("properties", {}).get("lifecyclestage") or ""
        time.sleep(0.2)
    sql_contacts = {c for c in contact_ids if stage.get(c) in SQL_STAGES}
    res["unique"] = len(sql_contacts)
    res["attempts"] = sum(1 for tos in call2contact.values()
                          if any(stage.get(t) in SQL_STAGES for t in tos))
    return res


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


def count_sdr_emails(start_iso, end_iso):
    """Nº de emails enviados por los SDR (Agustín/Juanma) en el rango."""
    try:
        res = fetch_all("emails", [
            {"propertyName": "hubspot_owner_id", "operator": "IN", "values": SDR_OWNERS},
            {"propertyName": "hs_timestamp", "operator": "BETWEEN", "value": start_iso, "highValue": end_iso},
        ], ["hs_timestamp"])
        return len(res)
    except Exception as e:
        print(f"  sdr emails error: {e}")
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
        f'<text x="{pl-6}" y="{Y(maxv*f)+4:.0f}" text-anchor="end" fill="#6f8c7e" font-size="10">{round(maxv*f)}</text>'
        f'<line x1="{pl}" y1="{Y(maxv*f):.0f}" x2="{W-pr}" y2="{Y(maxv*f):.0f}" stroke="#20402f" stroke-width="1" opacity=".5"/>'
        for f in (0, .5, 1))
    # líneas y etiquetas de mes (cambio de mes en labels 'D mmm')
    months = ""
    prev_m = None
    for i, lb in enumerate(labels):
        m = lb.split()[-1]
        if m != prev_m:
            months += (f'<line x1="{X(i):.0f}" y1="{pt}" x2="{X(i):.0f}" y2="{pt+ph}" stroke="#20402f" stroke-width="1" opacity=".55"/>'
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
        f'<text x="{X(i):.0f}" y="{H-8}" text-anchor="{a}" fill="#6f8c7e" font-size="10">{labels[i]}</text>'
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


def svg_exec_month(cum, daily, labels, color):
    """Gráfico lineal acumulado (1 ene → hoy) con el TOTAL acumulado marcado al final
    de cada mes sobre la propia línea. Pensado para el dashboard ejecutivo."""
    if not cum:
        return '<div style="color:#6f8c7e;font-size:12px;padding:20px 0">Sin datos</div>'
    W, H = 720, 210
    pl, pr, pt, pb = 40, 16, 22, 26
    n = len(cum)
    maxv = max(cum) or 1
    pw, ph = W - pl - pr, H - pt - pb
    def X(i): return pl + (pw * i / (n - 1 if n > 1 else 1))
    def Y(v): return pt + ph * (1 - v / maxv)
    line = " ".join(f"{X(i):.1f},{Y(v):.1f}" for i, v in enumerate(cum))
    area = f"{pl},{pt+ph} " + line + f" {X(n-1):.1f},{pt+ph}"
    # baseline grid (solo base y máx, muy tenue)
    grid = (f'<line x1="{pl}" y1="{Y(0):.0f}" x2="{W-pr}" y2="{Y(0):.0f}" stroke="#2a5442" stroke-width="1" opacity=".5"/>')
    # último índice de cada mes → marca punto + total acumulado
    last_idx = {}
    for i, lb in enumerate(labels):
        last_idx[lb.split()[-1]] = i
    marks = ""
    monthname = {"ene": "Ene", "feb": "Feb", "mar": "Mar", "abr": "Abr", "may": "May", "jun": "Jun",
                 "jul": "Jul", "ago": "Ago", "sep": "Sep", "oct": "Oct", "nov": "Nov", "dic": "Dic"}
    prev_cum = 0
    for m, i in last_idx.items():
        x, y, v = X(i), Y(cum[i]), cum[i]
        delta = v - prev_cum          # generados en ESE mes
        prev_cum = v
        ty = y - 27 if y > 52 else y + 15   # total (grande)
        dy = ty + 13                        # +generados, debajo del total
        marks += (f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3" fill="{color}"/>'
                  f'<text x="{x:.0f}" y="{ty:.0f}" text-anchor="middle" fill="{color}" '
                  f'font-size="13" font-weight="800">{v}</text>'
                  f'<text x="{x:.0f}" y="{dy:.0f}" text-anchor="middle" fill="#cdeede" '
                  f'font-size="10.5" font-weight="700">+{delta}</text>'
                  f'<text x="{x:.0f}" y="{H-8}" text-anchor="middle" fill="#7a988a" font-size="9.5">{monthname.get(m,m)}</text>')
    return (f'<svg viewBox="0 0 {W} {H}" width="100%" preserveAspectRatio="xMidYMid meet" '
            f'style="display:block;height:auto">'
            f'<defs><linearGradient id="gm{color[1:]}" x1="0" y1="0" x2="0" y2="1">'
            f'<stop offset="0" stop-color="{color}" stop-opacity=".28"/>'
            f'<stop offset="1" stop-color="{color}" stop-opacity="0"/></linearGradient></defs>'
            f'{grid}'
            f'<polygon points="{area}" fill="url(#gm{color[1:]})"/>'
            f'<polyline points="{line}" fill="none" stroke="{color}" stroke-width="2.5" '
            f'stroke-linejoin="round" stroke-linecap="round"/>'
            f'{marks}</svg>')


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
        "hs_lead_status", "createdate", "recent_conversion_event_name",
        "first_conversion_event_name", "fuente_webinar", "preferencia_canal_de_contacto",
        "razon_descarte_sql", "numero_de_conversaciones__inbound", "volumen_de_consultas_al_mes",
        "phone", "mobilephone"])

    hist = []
    hist_out = []   # OUTBOUND / no-inbound: importaciones + leads sin origen identificado (los trabaja Juanma)
    imports = tests = internal = noinfo = 0
    def _outrec(p, src, d1, lc):
        return {"src": src, "d1": d1, "lc": lc, "sql_state": p.get("estado_sql_consultoria") or "",
                "email": p.get("email") or "", "company": p.get("company") or "",
                "created": (p.get("createdate") or "")[:10], "created_full": p.get("createdate") or ""}
    for c in hraw:
        p = c["properties"]
        email = p.get("email") or ""
        src = p.get("hs_analytics_source") or ""
        d1 = p.get("hs_analytics_source_data_1") or ""
        lc = p.get("lifecyclestage") or ""
        conv = p.get("recent_conversion_event_name") or p.get("first_conversion_event_name") or ""
        webinar = p.get("fuente_webinar") or ""
        if is_internal(email): internal += 1; continue
        # No excluir como test a quien ya ha llegado a Oportunidad/Cliente (son negocios reales)
        if is_test(p.get("revision_ventas"), email) and LC_RANK.get(lc, 0) < 4:
            tests += 1; continue
        # Las importaciones (CRM_UI / IMPORT) → OUTBOUND (salvo freemium)
        if is_import(src, d1) and lc != "1378463825":
            imports += 1
            if lc != "1378463825": hist_out.append(_outrec(p, src, d1, lc))
            continue
        # Altas por la integración de la app = freemium (aunque estén mal cualificadas como opportunity)
        if src == "OFFLINE" and (d1 or "") == "INTEGRATION":
            lc = "1378463825"
        # Leads/MQL SIN origen identificado (sin evento de conversión ni webinar) → OUTBOUND (no inbound)
        if lc in ("lead", "marketingqualifiedlead") and not conv and not webinar:
            noinfo += 1
            hist_out.append(_outrec(p, src, d1, lc))
            continue
        hist.append({
            "src": src, "d1": d1, "lc": lc,
            "rev": p.get("revision_ventas") or "",
            "sql_state": p.get("estado_sql_consultoria") or "",
            "lead_state": p.get("hs_lead_status") or "",
            "email": email, "firstname": p.get("firstname") or "", "company": p.get("company") or "",
            "created": (p.get("createdate") or "")[:10],
            "created_full": p.get("createdate") or "",
            "conv": p.get("recent_conversion_event_name") or p.get("first_conversion_event_name") or "",
            "webinar": p.get("fuente_webinar") or "",
            "canal_pref": p.get("preferencia_canal_de_contacto") or "",
            "razon": p.get("razon_descarte_sql") or "",
            "num_conv": p.get("numero_de_conversaciones__inbound") or "",
            "vol_mes": p.get("volumen_de_consultas_al_mes") or "",
            "phone": (p.get("phone") or p.get("mobilephone") or "").strip(),
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
        # etiqueta por (pipeline, etapa) — la id 'presentationscheduled' se reutiliza en varios
        # pipelines con etiquetas distintas, así que NO se puede indexar solo por id de etapa
        STAGE_ID_LABEL = {(p["id"], s["id"]): (s.get("label") or "")
                          for p in pdefs for s in p.get("stages", [])}
        # etapas que representan cierre ganado / cliente (no son oportunidad abierta)
        STAGE_WON = {s["id"] for p in pdefs for s in p.get("stages", [])
                     if (s.get("metadata", {}) or {}).get("isClosed") == "true"
                     and (s.get("metadata", {}) or {}).get("probability") == "1.0"}
        # Pipeline de VENTAS = el que contiene las etapas Discovery/Demo/Best Case
        SALES_STAGE_IDS = {"1107496610", "presentationscheduled", "1033589123"}
        SALES_PL = {p["id"] for p in pdefs
                    if any(s["id"] in SALES_STAGE_IDS for s in p.get("stages", []))}
    except Exception as e:
        print(f"  pipelines error: {e}"); PL_LABEL = {}; STAGE_ID_LABEL = {}; STAGE_WON = set(); SALES_PL = set()
    def is_brain_pl(pid):
        return "brain" in PL_LABEL.get(pid, "").lower()
    all_deals = fetch_all("deals", [
        {"propertyName": "hs_is_closed", "operator": "EQ", "value": "false"},
    ], ["dealname", "dealstage", "pipeline", "createdate", "hs_is_closed", "amount",
        "hs_analytics_source", "hs_analytics_source_data_1", "hubspot_owner_id",
        "num_associated_contacts"])
    # Churn REAL = cuentas del pipeline "Clientes" en etapa Churned/Dormidos (incluye cerradas)
    try:
        _churn_client_deals = fetch_all("deals", [
            {"propertyName": "pipeline", "operator": "EQ", "value": "724590933"},
            {"propertyName": "dealstage", "operator": "IN", "values": ["1367778337", "1177859668"]},
        ], ["dealname", "dealstage", "num_associated_contacts"])
    except Exception as e:
        print(f"[churn] error: {e}", file=sys.stderr); _churn_client_deals = []
    cli_churn_n = len(_churn_client_deals)
    def _nac(dl):
        try: return int(dl["properties"].get("num_associated_contacts") or 0)
        except (TypeError, ValueError): return 0
    churn_contactos = sum(_nac(dl) for dl in _churn_client_deals)
    OWNER_NAME = {"92703778": "Agustín", "92703779": "Juanma", "81606279": "Alex", "82823543": "Álvaro"}
    reun_owner = {}      # reuniones/negocios vivos en pipeline (ventas+brain) por persona
    brain_open = 0; brain_value = 0.0   # oportunidades y valor del pipeline Brain
    brain_names = []     # nombres de negocios Brain (para contar empresas únicas)
    out_value = 0.0      # valor de oportunidades outbound (ventas, no-inbound)

    def valid_deal(n):
        n = (n or "").lower()
        return "@" not in n and "[duplicado]" not in n and not n.rstrip().endswith("new deal") and "- new deal" not in n
    def clean_deal(n):
        return re.sub(r'\s*-\s*nuevo tipo de objeto deal\s*$', '', n or "", flags=re.I).strip()

    deals = []            # todos los deals válidos abiertos (para reunión)
    open_deals = []       # abiertos marketing (para tabla pipeline)
    total_pipeline = 0    # volumen total de negocios abiertos en el pipeline
    reun_pipe = {}        # reuniones VIVAS en el pipeline de ventas, por etapa (a día de hoy, cualquier fuente)
    exec_opp = []         # oportunidades abiertas de INBOUND en el pipeline de ventas (sin filtro de fecha)
    exec_opp_out = []     # oportunidades abiertas OUTBOUND (fuentes no-inbound) en el pipeline de ventas
    _EXC_STG_PIPE = ("freemium", "onboarding", "cliente", "customer", "ganad", "won", "post", "daily", "descart", "perdid", "lost")
    brain_count = ventas_count = 0
    clientes_activos = 0   # cuentas de cliente activas = negocios abiertos en el pipeline "Clientes"
    cli_inb_src = 0; cli_out_src = 0   # de dónde vienen los clientes activos (fuente real del negocio)
    cli_contactos = 0      # volumen de contactos de la cartera real (contactos asociados a esas cuentas)
    CLIENTES_PL = "724590933"
    CLI_CHURN_STAGES = ("1367778337", "1177859668")   # Churned · Dormidos/Inactivos
    for dl in all_deals:
        p = dl["properties"]
        if p.get("pipeline") == CLIENTES_PL and p.get("dealstage") not in CLI_CHURN_STAGES:
            clientes_activos += 1
            try: cli_contactos += int(p.get("num_associated_contacts") or 0)
            except (TypeError, ValueError): pass
            if is_marketing(p.get("hs_analytics_source") or "", p.get("hs_analytics_source_data_1") or ""):
                cli_inb_src += 1
            else:
                cli_out_src += 1
        name = clean_deal(p.get("dealname", "—")) or "—"
        if not valid_deal(p.get("dealname", "")):
            continue
        total_pipeline += 1
        stage = p.get("dealstage", ""); pid = p.get("pipeline", "")
        created = (p.get("createdate") or "")[:10]
        src, d1 = p.get("hs_analytics_source") or "", p.get("hs_analytics_source_data_1") or ""
        deals.append({"stage": stage, "created": created})
        # Estos deals YA son abiertos (hs_is_closed=false), así que no hace falta excluir por "won":
        # solo dejamos fuera etapas Freemium/descarte por su etiqueta.
        _sl = STAGE_ID_LABEL.get((pid, stage), "Otra")
        _stg_ok = not any(x in _sl.lower() for x in _EXC_STG_PIPE)
        _oid = str(p.get("hubspot_owner_id") or "")
        _own = OWNER_NAME.get(_oid, "Sin asignar" if not _oid else "Otros")
        _brain = is_brain_pl(pid)
        if pid in SALES_PL and _stg_ok:
            reun_pipe[_sl] = reun_pipe.get(_sl, 0) + 1
        # Reuniones/negocios vivos en pipeline (ventas + brain), por persona
        if (pid in SALES_PL or _brain) and _stg_ok:
            reun_owner[_own] = reun_owner.get(_own, 0) + 1
        # Brain: oportunidades abiertas y su valor
        if _brain and _stg_ok:
            brain_open += 1
            brain_names.append(name)
            try: brain_value += float(p.get("amount") or 0)
            except (TypeError, ValueError): pass
        excluded = any(x in name.lower() for x in EXCLUDE_MKT)   # mal atribuido → fuera de marketing
        # Pipeline EJECUTIVO: oportunidad abierta de inbound en el pipeline de VENTAS (sin filtro de fecha)
        if pid in SALES_PL and _stg_ok:
            try: _amt = float(p.get("amount") or 0)
            except (TypeError, ValueError): _amt = 0.0
            if is_marketing(src, d1) and not excluded:
                _ic, _lb = classify_channel(src, d1)[1], classify_channel(src, d1)[0]
                exec_opp.append({"name": name, "stage_label": _sl, "amount": _amt, "channel": _lb, "icon": _ic})
            else:
                out_value += _amt   # valor de oportunidades outbound (no-inbound) en ventas
                # Clasificar la fuente outbound del negocio (misma lógica que la matriz outbound)
                _os = (src or "").upper()
                if is_import(src, d1):        _olb = "Importaciones"
                elif _os == "OFFLINE":        _olb = "Offline / manual"
                elif _os == "INTEGRATION":    _olb = "Integración de la app"
                elif not _os:                 _olb = "Comercial / prospección"
                else:                          _olb = classify_channel(src, d1)[0]
                exec_opp_out.append({"name": name, "stage_label": _sl, "channel": _olb})
        if is_marketing(src, d1) and created >= fstart and not excluded:
            # Brain solo cuenta como inbound si la fuente es web inbound real (orgánico / campaña / formulario web)
            if is_brain_pl(pid) and is_inbound_web(src): brain_count += 1
            elif not is_brain_pl(pid): ventas_count += 1
            icon = classify_channel(src, d1)[1]; label = classify_channel(src, d1)[0]
            try:
                amount = float(p.get("amount") or 0)
            except (TypeError, ValueError):
                amount = 0.0
            open_deals.append({"id": dl["id"], "name": name,
                               "stage": stage, "stage_label": STAGE_ID_LABEL.get((pid, stage), "Otra etapa"),
                               "is_won": stage in STAGE_WON, "amount": amount, "pid": pid,
                               "is_sales": pid in SALES_PL,
                               "created": created, "channel": f"{icon} {label}",
                               "brain": is_brain_pl(pid)})

    # Deals PERDIDOS (closed-lost) de marketing → sección de perdidos inbound
    lost_deals = []
    try:
        for dl in fetch_all("deals", [
            {"propertyName": "hs_is_closed", "operator": "EQ", "value": "true"},
            {"propertyName": "hs_is_closed_won", "operator": "EQ", "value": "false"},
            {"propertyName": "createdate", "operator": "GTE", "value": funnel_iso},
        ], ["dealname", "dealstage", "pipeline", "createdate",
            "hs_analytics_source", "hs_analytics_source_data_1", "motivo_de_descalificacion"]):
            p = dl["properties"]
            if not valid_deal(p.get("dealname", "")):
                continue
            src, d1 = p.get("hs_analytics_source") or "", p.get("hs_analytics_source_data_1") or ""
            if not is_marketing(src, d1):
                continue
            icon, label = classify_channel(src, d1)[1], classify_channel(src, d1)[0]
            raw_mot = p.get("motivo_de_descalificacion") or ""
            razon = " · ".join(UNIFY_DESCARTE.get(x.strip(), x.strip())
                               for x in raw_mot.split(";") if x.strip())
            lost_deals.append({"id": dl["id"], "name": clean_deal(p.get("dealname", "—")) or "—",
                               "stage": "lost", "created": (p.get("createdate") or "")[:10],
                               "channel": f"{icon} {label}", "brain": is_brain_pl(p.get("pipeline", "")),
                               "razon": razon})
    except Exception as e:
        print(f"  lost deals error: {e}")

    # Fecha de la reunión (discovery/demo) programada para cada deal del pipeline (abiertos + perdidos)
    mtg = deal_meeting_starts([d["id"] for d in open_deals] + [d["id"] for d in lost_deals])
    now_utc = es_now.astimezone(timezone.utc)
    for od in open_deals + lost_deals:
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
    agu_calls = agustin_sql_calls(start_iso, end_iso)  # SQL únicos llamados por Agustín (+ intentos)

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
    # Estado del lead (hs_lead_status) de los SQL → explica por qué no han pasado a oportunidad
    LEAD_STATE_LABELS = {
        "OPEN_DEAL": ("En negociación · deal abierto", "adv"),
        "cliente": ("Cliente", "adv"),
        "OPEN": ("En contacto", "warm"),
        "ATTEMPTED_TO_CONTACT": ("Lead caliente · contactado, en proceso", "warm"),
        "Mareado": ("Mareado · da largas / sin respuesta", "cold"),
        "UNQUALIFIED": ("Lead frío · no cualifica", "cold"),
        "usuario_free": ("Prueba gratuita", "cold"),
        "": ("Sin asignar / sin trabajar", "cold"),
    }
    # El desglose por «temperatura» del lead se hace sobre el TOTAL de SQL (suma = total de SQL)
    ls_counts = {}
    for c in sql_stage_contacts:
        lbl, grp = LEAD_STATE_LABELS.get(c["lead_state"], (c["lead_state"] or "Sin asignar", "cold"))
        ls_counts.setdefault(lbl, [0, grp])
        ls_counts[lbl][0] += 1
    sql_disp["lead_status"] = sorted(([lbl, n, grp] for lbl, (n, grp) in ls_counts.items()), key=lambda x: -x[1])
    sql_disp["ls_base"] = len(sql_stage_contacts)   # total de SQL
    # De los CONTACTADOS/gestionados, cuántos tienen negocio/oportunidad abierta (deal abierto o cliente)
    gest_contacts = [c for c in sql_stage_contacts if rev_group(c["rev"]) == "gestionado"]
    sql_disp["en_oport"] = sum(1 for c in gest_contacts if c["lead_state"] in ("OPEN_DEAL", "cliente"))
    sql_disp["en_medio"] = len(gest_contacts) - sql_disp["en_oport"]

    # ── Ramas del workflow de precualificación (por volumen de consultas) ──
    n_lt3000  = sum(1 for c in hist_fun if c["lc"] == "1394675095")   # <3000 → descartar + email
    n_gt3000  = sum(1 for c in hist_fun if c["lc"] == "1394675094")   # >3000 → Agustín
    n_nosabe  = sum(1 for c in hist_fun if c["lc"] == "1394675096")   # no sé → Agustín
    n_sqldemo = sum(1 for c in hist_fun if c["lc"] == "salesqualifiedlead")
    preq = {
        "agustin": n_gt3000 + n_nosabe + n_sqldemo,   # todo lo que va a ventas (demo)
        "gt3000": n_gt3000, "nosabe": n_nosabe, "sqldemo": n_sqldemo,
        "lt3000": n_lt3000,
        "gestionado": sql_disp["gestionado"],
        "opp": opp_cum,
        "calls_cum": count_sdr_calls(funnel_iso, end_iso),
        "emails_cum": count_sdr_emails(funnel_iso, end_iso),
        "reuniones_cum": reunion_cum,
    }
    # ── Flujo de Agustín desde el 9 de julio (inicio de su seguimiento inbound) ──
    AG_START = "2026-07-09"
    ag_iso = iso(datetime.fromisoformat(AG_START + "T00:00:00").replace(tzinfo=tz))
    ag = agustin_sql_calls(ag_iso, end_iso)   # {unique, attempts} de Agustín desde 9 jul
    preq["ag_start"] = "9 jul"
    preq["ag_sql"] = sum(1 for c in hist if c["lc"] in SQL_STAGES and c["lc"] != "1394675095" and c["created"] >= AG_START)
    preq["ag_lt3000"] = sum(1 for c in hist if c["lc"] == "1394675095" and c["created"] >= AG_START)
    preq["ag_calls_unique"] = ag["unique"]
    preq["ag_calls_attempts"] = ag["attempts"]
    preq["ag_reuniones"] = sum(1 for x in deals if x["stage"] in DEMO_PLUS and x["created"] >= AG_START)
    # Oportunidad = deal NUEVO en pipeline (inbound marketing) creado desde el 9 jul (abierto o cerrado)
    preq["ag_opp"] = (sum(1 for x in open_deals if x["created"] >= AG_START)
                      + sum(1 for x in lost_deals if x["created"] >= AG_START))
    # Razones de descarte de los SQL que fueron a Agustín (por qué se caen)
    ag_sql_contacts = [c for c in hist if c["lc"] in ("salesqualifiedlead", "1394675094", "1394675096")
                       and c["created"] >= AG_START]
    ag_raz = {}
    for c in ag_sql_contacts:
        for x in (c["razon"] or "").split(";"):
            x = x.strip()
            if x:
                lbl = UNIFY_DESCARTE.get(x, x)
                ag_raz[lbl] = ag_raz.get(lbl, 0) + 1
    preq["ag_razones"] = sorted(ag_raz.items(), key=lambda x: -x[1])
    preq["ag_descartados"] = sum(1 for c in ag_sql_contacts
                                 if c["lead_state"] in ("UNQUALIFIED", "Mareado") or c["rev"] == "No aplica / Descartado")
    # Desglose de volumen de consultas de los SQL de Agustín (≥3.000 / no lo sé / <3.000 / sin dato)
    ag_vol = {"ge3000": 0, "nose": 0, "lt3000": 0, "sindato": 0}
    for c in ag_sql_contacts:
        ag_vol[vol_bucket(c["num_conv"], c["vol_mes"])] += 1
    preq["ag_vol"] = ag_vol
    preq["ag_total"] = len(ag_sql_contacts)

    # Preferencia de canal de contacto (del formulario demo) entre los SQL
    pref_llamada = sum(1 for c in sql_stage_contacts if c["canal_pref"] == "Llamada por teléfono")
    pref_email   = sum(1 for c in sql_stage_contacts if c["canal_pref"] == "Email")
    preq["pref_llamada"] = pref_llamada
    preq["pref_email"] = pref_email
    preq["pref_total"] = pref_llamada + pref_email

    # ── Origen de los leads (por formulario / evento de conversión) ──
    CONTENT_ORIGINS = {"Ebook / descargable", "Blog / artículo",
                       "Herramienta / calculadora", "Newsletter", "Webinar"}
    def lead_pop(lst):
        return [c for c in lst if rank(c["lc"]) >= 1 and not is_free(c)]
    origin_counts = {}
    leadads_counts = {}
    for c in lead_pop(hist_fun):
        b = classify_origin(c["conv"], c["webinar"])
        origin_counts[b] = origin_counts.get(b, 0) + 1
        if b == "Lead Ads (paid)":
            lbl = leadads_label(c["conv"])
            leadads_counts[lbl] = leadads_counts.get(lbl, 0) + 1
    origin_sorted = sorted(origin_counts.items(), key=lambda x: -x[1])
    leadads_sorted = sorted(leadads_counts.items(), key=lambda x: -x[1])
    origin_content = sum(v for k, v in origin_counts.items() if k in CONTENT_ORIGINS)
    origin_noinfo = origin_counts.get("Sin información", 0)
    origin_total = sum(origin_counts.values())
    # Split diario (para el KPI de leads)
    daily_leads = lead_pop(daily)
    d_lead_content = sum(1 for c in daily_leads
                         if classify_origin(c["conv"], c["webinar"]) in CONTENT_ORIGINS)
    d_lead_noinfo = sum(1 for c in daily_leads
                        if classify_origin(c["conv"], c["webinar"]) == "Sin información")
    # Leads (etapa = lead) descartados / fríos tras trato de ventas + su origen
    def is_disc_lead(c):
        return c["lead_state"] in ("UNQUALIFIED", "Mareado") or c["rev"] == "No aplica / Descartado"
    lead_stage = [c for c in lead_pop(hist_fun) if c["lc"] == "lead"]
    lead_desc = [c for c in lead_stage if is_disc_lead(c)]
    ld_origin = {}
    for c in lead_desc:
        b = classify_origin(c["conv"], c["webinar"])
        ld_origin[b] = ld_origin.get(b, 0) + 1
    origin = {"sorted": origin_sorted, "content": origin_content, "noinfo": origin_noinfo,
              "total": origin_total, "content_set": CONTENT_ORIGINS, "leadads": leadads_sorted,
              "d_content": d_lead_content, "d_noinfo": d_lead_noinfo, "d_total": len(daily_leads),
              "lead_stage": len(lead_stage), "lead_desc": len(lead_desc),
              "lead_desc_origin": sorted(ld_origin.items(), key=lambda x: -x[1])}

    # ── Paid media (Google Ads + Social Ads) · embudo acumulado desde 1 ene ──
    def chan_label(c):
        return classify_channel(c["src"], c["d1"])[0]
    def paid_funnel(lst):
        return {
            "contactos": len(lst),
            "leads": sum(1 for c in lst if rank(c["lc"]) >= 1),
            "mql":  sum(1 for c in lst if rank(c["lc"]) >= 2),
            "sql":  sum(1 for c in lst if rank(c["lc"]) >= 3),
            "opp":  sum(1 for c in lst if rank(c["lc"]) >= 4),   # oportunidad + cliente (contactos reales)
        }
    paid_google = [c for c in hist_fun if chan_label(c) == "Google Ads"]
    paid_social = [c for c in hist_fun if chan_label(c) == "Social Ads"]
    paid_all = paid_google + paid_social
    paid = {
        "total": paid_funnel(paid_all),
        "google": paid_funnel(paid_google),
        "social": paid_funnel(paid_social),
        # Gasto (no disponible vía API; configurable por env, en €). 0/"" = pendiente de conectar.
        "spend_total": os.environ.get("GEN_PAID_SPEND", "").strip(),
        "spend_google": os.environ.get("GEN_PAID_SPEND_GOOGLE", "").strip(),
        "spend_social": os.environ.get("GEN_PAID_SPEND_SOCIAL", "").strip(),
    }

    # ── Rendimiento por canal (acumulado 1 ene) · contactos → leads → MQL → SQL ──
    chan_fun = {}
    for c in hist_fun:
        lbl = classify_channel(c["src"], c["d1"])[0]
        e = chan_fun.setdefault(lbl, {"contactos": 0, "leads": 0, "mql": 0, "sql": 0})
        e["contactos"] += 1
        r = rank(c["lc"])
        if r >= 1: e["leads"] += 1
        if r >= 2: e["mql"] += 1
        if r >= 3: e["sql"] += 1
    # Oportunidades por canal (deals abiertos de marketing, por su etiqueta de canal)
    opp_by_chan = {}
    for dl in open_deals:
        # dl["channel"] es "icono label" → nos quedamos con el label sin icono
        lbl = dl["channel"].split(" ", 1)[-1].strip()
        opp_by_chan[lbl] = opp_by_chan.get(lbl, 0) + 1
    for lbl, e in chan_fun.items():
        e["opp"] = opp_by_chan.get(lbl, 0)
    chan_funnel = sorted(chan_fun.items(), key=lambda x: -x[1]["sql"])

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
    ch_contactos = series(hist_fun, lambda c: True)                       # todos los contactos del embudo
    ch_leads = series(hist, lambda c: rank(c["lc"]) >= 1)
    ch_mql   = series(hist, lambda c: rank(c["lc"]) >= 2)
    ch_sql   = series(hist, lambda c: rank(c["lc"]) >= 3)
    ch_reun  = series(deals, lambda x: x["stage"] in DEMO_PLUS)           # deals que alcanzaron demo+
    ch_opp   = series(hist, lambda c: c["lc"] == "opportunity", compkey)  # empresas oportunidad
    ch_cli   = series(hist, lambda c: c["lc"] == "customer", compkey)     # empresas cliente

    def trend7(daily_inc):
        """Tendencia: suma últimos 7 días vs 7 previos. dir: up/down/flat + delta."""
        if len(daily_inc) < 14:
            return {"dir": "flat", "delta": 0, "last7": sum(daily_inc[-7:])}
        last7 = sum(daily_inc[-7:]); prev7 = sum(daily_inc[-14:-7])
        d = last7 - prev7
        return {"dir": "up" if d > 0 else ("down" if d < 0 else "flat"), "delta": d, "last7": last7, "prev7": prev7}
    ch_free = series(hist_fun, is_free)
    trends = {
        "contactos": trend7(ch_contactos[1]), "leads": trend7(ch_leads[1]),
        "mql": trend7(ch_mql[1]), "sql": trend7(ch_sql[1]), "reuniones": trend7(ch_reun[1]),
        "opp": trend7(ch_opp[1]), "cli": trend7(ch_cli[1]), "free": trend7(ch_free[1]),
    }
    # ── Exec: contactos por etapa (no empresas) + filtrado inbound marketing + reuniones por etapa ──
    MKT_CH = set(FIXED_CHANNELS.keys())
    def _chl(c): return classify_channel(c["src"], c["d1"])[0]
    exec_extra = {
        "opp_contacts": sum(1 for c in hist_fun if rank(c["lc"]) >= 4),
        "cli_contacts": sum(1 for c in hist_fun if rank(c["lc"]) >= 5),
        "opp_contacts_mkt": sum(1 for c in hist_fun if rank(c["lc"]) >= 4 and _chl(c) in MKT_CH),
        "cli_contacts_mkt": sum(1 for c in hist_fun if rank(c["lc"]) >= 5 and _chl(c) in MKT_CH),
        "opp_emp_mkt": len({compkey(c) for c in hist_fun if rank(c["lc"]) >= 4 and _chl(c) in MKT_CH}),
        "cli_emp_mkt": len({compkey(c) for c in hist_fun if rank(c["lc"]) >= 5 and _chl(c) in MKT_CH}),
        "free_last7": trends["free"]["last7"],
    }
    REUN_STAGES = {"1107496610": "Discovery", "presentationscheduled": "Demo",
                   "1033589123": "Best Case", "1119432966": "Cierre"}
    reun_by_stage = {}
    for x in deals:
        if x["stage"] in REUN_STAGES and x["created"] >= fstart:
            k = REUN_STAGES[x["stage"]]
            reun_by_stage[k] = reun_by_stage.get(k, 0) + 1
    ch_reun_all = series(deals, lambda x: x["stage"] in REUN_STAGES)
    exec_extra["reun_by_stage"] = reun_by_stage
    exec_extra["reun_total"] = sum(reun_by_stage.values())
    exec_extra["reun_trend"] = trend7(ch_reun_all[1])
    exec_extra["reun_pipe"] = sorted(reun_pipe.items(), key=lambda x: -x[1])
    exec_extra["reun_pipe_total"] = sum(reun_pipe.values())
    # Charts ejecutivos con totales por mes · series que CUADRAN con los KPIs:
    #   MQL = de facto (leads con contenido consumido) ~604 · SQL = etapa SQL-consultoría ~161
    ch_mqlc = series(hist, lambda c: not is_free(c) and rank(c["lc"]) >= 1
                     and classify_origin(c["conv"], c["webinar"]) in CONTENT_ORIGINS)
    ch_sqls = series(hist, lambda c: c["lc"] in SQL_STAGES)
    # Comparativa semanal: alinear MQL/SQL con el dato mostrado (de facto / etapa consultoría)
    trends["mql"] = trend7(ch_mqlc[1])
    trends["sql"] = trend7(ch_sqls[1])
    exec_extra["svg_mql_m"] = svg_exec_month(*ch_mqlc, labels, "#57e08a")
    exec_extra["svg_sql_m"] = svg_exec_month(*ch_sql, labels, "#f5b544")   # SQL alcanzados (rank>=3) · crece todo el año
    exec_extra["svg_opp_m"] = svg_exec_month(*ch_opp, labels, "#5bc8f2")
    exec_extra["svg_cli_m"] = svg_exec_month(*ch_cli, labels, "#c084fc")
    # Nota de pico estacional: si un mes supera claramente la mediana, ¿de qué canal vino?
    from collections import Counter as _Ctr
    def spike_note(pred, keyf=None):
        mtot, mchan, seen = {}, {}, set()
        for it in hist:
            if it["created"] in idx and pred(it):
                if keyf:
                    k = keyf(it)
                    if k in seen: continue
                    seen.add(k)
                mo = it["created"][:7]
                mtot[mo] = mtot.get(mo, 0) + 1
                mchan.setdefault(mo, _Ctr())[classify_channel(it["src"], it["d1"])[0]] += 1
            elif keyf:  # asegurar dedupe global aunque el pred filtre
                pass
        if len(mtot) < 2:
            return "* Aún sin histórico suficiente para detectar estacionalidad."
        vals = sorted(mtot.values())
        med = vals[len(vals) // 2] or 1
        mo_max = max(mtot, key=lambda m: mtot[m]); n = mtot[mo_max]
        mes = MESES[int(mo_max[5:7]) - 1]
        if n >= max(med * 1.5, med + 3):
            ch, cn = mchan[mo_max].most_common(1)[0]
            return (f'📈 <b>Pico en {mes}</b> (+{n}, ~{round(n/med,1)}× la media mensual), sobre todo por '
                    f'<b>{esc(ch)}</b> ({round(cn/n*100)}%): volumen no lineal, de una acción/estacional.')
        return "📈 Crecimiento sostenido, sin picos estacionales marcados."
    exec_extra["note_mql"] = spike_note(lambda c: not is_free(c) and rank(c["lc"]) >= 1
                                        and classify_origin(c["conv"], c["webinar"]) in CONTENT_ORIGINS)
    exec_extra["note_sql"] = spike_note(lambda c: c["lc"] in SQL_STAGES)
    exec_extra["note_opp"] = spike_note(lambda c: c["lc"] == "opportunity", compkey)
    exec_extra["note_cli"] = spike_note(lambda c: c["lc"] == "customer", compkey)
    # Calidad del dato (sobre contactos desde 1 ene): email corporativo, teléfono, empresa
    FREE_MAIL = {"gmail.com", "hotmail.com", "outlook.com", "yahoo.com", "yahoo.es", "icloud.com",
                 "hotmail.es", "live.com", "outlook.es", "protonmail.com", "gmx.com", "aol.com",
                 "me.com", "msn.com", "ymail.com", "hotmail.fr", "gmail.es"}
    def has_corp(c):
        e = (c.get("email") or "").lower()
        return "@" in e and e.split("@")[-1] not in FREE_MAIL
    def has_company(c):
        return bool((c.get("company") or "").strip()) or has_corp(c)
    # SIN Freemium: el total de contactos y agregados del ejecutivo excluyen etapa Freemium
    hist_nf = [c for c in hist_fun if not is_free(c)]
    hist_out_fun = [c for c in hist_out if c["created_full"] >= funnel_iso and not is_free(c)]
    exec_extra["total_contactos"] = len(hist_nf)
    q_tot = len(hist_nf) or 1
    exec_extra["quality"] = {
        "total": len(hist_nf),
        "corp": sum(1 for c in hist_nf if has_corp(c)),
        "phone": sum(1 for c in hist_nf if c.get("phone")),
        "company": sum(1 for c in hist_nf if has_company(c)),
    }
    # Volumen de consultas declarado en el formulario (≥3.000 / no lo sé / <3.000 / sin dato)
    volq = {"ge3000": 0, "nose": 0, "lt3000": 0, "sindato": 0}
    for c in hist_nf:
        volq[vol_bucket(c["num_conv"], c["vol_mes"])] += 1
    exec_extra["volq"] = volq
    # Preferencia de canal de contacto (teléfono / email) declarada en el formulario
    pref_tel = sum(1 for c in hist_nf if c["canal_pref"] == "Llamada por teléfono")
    pref_mail = sum(1 for c in hist_nf if c["canal_pref"] == "Email")
    exec_extra["pref"] = {"tel": pref_tel, "mail": pref_mail, "total": pref_tel + pref_mail}
    # Rendimiento por canal EXTENDIDO (sin Freemium): contactos + etapas
    chan_ext = {}
    for c in hist_nf:
        lbl = _chl(c)
        e = chan_ext.setdefault(lbl, {"contactos": 0, "leads": 0, "mql": 0, "sql": 0, "opp_c": 0, "cli_c": 0})
        e["contactos"] += 1
        r = rank(c["lc"])
        if r >= 1: e["leads"] += 1
        # MQL = de facto (contenido consumido) · SQL = etapa consultoría (coherente con los KPIs)
        if r >= 1 and classify_origin(c["conv"], c["webinar"]) in CONTENT_ORIGINS: e["mql"] += 1
        if c["lc"] in SQL_STAGES: e["sql"] += 1
        if r >= 4: e["opp_c"] += 1
        if r >= 5: e["cli_c"] += 1
    # Rendimiento por canal · OUTBOUND (contactos de fuentes no-inbound)
    def _ochl(c):
        s = (c.get("src") or "").upper()
        if is_import(c.get("src"), c.get("d1")): return "Importaciones"
        if s == "OFFLINE": return "Offline / manual"
        if not s: return "Comercial / prospección"
        return classify_channel(c.get("src"), c.get("d1"))[0]
    chan_ext_out = {}
    for c in hist_out_fun:
        lbl = _ochl(c)
        e = chan_ext_out.setdefault(lbl, {"contactos": 0, "leads": 0, "mql": 0, "sql": 0})
        e["contactos"] += 1
        r = rank(c["lc"])
        if r >= 1: e["leads"] += 1
        if r >= 2: e["mql"] += 1
        if c["lc"] in SQL_STAGES: e["sql"] += 1
    # Orgánico y social SON canales de inbound: se mueven de outbound → inbound
    for _inb_lbl in ("SEO Orgánico", "Social orgánico"):
        if _inb_lbl in chan_ext_out:
            _mv = chan_ext_out.pop(_inb_lbl)
            tgt = chan_ext.setdefault(_inb_lbl, {"contactos": 0, "leads": 0, "mql": 0, "sql": 0, "opp_c": 0, "cli_c": 0})
            for k in ("contactos", "leads", "mql", "sql"):
                tgt[k] += _mv.get(k, 0)
    chan_matrix = sorted(chan_ext.items(), key=lambda x: -x[1]["contactos"])
    exec_extra["chan_matrix"] = chan_matrix
    exec_extra["chan_matrix_out"] = sorted(chan_ext_out.items(), key=lambda x: -x[1]["contactos"])
    # Oportunidades OUTBOUND con negocio asociado, por fuente
    deals_by_chan_out = {}
    for dl in exec_opp_out:
        deals_by_chan_out.setdefault(dl.get("channel", "Comercial / prospección"), []).append(
            (dl.get("name", "—"), dl.get("stage_label", "—")))
    exec_extra["deals_by_chan_out"] = deals_by_chan_out
    # Empresas únicas con negocio (oportunidades reales): dedupe por nombre de negocio
    exec_extra["opp_emp_inb"] = len({dl.get("name") for dl in exec_opp})
    exec_extra["opp_emp_out"] = len({dl.get("name") for dl in exec_opp_out})
    exec_extra["opp_emp_brain"] = len(set(brain_names))
    exec_extra["opp_emp_total"] = len({dl.get("name") for dl in exec_opp}
                                      | {dl.get("name") for dl in exec_opp_out}
                                      | set(brain_names))
    # ── Pipeline de ventas · oportunidades abiertas de INBOUND (exec_opp, sin filtro de fecha) ──
    exec_extra["pipeline_value"] = sum(dl.get("amount", 0) for dl in exec_opp)
    exec_extra["pipeline_count"] = len(exec_opp)
    exec_extra["pipeline_value_known"] = sum(1 for dl in exec_opp if dl.get("amount", 0) > 0)
    deals_by_chan = {}
    for dl in exec_opp:
        deals_by_chan.setdefault(dl.get("channel", "—"), []).append((dl.get("name", "—"), dl.get("stage_label", "—")))
    exec_extra["deals_by_chan"] = deals_by_chan
    stage_dist = {}
    for dl in exec_opp:
        stage_dist[dl.get("stage_label", "Otra")] = stage_dist.get(dl.get("stage_label", "Otra"), 0) + 1
    exec_extra["stage_dist"] = sorted(stage_dist.items(), key=lambda x: -x[1])
    # Lead Ads por red (Meta/LinkedIn) desde el desglose de origen
    exec_extra["leadads"] = origin.get("leadads", [])
    # ── OUTBOUND (Juanma) · embudo de contactos de fuentes no-inbound (imports / sin origen) ──
    def _of(pred): return sum(1 for c in hist_out_fun if pred(c))
    exec_extra["out"] = {
        "contactos": len(hist_out_fun),
        "lead": _of(lambda c: rank(c["lc"]) >= 1),
        "mql": _of(lambda c: rank(c["lc"]) >= 2),
        "sql": _of(lambda c: rank(c["lc"]) >= 3),
        "opp": _of(lambda c: rank(c["lc"]) >= 4),
        "cli": _of(lambda c: rank(c["lc"]) >= 5),
        "opp_emp": len({compkey(c) for c in hist_out_fun if rank(c["lc"]) >= 4}),
        "cli_emp": len({compkey(c) for c in hist_out_fun if rank(c["lc"]) >= 5}),
    }
    exec_extra["reun_owner"] = sorted(reun_owner.items(), key=lambda x: -x[1])
    exec_extra["reun_owner_total"] = sum(reun_owner.values())
    exec_extra["brain_open"] = brain_open
    exec_extra["brain_value"] = brain_value
    exec_extra["inb_value"] = exec_extra.get("pipeline_value", 0)
    exec_extra["out_value"] = out_value
    # ── Oportunidades = CONTACTOS en etapa oportunidad CON negocio (deal) asociado ──
    try:
        _opp_ct = fetch_all("contacts", [
            {"propertyName": "lifecyclestage", "operator": "EQ", "value": "opportunity"},
            {"propertyName": "num_associated_deals", "operator": "GT", "value": "0"},
            {"propertyName": "email", "operator": "NOT_CONTAINS_TOKEN", "value": "gurusup.com"},
        ], ["associatedcompanyid"])
    except Exception as e:
        print(f"[opp] error: {e}", file=sys.stderr); _opp_ct = []
    exec_extra["opp_contactos"] = len(_opp_ct)
    exec_extra["opp_empresas"] = len({c["properties"].get("associatedcompanyid") for c in _opp_ct
                                      if c["properties"].get("associatedcompanyid")})
    # ── Clientes: cuentas ACTIVAS del pipeline "Clientes" y de dónde vienen (fuente real del negocio) ──
    exec_extra["cli_split"] = {
        "total": clientes_activos, "contactos": cli_contactos,
        "inbound": cli_inb_src,
        "outbound": cli_out_src,
    }
    # ── Churn REAL = cuentas de cliente que ya no lo son (etapa Churned/Dormidos del pipeline Clientes) ──
    exec_extra["churn"] = {"empresas": cli_churn_n, "contactos": churn_contactos}
    exec_extra["clientes_activos"] = clientes_activos

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
        e = chan.setdefault(label, {"n": 0, "lead": 0, "mql": 0, "sql": 0, "free": 0, "icon": icon, "color": color})
        e["n"] += 1
        r = rank(c["lc"])
        if r >= 3: e["sql"] += 1
        elif r == 2: e["mql"] += 1
        elif is_free(c): e["free"] += 1
        elif r >= 1: e["lead"] += 1
    for lbl, fd in FIXED_CHANNELS.items():
        if lbl not in chan:
            chan[lbl] = {"n": 0, "lead": 0, "mql": 0, "sql": 0, "free": 0, "icon": fd["icon"], "color": fd["color"]}
    channels = sorted(chan.items(), key=lambda x: (-x[1]["n"], x[0]))

    # ── SQL del día (seguimiento de ventas) · una fila por empresa/contacto (sin repetidos) ──
    sql_rows = []
    seen_sql = set()
    for c in daily:
        if c["lc"] in SQL_STAGES:
            key = (c["company"].strip().lower() or c["email"].strip().lower()
                   or (c["firstname"] or "").strip().lower())
            if key and key in seen_sql:
                continue
            if key:
                seen_sql.add(key)
            label, _, _ = classify_channel(c["src"], c["d1"])
            name = c["firstname"] or (c["email"].split("@")[0] if c["email"] else "—")
            razon_u = " · ".join(UNIFY_DESCARTE.get(x.strip(), x.strip())
                                  for x in (c.get("razon") or "").split(";") if x.strip())
            sql_rows.append({"name": name, "company": c["company"], "channel": label,
                             "state": c["sql_state"] or "Pendiente", "rev": c["rev"] or "Pendiente de revisión",
                             "razon": razon_u})
    sql_rows.sort(key=lambda r: r["channel"])

    # ── Razón de descarte/descalificación UNIFICADA (contacto razon_descarte_sql + deal motivo_de_descalificacion) ──
    drz = {}
    def add_reason(raw):
        if not raw:
            return
        # La propiedad puede ser multi-opción (valores separados por «;»)
        for part in str(raw).split(";"):
            part = part.strip()
            if not part:
                continue
            label = UNIFY_DESCARTE.get(part, part)
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
        "agu_unique": agu_calls["unique"], "agu_attempts": agu_calls["attempts"],
        "meet_names": meet_names,
        "svg_leads": svg_cumulative(*ch_leads, labels, "#57e08a"),
        "svg_sql": svg_cumulative(*ch_sql, labels, "#f5b544"),
        "svg_opp": svg_cumulative(*ch_opp, labels, "#ff6b5b"),
        "svg_cli": svg_cumulative(*ch_cli, labels, "#5bc8f2"),
        "svg_contactos": svg_cumulative(*ch_contactos, labels, "#57e08a"),
        "svg_mql": svg_cumulative(*ch_mql, labels, "#34d399"),
        "svg_reun": svg_cumulative(*ch_reun, labels, "#5bc8f2"),
        "trends": trends, "exec_extra": exec_extra,
        "opp_companies": opp_cum, "cli_companies": cli_cum,
        "peak_leads": peak_insight(hist, lambda c: rank(c["lc"]) >= 1),
        "peak_sql": peak_insight(hist, lambda c: rank(c["lc"]) >= 3),
        "peak_opp": peak_insight(hist, lambda c: c["lc"] == "opportunity"),
        "peak_cli": peak_insight(hist, lambda c: c["lc"] == "customer"),
        "channels": channels, "sql_rows": sql_rows, "sql_disp": sql_disp, "preq": preq, "origin": origin, "paid": paid,
        "chan_funnel": chan_funnel,
        "mkt_deals": open_deals, "mkt_total": len(open_deals), "lost_deals": lost_deals,
        "total_pipeline": total_pipeline,
        "nuevos_ids": nuevos_ids, "nuevos_deals": len(nuevos_ids),
        "demos_pipeline": demos_pipeline, "chan_dist": chan_dist, "descarte": descarte,
        "brain_count": brain_count, "ventas_count": ventas_count,
        "excl_tests": tests, "excl_internal": internal, "excl_imports": imports, "excl_noinfo": noinfo,
        "generado": es_now.strftime("%d %b %Y · %H:%M"),
        "paid_tracker": fetch_paid_tracker(),
    }
    html = render(data)
    with open(out_file, "w", encoding="utf-8") as f:
        f.write(html)
    # ── Dashboard ejecutivo (CEO / comité) · página aparte, misma fuente de datos ──
    if out_file == "dashboard_diario.html":
        try:
            with open("dashboard_ejecutivo.html", "w", encoding="utf-8") as f:
                f.write(render_exec(data))
            print("OK · dashboard_ejecutivo.html generado")
        except Exception as e:
            print(f"[exec] error generando ejecutivo: {e}", file=sys.stderr)
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
    sales_pal = ["#cdeed9", "#a9e6c2", "#86dcab",   # acumulativos (verde claro)
                 "#0e5136", "#1f9d5f", "#57e08a"]   # evolutivos (verde fuerte oscuro→claro)
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
        ("Contactos", t, "", "Incluye TODO lo que entra (también los Freemium, que suman al total pero no pasan a Lead). Excluye test, empleados @gurusup e importaciones.", "", "#6f8c7e"),
        ("Leads", cum["lead"], pct(cum["lead"], t), "Interés real: contenido, formulario o chat. Se han EXCLUIDO los Freemium (no cuentan como Lead).", "del total", "#F3ABA0"),
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
    # Bloque visual de razones de descarte (volumen + % sobre el total de descartes)
    drz_tot = sum(n for _, n in d["descarte"])
    if d["descarte"]:
        drz_mx = d["descarte"][0][1] or 1
        raz_rows = ""
        for r, n in d["descarte"]:
            w = max(8, round(n / drz_mx * 100))
            raz_rows += (f'<div class="fbr-row"><div class="fbr-l">{esc(r)}</div>'
                         f'<div class="fbr-barwrap"><div class="fbr-bar" style="width:{w}%"></div></div>'
                         f'<div class="fbr-n">{n} <span class="fbr-p">{pct(n, drz_tot)}</span></div></div>')
        raz_block = (
            f'<div class="fb-raz-head">Razones de descarte registradas ({drz_tot}):</div>'
            f'<div class="fbr">{raz_rows}</div>'
            f'<div class="fbr-foot">Volumen y % sobre los descartes con motivo. ⚠️ De {sd["descartado"]} descartados, solo {drz_tot} tienen razón registrada; el resto están sin motivo (ventas no lo rellena).</div>')
    else:
        raz_block = '<div class="fb-raz-head">Sin razones de descarte registradas todavía.</div>'
    # Temperatura del lead sobre el TOTAL de SQL (suma = total de SQL)
    GRP_ICON = {"adv": "🟢", "warm": "🟡", "cold": "🔴"}
    lb = sd.get("ls_base", 0) or 1
    ls_rows = ""
    for lbl, n, grp in sd.get("lead_status", []):
        ls_rows += (f'<div class="ls-row ls-{grp}"><span class="ls-ico">{GRP_ICON.get(grp,"•")}</span>'
                    f'<span class="ls-l">{esc(lbl)}</span>'
                    f'<span class="ls-n">{n} <span class="ls-p">{pct(n, lb)}</span></span></div>')
    ls_block = (
        '<div class="fb-lsbox">'
        f'<div class="fb-ls-head">🌡️ Temperatura del lead · sobre el <b>total de {sd["total"]} SQL</b> (suma = total de SQL):</div>'
        f'<div class="ls-list">{ls_rows}</div>'
        '<div class="fbr-foot">🟢 avanzando (deal abierto/cliente) · 🟡 en proceso/contactados · 🔴 fríos, mareados, prueba gratuita o sin trabajar. '
        'Es la razón por la que los que están «en medio» aún no pasan a oportunidad.</div>'
        '</div>')
    gest = sd["gestionado"]; pend = sd["pendiente"]; desc = sd["descartado"]; excl = sd.get("excluido", 0)
    en_oport = sd.get("en_oport", 0); en_medio = sd.get("en_medio", 0)
    # Columna IZQUIERDA · flujo de gestión (verde): Contactados → En proceso → Oportunidad
    col_gest = (
        '<div class="sqlcol sqlcol-ok">'
        f'<div class="sqlcol-h">🟢 Gestionados · <b>{gest}</b> <span>({pct(gest, st)} de los SQL)</span></div>'
        '<div class="sqlflow">'
        f'<div class="sfv-step"><b>{gest}</b><span>📞 Contactados / agendados<br>(llamada o email · Agustín)</span></div>'
        '<div class="sfv-arrow">↓</div>'
        f'<div class="sfv-step sfv-mid"><b>{en_medio}</b><span>⏳ En proceso<br>contactados, aún sin convertir</span></div>'
        '<div class="sfv-arrow">↓</div>'
        f'<div class="sfv-step sfv-ok"><b>🎯 {en_oport}</b><span>Oportunidad creada<br>({pct(en_oport, gest or 1)} de los contactados)</span></div>'
        '</div>'
        '</div>')
    # Columna DERECHA · descarte (rojo): razones
    col_desc = (
        '<div class="sqlcol sqlcol-bad">'
        f'<div class="sqlcol-h">🔴 Descartados · <b>{desc}</b> <span>({pct(desc, st)} de los SQL)</span></div>'
        f'{raz_block}'
        '</div>')
    reconc = f'{gest} gestionados + {pend} pendientes + {desc} descartados' + (f' + {excl} excluidos (dup/test)' if excl else '') + f' = <b>{sd["total"]} SQL</b>'
    flow_branch = (
        '<div class="flow-branch nobrd">'
        f'<div class="fb-head">📌 De los <b>{sd["total"]} SQL</b> totales, ¿cómo evolucionan? '
        f'<span class="fb-reconc">{reconc}</span></div>'
        '<div class="fb-states">'
        f'<div class="fb-state ok"><div class="fbs-n">{gest}</div><div class="fbs-l">🟢 Gestionados</div>'
        f'<div class="fbs-p">{pct(gest, st)} de los SQL</div><small>contactados por Agustín (llamada / email)</small></div>'
        f'<div class="fb-state pend"><div class="fbs-n">{pend}</div><div class="fbs-l">🟡 Pendientes</div>'
        f'<div class="fbs-p">{pct(pend, st)} de los SQL</div><small>sin contactar / asignar todavía</small></div>'
        f'<div class="fb-state bad"><div class="fbs-n">{desc}</div><div class="fbs-l">🔴 Descartados</div>'
        f'<div class="fbs-p">{pct(desc, st)} de los SQL</div><small>no cualifican (razones →)</small></div>'
        '</div>'
        '<div class="sqlcols">'
        f'{col_gest}{col_desc}'
        '</div>')
    # Se separan: el embudo (flow_html) y la rama de estado de SQL (flow_branch) para intercalar Paid media
    flow_full = flow_html

    # ── Contadores de las ramas del workflow de precualificación ──
    pq = d["preq"]
    # Rama Agustín: SQL → contactados (llamadas + videollamadas) → oportunidades
    ag_base = pq["ag_sql"] or 1
    ag_contactos = pq["ag_calls_unique"] + pq["ag_reuniones"]   # total precualificación (tel + video)
    preq_sales_stats = (
        '<div class="pqf-sub">① Evolución · del SQL a la oportunidad</div>'
        '<div class="pqflow">'
        f'<div class="pqf-step"><b>{pq["ag_sql"]}</b><span>SQL a Agustín<br>(desde {pq["ag_start"]}) · base 100%</span></div>'
        f'<div class="pqf-arrow"><span class="pqf-pct">{pct(ag_contactos, ag_base)}</span>→</div>'
        f'<div class="pqf-step"><b>{ag_contactos}</b><span>contactos de precualificación<br>{pct(ag_contactos, ag_base)} de los SQL · '
        f'<span class="pqf-ch-tel">📞 {pq["ag_calls_unique"]} tel.</span> · <span class="pqf-ch-vid">🎥 {pq["ag_reuniones"]} videoll.</span></span></div>'
        f'<div class="pqf-arrow"><span class="pqf-pct">{pct(pq["ag_opp"], ag_base)}</span>→</div>'
        f'<div class="pqf-step pqf-ok"><b>🎯 {pq["ag_opp"]}</b><span>oportunidades creadas<br>{pct(pq["ag_opp"], ag_base)} de los SQL</span></div>'
        '</div>')
    # Desglose por volumen de consultas declarado en el formulario
    avb = pq.get("ag_vol", {}); avt = pq.get("ag_total", 0) or 1
    preq_sales_stats += (
        '<div class="pqf-sub">② Calidad de entrada · volumen de consultas declarado en el formulario</div>'
        '<div class="pqvol">'
        f'<div class="pqvol-item pqvol-ok"><b>{avb.get("ge3000",0)}</b><span>✅ +3.000 consultas/mes<br>(incluye +5k, +10k) · {pct(avb.get("ge3000",0), avt)}</span></div>'
        f'<div class="pqvol-item"><b>{avb.get("nose",0)}</b><span>🤷 «No lo sé»<br>{pct(avb.get("nose",0), avt)}</span></div>'
        f'<div class="pqvol-item pqvol-bad"><b>{avb.get("lt3000",0)}</b><span>⚠️ &lt;3.000 (mal cualificados)<br>{pct(avb.get("lt3000",0), avt)}</span></div>'
        f'<div class="pqvol-item"><b>{avb.get("sindato",0)}</b><span>❔ Sin dato de volumen *<br>{pct(avb.get("sindato",0), avt)}</span></div>'
        '</div>'
        f'<div class="pqvol-note">* El campo de volumen no era obligatorio → sin él no se puede cualificar. Al precualificar, Agus vio que <b>7 de {avb.get("sindato",0)}</b> tenían &lt;3.000. Por eso ya es <b>campo obligatorio</b>.</div>')
    # Mini-desglose: por qué se caen (razones de descarte de los SQL de Agustín)
    if pq.get("ag_razones"):
        ag_raz_mx = pq["ag_razones"][0][1] or 1
        ag_raz_tot = sum(n for _, n in pq["ag_razones"])
        ag_raz_rows = "".join(
            f'<div class="fbr-row"><div class="fbr-l">{esc(r)}</div>'
            f'<div class="fbr-barwrap"><div class="fbr-bar" style="width:{max(8, round(n/ag_raz_mx*100))}%"></div></div>'
            f'<div class="fbr-n">{n} <span class="fbr-p">{pct(n, ag_raz_tot)}</span></div></div>'
            for r, n in pq["ag_razones"])
        preq_sales_stats += (
            '<div class="pqf-sub">③ Descartados · cuántos y por qué se caen</div>'
            '<div class="fb-razbox" style="margin-top:0">'
            f'<div class="fb-raz-head">🔴 <b>{pq["ag_descartados"]} descartados</b> de los {pq["ag_total"]} SQL de Agustín · razones registradas:</div>'
            f'<div class="fbr">{ag_raz_rows}</div>'
            '<div class="fbr-foot">Razón de descarte SQL registrada. La mayoría suelen ser <b>volumen insuficiente (&lt;3.000)</b>: llegan como SQL pero al precualificar no tienen volumen.</div>'
            '</div>')
    # Donut · preferencia de canal de contacto (del formulario demo)
    pt = pq["pref_total"] or 1
    pll, pem = pq["pref_llamada"], pq["pref_email"]
    ang = round(pll / pt * 360)
    canal_pref_html = (
        '<div class="cpref">'
        f'<div class="cpref-donut" style="background:conic-gradient(#ff6b5b 0deg {ang}deg,#22D3EE {ang}deg 360deg)">'
        f'<div class="cpref-hole"><b>{pq["pref_total"]}</b><span>con preferencia</span></div></div>'
        '<div class="cpref-leg">'
        '<div class="cpref-t">Preferencia de canal de contacto <span>(campo del formulario demo)</span></div>'
        f'<div class="cpref-row"><span class="cpref-dot" style="background:#ff6b5b"></span> 📞 Llamada por teléfono · <b>{pll}</b> ({pct(pll, pt)})</div>'
        f'<div class="cpref-row"><span class="cpref-dot" style="background:#22D3EE"></span> ✉️ Email · <b>{pem}</b> ({pct(pem, pt)})</div>'
        '<div class="cpref-note">Solo cuenta los SQL que han indicado preferencia en el formulario.</div>'
        '</div></div>')
    # ── Origen de los leads (de dónde vienen) ──
    og = d["origin"]
    og_tot = og["total"] or 1
    ORIGIN_ICON = {
        "Sin información": "❔", "Ebook / descargable": "📘", "Blog / artículo": "📝",
        "Herramienta / calculadora": "🧮", "Newsletter": "📰", "Webinar": "🎥",
        "Formulario de demo": "🎯", "Lead Ads (paid)": "📣", "GuruSup Brain": "🧠",
        "Partners": "🤝", "Otro formulario": "•",
    }
    og_mx = og["sorted"][0][1] if og["sorted"] else 1
    resto = og["total"] - og["content"]
    def og_row(name, n, cls):
        w = max(6, round(n / og_mx * 100))
        return (f'<div class="og-row{cls}"><div class="og-l">{ORIGIN_ICON.get(name, "•")} {esc(name)}</div>'
                f'<div class="og-barwrap"><div class="og-bar" style="width:{w}%"></div></div>'
                f'<div class="og-n">{n} <span class="og-p">{pct(n, og_tot)}</span></div></div>')
    content_rows = "".join(og_row(name, n, " og-content") for name, n in og["sorted"] if name in og["content_set"])
    # Resto de leads (TOFU): sin «Lead Ads (paid)» agregado — se muestra desglosado aparte
    rest_rows = "".join(og_row(name, n, (" og-noinfo" if name == "Sin información" else ""))
                        for name, n in og["sorted"] if name not in og["content_set"] and name != "Lead Ads (paid)")
    content_rows = content_rows or '<div class="fbr-foot">Sin leads de contenido todavía.</div>'
    # Sub-desglose de Lead Ads (paid): fuente + contenido
    la_tot = sum(n for _, n in og.get("leadads", [])) or 1
    la_mx = og["leadads"][0][1] if og.get("leadads") else 1
    leadads_rows = "".join(
        f'<div class="og-row"><div class="og-l">{esc(lbl)}</div>'
        f'<div class="og-barwrap"><div class="og-bar" style="width:{max(6, round(n/la_mx*100))}%"></div></div>'
        f'<div class="og-n">{n} <span class="og-p">{pct(n, la_tot)}</span></div></div>'
        for lbl, n in og.get("leadads", []))
    leadads_block = (f'<div class="og-sub">📣 Lead Ads (paid) · por fuente y contenido</div>'
                     f'<div class="og-bars">{leadads_rows}</div>') if og.get("leadads") else ""
    # Leads descartados (etapa = lead, fríos/no cualificados) + su origen
    ld_n = og.get("lead_desc", 0); ld_base = og.get("lead_stage", 0) or 1
    ld_mx = og["lead_desc_origin"][0][1] if og.get("lead_desc_origin") else 1
    ld_rows = "".join(
        f'<div class="og-row"><div class="og-l">{ORIGIN_ICON.get(name, "•")} {esc(name)}</div>'
        f'<div class="og-barwrap"><div class="og-bar" style="width:{max(6, round(n/ld_mx*100))}%;background:linear-gradient(90deg,#e0574a,#ff6b5b)"></div></div>'
        f'<div class="og-n">{n} <span class="og-p">{pct(n, ld_n or 1)}</span></div></div>'
        for name, n in og.get("lead_desc_origin", []))
    leaddesc_block = (
        f'<div class="og-sub">🔴 Leads descartados · {ld_n} de {og.get("lead_stage",0)} leads ({pct(ld_n, ld_base)}) · por origen</div>'
        f'<div class="og-bars">{ld_rows}</div>'
        '<div class="fbr-foot">Leads (etapa «lead») marcados como <b>fríos / no cualificados</b> tras el trato de ventas (estado del lead). % sobre el total de leads en etapa «lead».</div>'
    ) if ld_n else ""
    origin_html = (
        '<div class="og-head">'
        f'<div class="og-stat og-total"><div class="og-tag">LEADS TOTALES</div><b>{og["total"]}</b><span>acumulado desde el 1 de enero</span></div>'
        f'<div class="og-stat og-content"><div class="og-tag">📗 MQL · CONTENIDO (MOFU/BOFU)</div><b>{og["content"]} <span class="og-pct">{pct(og["content"], og_tot)}</span></b>'
        '<span>han <b>consumido contenido</b> (ebook · webinar · calculadora · comparativa · newsletter) → consideración/decisión = <b>MQL de facto</b>.</span></div>'
        f'<div class="og-stat og-noinfo"><div class="og-tag">🔭 RESTO DE LEADS (TOFU)</div><b>{resto} <span class="og-pct">{pct(resto, og_tot)}</span></b>'
        '<span>sin rastro de contenido de valor (sin info, blog suelto, formulario demo, otros) → menos intención (descubrimiento).</span></div>'
        '</div>'
        '<div class="og-sub">📗 MOFU/BOFU · leads por tipo de contenido consumido</div>'
        f'<div class="og-bars">{content_rows}</div>'
        '<div class="og-sub">🔭 TOFU · resto de leads por origen</div>'
        f'<div class="og-bars">{rest_rows}</div>'
        f'{leadads_block}'
        f'{leaddesc_block}')

    # ── Paid media (embudo + gasto + desglose por canal) ──
    pd_ = d["paid"]; ptot = pd_["total"]
    def cost_per(spend, n):
        try:
            if spend and n:
                return f'{round(float(str(spend).replace(",", ".")) / n)} €'
        except Exception:
            pass
        return "—"
    def money(s):
        return f'{s} €' if s else '<span class="pm-pend">pendiente de conectar</span>'
    pcont = ptot["contactos"] or 1
    paid_stages = [
        ("Contactos", ptot["contactos"], "", "#6f8c7e"),
        ("Leads", ptot["leads"], f'{pct(ptot["leads"], pcont)} de contactos', "#a855f7"),
        ("MQL", ptot["mql"], f'{pct(ptot["mql"], ptot["leads"] or 1)} de leads', "#8b5cf6"),
        ("SQL", ptot["sql"], f'{pct(ptot["sql"], ptot["leads"] or 1)} de leads', "#7c3aed"),
        ("Oportunidad", ptot["opp"], f'{pct(ptot["opp"], ptot["sql"] or 1)} de SQL · empresas', "#6d28d9"),
    ]
    pm_track = '<div class="flow-track">'
    for i, (name, val, conv, color) in enumerate(paid_stages):
        if i > 0:
            pm_track += f'<div class="flow-arrow"><span class="fa-pct">{conv.split(" ")[0]}</span><span class="fa-base">{" ".join(conv.split(" ")[1:])}</span></div>'
        pm_track += (f'<div class="fstage" style="border-top-color:{color}">'
                     f'<div class="fs-count" style="color:{color}">{val}</div>'
                     f'<div class="fs-name">{esc(name)}</div></div>')
    pm_track += '</div>'
    # Cabecera de gasto + coste por resultado
    sp = pd_["spend_total"]
    pm_head = (
        '<div class="pm-head">'
        f'<div class="pm-stat pm-spend"><b>{money(sp)}</b><span>gasto total en paid media<br>(acumulado desde 1 ene)</span></div>'
        f'<div class="pm-stat"><b>{cost_per(sp, ptot["leads"])}</b><span>coste por lead (CPL)</span></div>'
        f'<div class="pm-stat"><b>{cost_per(sp, ptot["sql"])}</b><span>coste por SQL</span></div>'
        f'<div class="pm-stat pm-ok"><b>{cost_per(sp, ptot["opp"])}</b><span>coste por oportunidad</span></div>'
        '</div>')
    # Desglose por canal
    def pm_row(nombre, icon, fn, spend):
        return (f'<tr><td>{icon} <strong>{nombre}</strong></td>'
                f'<td>{money(spend)}</td><td>{fn["leads"]}</td><td>{fn["mql"]}</td>'
                f'<td>{fn["sql"]}</td><td>{fn["opp"]}</td>'
                f'<td>{cost_per(spend, fn["leads"])}</td></tr>')
    pm_table = (
        '<table class="table pm-table"><thead><tr><th>Canal</th><th>Gasto</th><th>Leads</th>'
        '<th>MQL</th><th>SQL</th><th>Oport.</th><th>CPL</th></tr></thead><tbody>'
        + pm_row("Google Ads", "🔍", pd_["google"], pd_["spend_google"])
        + pm_row("Social Ads", "📣", pd_["social"], pd_["spend_social"])
        + '</tbody></table>')
    paid_html = pm_head + pm_track + pm_table

    # ── Pipeline Paid (Agustín) · desde 1 jul · datos en vivo del Paid Leads Tracker ──
    pt = d.get("paid_tracker")
    if not pt:
        paidtracker_html = (
            '<div class="pt-empty">⏳ Pendiente de conectar el <b>Paid Leads Tracker</b>. '
            'En cuanto esté disponible el acceso, esta sección se rellena sola en cada refresco '
            '(datos desde el 1 de julio).</div>')
    else:
        st = pt.get("stats", {}) or {}
        def _n(v):
            try: return int(v)
            except (TypeError, ValueError): return 0
        def _pct(a, b):
            b = b or 0
            return f"{round(a / b * 100)}%" if b else "—"
        pt_total = _n(st.get("total"))
        base = pt_total or 1
        # KPIs
        kpi_defs = [
            ("total", "Leads paid", st.get("total")),
            ("qualified", "Cualificados", st.get("qualified")),
            ("open", "En proceso", st.get("open")),
            ("won", "Ganados", st.get("won")),
            ("lost", "Perdidos", st.get("lost")),
            ("uncontacted", "Sin contactar", st.get("uncontacted")),
        ]
        pt_kpis = "".join(
            f'<div class="pt-kpi pt-{k}"><b>{_n(v)}</b><span>{lab}'
            + (f'<br>{_pct(_n(v), base)} del total</span>' if k not in ("total",) else '</span>')
            + '</div>'
            for k, lab, v in kpi_defs)
        afc = st.get("avg_first_contact_days")
        pt_afc = ""
        if afc is not None:
            try:
                pt_afc = (f'<div class="pt-afc">⏱️ Tiempo medio hasta primer contacto: '
                          f'<b>{round(float(afc), 1)} días</b></div>')
            except (TypeError, ValueError):
                pt_afc = ""
        # Embudo por etapa
        by_stage = st.get("by_stage") or []
        st_mx = max((_n(s.get("count")) for s in by_stage), default=0) or 1
        stage_rows = "".join(
            f'<div class="fbr-row"><div class="fbr-l">{esc(str(s.get("label") or s.get("stage") or ""))}</div>'
            f'<div class="fbr-barwrap"><div class="fbr-bar" style="width:{max(6, round(_n(s.get("count"))/st_mx*100))}%"></div></div>'
            f'<div class="fbr-n">{_n(s.get("count"))}</div></div>'
            for s in by_stage)
        stage_block = (f'<div class="pt-col"><h4 class="pt-h">Embudo por etapa</h4>'
                       f'<div class="fbr">{stage_rows}</div></div>') if by_stage else ""
        # Por canal
        ch_stats = st.get("channel_stats") or []
        ch_mx = max((_n(c.get("count")) for c in ch_stats), default=0) or 1
        _PT_ICO = {"Meta Ads": "📣", "Facebook Ads": "📣", "Instagram Ads": "📣",
                   "LinkedIn Ads": "🔗", "TikTok Ads": "🎵"}
        def _chan_ico(name):
            if name in FIXED_CHANNELS:
                return FIXED_CHANNELS[name]["icon"]
            return _PT_ICO.get(name, "•")
        chan_rows = "".join(
            f'<div class="fbr-row"><div class="fbr-l">{_chan_ico(c.get("channel"))} {esc(str(c.get("channel") or "—"))}</div>'
            f'<div class="fbr-barwrap"><div class="fbr-bar pt-bar2" style="width:{max(6, round(_n(c.get("count"))/ch_mx*100))}%"></div></div>'
            f'<div class="fbr-n">{_n(c.get("count"))} <span class="fbr-p">{_n(c.get("qualified"))} cual.</span></div></div>'
            for c in ch_stats)
        chan_block = (f'<div class="pt-col"><h4 class="pt-h">Por canal</h4>'
                      f'<div class="fbr">{chan_rows}</div></div>') if ch_stats else ""
        # Motivos de pérdida
        loss = st.get("loss_reasons") or []
        loss_tot = sum(_n(l.get("count")) for l in loss) or 1
        loss_mx = max((_n(l.get("count")) for l in loss), default=0) or 1
        loss_rows = "".join(
            f'<div class="fbr-row"><div class="fbr-l">{esc(str(l.get("reason") or "—"))}</div>'
            f'<div class="fbr-barwrap"><div class="fbr-bar pt-bar3" style="width:{max(6, round(_n(l.get("count"))/loss_mx*100))}%"></div></div>'
            f'<div class="fbr-n">{_n(l.get("count"))} <span class="fbr-p">{_pct(_n(l.get("count")), loss_tot)}</span></div></div>'
            for l in loss)
        loss_block = (f'<div class="pt-col"><h4 class="pt-h">Motivos de pérdida</h4>'
                      f'<div class="fbr">{loss_rows}</div></div>') if loss else ""
        cols = stage_block + chan_block + loss_block
        paidtracker_html = (
            f'<div class="pt-kpis">{pt_kpis}</div>'
            f'{pt_afc}'
            f'<div class="pt-cols">{cols}</div>')

    # Rama <3.000: número grande + bullets
    preq_free_stats = (
        '<div class="pqbig">'
        f'<div class="pqbig-n">{pq["ag_lt3000"]}</div>'
        '<ul class="pqbig-ul">'
        '<li><b>Descarte inicial automático</b> (desde 9 jul).</li>'
        '<li>Reciben <b>email de agradecimiento</b>.</li>'
        '<li>Entran en la lista de HubSpot <b>«Descalificación de SQLs · &lt;3.000»</b> — dinámica, crece con cada descarte.</li>'
        '<li>Razón de descarte SQL <b>automatizada = «&lt;3.000 consultas»</b> → se verá en el evolutivo.</li>'
        '</ul>'
        '</div>')

    # Resumen 24h · KPIs (% sobre el total de contactos, NO es un embudo)
    dtot = dd["total"]
    def dcard(label, val, sub, cls="f-c-default"):
        return f'<div class="f-card {cls}"><div class="fc-label">{label}</div><div class="fc-value">{val}</div><div class="fc-sub">{sub}</div></div>'
    video_day = max(d["agenda_day"] - d["calls_day"], 0)
    comercial = dd["lead"]   # rank>=1 = todo lo que entra al embudo comercial
    # Árbol: Contactos → (rama comercial: Leads+MQL+SQL → Llamadas)  y  (rama freemium: fin)
    opp_step = ""
    if dd["opp"] > 0:
        opp_step = (f'<div class="df-op df-arrow">→</div>'
                    f'<div class="df-card df-action"><div class="fc-label">Oportunidades</div><div class="fc-value">{dd["opp"]}</div>'
                    f'<div class="fc-sub">empresas</div></div>')
    day_flow = (
        '<div class="daytree">'
        f'<div class="dt-root"><div class="fc-label">Contactos · últimas 24h</div><div class="fc-value">{dtot}</div>'
        '<div class="fc-sub">total de nuevos contactos que entran</div></div>'
        '<div class="dt-branches">'
        # Rama comercial
        '<div class="dt-branch dt-com"><div class="dt-arm">→</div><div class="dt-body">'
        f'<div class="dt-btag">🛠️ Proceso comercial · <b>{pct(comercial, dtot)}</b> del total ({comercial})</div>'
        '<div class="dt-row">'
        f'<div class="df-card df-state"><div class="fc-label">Leads</div><div class="fc-value">{dd["lead1"]}</div>'
        f'<div class="fc-sub">📘 {og["d_content"]} contenido · ❔ {og["d_noinfo"]} sin info</div></div>'
        '<div class="df-op">+</div>'
        f'<div class="df-card df-state"><div class="fc-label">MQL</div><div class="fc-value">{dd["mql_only"]}</div>'
        '<div class="fc-sub">consumió contenido</div></div>'
        '<div class="df-op">+</div>'
        f'<div class="df-card df-state"><div class="fc-label">SQL</div><div class="fc-value">{dd["sql"]}</div>'
        '<div class="fc-sub">piden demo → seguimiento de Agustín</div></div>'
        '</div></div></div>'
        # Rama freemium
        '<div class="dt-branch dt-free"><div class="dt-arm">→</div><div class="dt-body">'
        f'<div class="dt-btag dt-free-tag">🧊 Producto gratuito · <b>{pct(dd["free"], dtot)}</b> del total</div>'
        '<div class="dt-row">'
        f'<div class="df-card df-free-card"><div class="fc-label">Free</div><div class="fc-value">{dd["free"]}</div>'
        f'<div class="fc-sub">{pct(dd["free"], dtot)} del total</div></div>'
        '<div class="dt-free-txt">Altas gratuitas por la app. <b>No pasan por Leads, MQL ni SQL</b>, ni por reuniones agendadas. Se quedan aquí, fuera del embudo comercial.</div>'
        '</div>'
        '</div></div>'
        '</div>'
        '</div>')
    day_funnel = day_flow

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
            razon_txt = r["razon"] if r.get("razon") else ("descartado sin razón" if r["rev"] == "No aplica / Descartado" else "")
            razon_td = (f'<td><span class="pill pill-lost">{esc(razon_txt)}</span></td>'
                        if razon_txt else '<td class="dt-none">—</td>')
            call_rows += (f'<tr><td><strong>{esc(r["name"])}</strong></td>'
                          f'<td>{emp} · <em>{esc(r["channel"])}</em></td>'
                          f'{razon_td}</tr>')
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

    # Pipeline · etapas + perdidos (inbound). Orden dentro de cada etapa por CANAL.
    by_stage = {}
    for deal in d["mkt_deals"]:
        by_stage.setdefault(deal["stage"], []).append(deal)
    deal_rows = ""
    stage_defs = list(STAGE_LABELS)   # sin la sección de perdidos (a petición)
    for st_id, label, pill in stage_defs:
        group = by_stage.get(st_id, [])
        # Ordenadas por canal (y, dentro del canal, por fecha de reunión)
        group = sorted(group, key=lambda x: (x["channel"], x.get("mtg_sort", float("inf"))))
        if not group:
            continue
        deal_rows += f'<tr class="stage-divider"><td colspan="5">{esc(label)} · {len(group)} deals</td></tr>'
        for deal in group:
            nt = ' <span class="new-tag">NUEVO</span>' if deal["id"] in d["nuevos_ids"] else ""
            if deal.get("mtg_txt"):
                cls = "dt-next" if deal.get("mtg_future") else "dt-past"
                fecha_td = f'<td class="{cls}">{esc(deal["mtg_txt"])}</td>'
            else:
                fecha_td = '<td class="dt-none">—</td>'
            razon = deal.get("razon", "")
            razon_td = (f'<td><span class="pill pill-lost">{esc(razon)}</span></td>'
                        if razon else '<td class="dt-none"></td>')
            deal_rows += (f'<tr data-name="{esc(deal["name"].lower())}"><td><strong>{esc(deal["name"])}</strong>{nt}</td>'
                          f'<td>{esc(deal["channel"])}</td><td><span class="pill {pill}">{esc(label)}</span></td>'
                          f'{fecha_td}{razon_td}</tr>')
    chan_dist_txt = " · ".join(f"{n} {esc(lbl)}" for lbl, n in sorted(d["chan_dist"].items(), key=lambda x: -x[1])) or "—"

    return TEMPLATE.format(
        title=esc(d["title"]), fecha_larga=esc(d["fecha_larga"]), periodo_txt=esc(d["periodo_txt"]),
        fun_label=esc(d["fun_label"]), chart_label=esc(d["chart_label"]),
        sales_pyr=sales_pyr, free_pyr=free_pyr, flow_full=flow_full, flow_branch=flow_branch,
        preq_sales_stats=preq_sales_stats, preq_free_stats=preq_free_stats, origin_html=origin_html,
        canal_pref_html=canal_pref_html, paid_html=paid_html,
        svg_leads=d["svg_leads"], svg_sql=d["svg_sql"], svg_opp=d["svg_opp"], svg_cli=d["svg_cli"],
        peak_leads=d["peak_leads"], peak_sql=d["peak_sql"], peak_opp=d["peak_opp"], peak_cli=d["peak_cli"],
        day_funnel=day_funnel, d_free=dd["free"], d_free_pct=pct(dd["free"], dd["total"]), d_total=dd["total"],
        meet_names=d["meet_names"], calls_day=d["calls_day"], ch_cards=ch_cards, call_rows=call_rows,
        descarte_html=descarte_html, descarte_note=descarte_note, deal_rows=deal_rows,
        mkt_total=d["mkt_total"], nuevos_deals=d["nuevos_deals"], demos_pipeline=d["demos_pipeline"],
        brain_count=d["brain_count"], ventas_count=d["ventas_count"], total_pipeline=d["total_pipeline"],
        mql_stage=d["cum"]["mql"],
        chan_dist_txt=chan_dist_txt,
        excl_tests=d["excl_tests"], excl_internal=d["excl_internal"], excl_imports=d["excl_imports"], excl_noinfo=d["excl_noinfo"],
        generado=esc(d["generado"]),
        paidtracker_html=paidtracker_html,
    )


# ═══════════════ Dashboard EJECUTIVO (CEO / comité) ═══════════════
EXEC_CSS = """
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
:root{
  --bg:#0c1b15; --bg2:#10251b; --card:#16302340; --card-solid:#183426; --card2:#13291e;
  --line:#2c5443; --line2:#3a6b54;
  --ink:#f2fff8; --ink2:#bcdccd; --mut:#83a593;
  --brand:#6ff0a2; --brand-2:#57e08a; --brand-d:#2bb673; --brand-deep:#0f4a30;
  --ok:#57e08a; --warn:#ffca5c; --bad:#ff7189; --sky:#68d1f5; --violet:#c8a6ff;
}
html{font-size:15px;-webkit-text-size-adjust:100%}
body{background:var(--bg);color:var(--ink);line-height:1.55;
  font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Inter,Roboto,Helvetica,Arial,sans-serif;
  background-image:
    radial-gradient(1200px 560px at 80% -12%,rgba(111,240,162,.16),transparent 62%),
    radial-gradient(900px 500px at 2% 3%,rgba(104,209,245,.08),transparent 55%),
    linear-gradient(180deg,#0e2019 0%,#0c1b15 40%);
  background-attachment:fixed;}
.tnum{font-variant-numeric:tabular-nums}
.wrap{max-width:1140px;margin:0 auto;padding:0 24px}
h1,h2,h3{line-height:1.14;letter-spacing:-.01em;text-wrap:balance}
.xhead{padding:26px 0 14px}
.xtop{display:flex;align-items:center;gap:14px;margin-bottom:20px;flex-wrap:wrap}
.xbrand{font-size:21px;font-weight:800;letter-spacing:-.02em}
.xbrand b{color:var(--brand)} .xbrand i{color:var(--brand);font-style:normal}
.tag{font-size:11px;color:var(--ink2);border:1px solid var(--line2);padding:6px 12px;border-radius:999px;background:rgba(111,240,162,.05)}
.xhead h1{font-size:clamp(26px,4.2vw,40px);font-weight:800;margin-bottom:9px}
.xhead h1 span{color:var(--brand);text-shadow:0 0 30px rgba(111,240,162,.35)}
.xhead p{color:var(--ink2);font-size:15.5px;line-height:1.6;max-width:900px;text-wrap:pretty}
.xhead p.hero-1l{max-width:none;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;font-size:15px}
@media(max-width:920px){.xhead p.hero-1l{white-space:normal}}
.xhead .upd{margin-top:10px;font-size:12px;color:var(--mut)}
.xhead .upd b{color:var(--ink2)}
details.dictx{margin-left:auto;background:rgba(111,240,162,.06);border:1px solid var(--line2);border-radius:12px;overflow:hidden}
details.dictx>summary{list-style:none;cursor:pointer;padding:8px 14px;font-size:12.5px;font-weight:700;color:var(--brand);display:flex;align-items:center;gap:7px;user-select:none}
details.dictx>summary::-webkit-details-marker{display:none}
details.dictx>summary .chev{transition:transform .2s;font-size:10px}
details.dictx[open]>summary .chev{transform:rotate(90deg)}
details.dictx .dwrap{padding:6px 14px 14px;display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:10px;max-width:900px}
details.dictx .d b{color:var(--brand);font-size:12.5px} details.dictx .d span{display:block;font-size:11.5px;color:var(--ink2);margin-top:3px}
details.dictx .d span b{color:var(--ink);font-size:11.5px}
details.dictx .dhdr{grid-column:1/-1;font-size:10.5px;font-weight:800;letter-spacing:.05em;text-transform:uppercase;color:var(--mut);margin-top:6px;padding-bottom:2px;border-bottom:1px solid var(--line2)}
section{padding:34px 0;border-top:1px solid var(--line)}
.q{font-size:11.5px;font-weight:800;letter-spacing:.14em;text-transform:uppercase;color:var(--brand)}
.sh{font-size:clamp(21px,3vw,28px);font-weight:800;margin:7px 0 5px}
.sh .tot{color:var(--brand);font-weight:800}
.sd{color:var(--ink2);font-size:13.5px;max-width:74ch;margin-bottom:18px}
.sd.wide{max-width:none}
.kg{display:grid;grid-template-columns:repeat(4,1fr);gap:13px}
.kc{background:linear-gradient(165deg,rgba(24,52,38,.9),rgba(19,41,30,.7));border:1px solid var(--line);
  border-radius:16px;padding:18px 16px;position:relative;overflow:hidden}
.kc::after{content:"";position:absolute;inset:0 0 auto 0;height:1px;background:linear-gradient(90deg,transparent,rgba(111,240,162,.4),transparent)}
.kc .kl{font-size:11px;font-weight:700;letter-spacing:.03em;text-transform:uppercase;color:var(--mut)}
.kc .kv{font-size:clamp(27px,3.7vw,38px);font-weight:800;line-height:1;margin:11px 0 8px;letter-spacing:-.02em}
.kc .kt{font-size:11.5px;color:var(--ink2);display:flex;align-items:center;gap:7px;flex-wrap:wrap}
.kc .emprow{margin-top:9px;padding-top:9px;border-top:1px dashed var(--line2);font-size:11px;color:var(--sky);display:flex;align-items:center;gap:6px;font-weight:700}
.kc .emprow .eb{font-size:15px;font-weight:800}
.trend{font-weight:800;font-size:11px;display:inline-flex;align-items:center;gap:3px}
.trend.up{color:var(--ok)} .trend.down{color:var(--bad)} .trend.flat{color:var(--mut)} .trend.zero{color:var(--ink)}
.kg.rates{grid-template-columns:repeat(auto-fit,minmax(185px,1fr))}
.kg.rates .kc{background:linear-gradient(165deg,rgba(43,182,115,.16),rgba(19,41,30,.5));border-color:var(--line2)}
.kg.rates .kc .kv{color:var(--brand)}
.rates-head{font-size:12px;color:var(--mut);margin:0 0 12px;font-weight:600}
.rates-head b{color:var(--ink2)}
.fnote{font-size:12px;color:var(--mut);border-left:2px solid var(--line2);padding-left:12px;margin-top:16px;line-height:1.5}
.fnote b{color:var(--ink2)}
.cg{display:grid;grid-template-columns:repeat(2,1fr);gap:18px}
.chartc{background:linear-gradient(165deg,rgba(24,52,38,.7),rgba(19,41,30,.5));border:1px solid var(--line);border-radius:16px;padding:18px 18px 14px}
.chartc .chd{display:flex;align-items:baseline;justify-content:space-between;margin-bottom:2px}
.chartc h3{font-size:13.5px;font-weight:800;color:var(--ink)}
.chartc .cbig{font-size:32px;font-weight:800;color:var(--brand);line-height:1;letter-spacing:-.02em}
.chartc .cn{font-size:11px;color:var(--mut);margin-bottom:8px}
.chartc svg{width:100%;height:auto;display:block}
.chartc .cfoot{font-size:11px;line-height:1.5;color:var(--mut);margin-top:10px;padding-top:9px;border-top:1px solid var(--line)}
.chartc .cfoot b{color:var(--ink2)}
/* banner de tasas de conversión (claro, corta visualmente) */
.ratesbanner{background:linear-gradient(135deg,#eefff7 0%,#d6f7e6 55%,#c3f0dd 100%);border-radius:18px;padding:22px 26px;margin:2px 0;box-shadow:0 8px 40px rgba(87,224,138,.14)}
.divbanner{display:flex;gap:18px;align-items:center;margin:12px 0;padding:22px 26px;border-radius:18px;
  background:linear-gradient(120deg,#6ff0a2 0%,#57e08a 55%,#34d399 100%);border:1px solid #8ff7bb;
  box-shadow:0 12px 44px rgba(87,224,138,.35)}
.divbanner .db-l{font-size:34px}
.divbanner .db-t{font-size:clamp(18px,2.6vw,24px);font-weight:800;color:#052012}
.divbanner .db-t span{color:#0a3d28}
.divbanner .db-s{font-size:13px;color:#0d3d29;margin-top:4px;max-width:80ch;font-weight:500}
/* inbound vs outbound dos columnas */
.io3{display:grid;grid-template-columns:1fr 1fr 1fr;gap:20px;margin-top:22px;position:relative;left:50%;transform:translateX(-50%);width:min(1280px,calc(100vw - 32px))}
.iocol{background:linear-gradient(165deg,rgba(24,52,38,.6),rgba(19,41,30,.4));border:1px solid var(--line);border-radius:16px;padding:18px}
.iocol.out{background:linear-gradient(165deg,rgba(52,42,24,.5),rgba(41,30,19,.4));border-color:#5a4a2a}
.iocol.brain{background:linear-gradient(165deg,rgba(40,30,55,.5),rgba(25,20,40,.4));border-color:#3f3560}
.iocol.brain .io-h .io-tot{color:var(--violet)}
.io-h{font-size:14px;font-weight:800;color:var(--ink);margin-bottom:14px;display:flex;align-items:center;gap:8px}
.io-h .io-tot{margin-left:auto;color:var(--brand);font-size:20px}
.iocol.out .io-h .io-tot{color:var(--warn)}
.mf{display:flex;flex-direction:column;gap:7px}
.mf-row{display:grid;grid-template-columns:minmax(150px,1fr) 1fr 48px;gap:14px;align-items:center;font-size:12.5px}
.mf-l{color:var(--ink2);white-space:nowrap} .mf-l b{color:var(--ink);font-size:15px}
.mf-bar{background:rgba(255,255,255,.05);border-radius:5px;height:12px;overflow:hidden}
.mf-fill{height:100%;background:linear-gradient(90deg,var(--brand-d),var(--brand))}
.iocol.out .mf-fill{background:linear-gradient(90deg,#a5741f,var(--warn))}
.mf-c{font-size:10.5px;color:var(--mut);font-weight:700;text-align:right}
.io-val{margin-top:14px;padding-top:12px;border-top:1px dashed var(--line2);font-size:11.5px;color:var(--mut);font-weight:700;display:flex;align-items:center;justify-content:space-between}
.io-val span{font-size:17px;font-weight:800;color:var(--brand)}
.iocol.out .io-val span{color:var(--warn)} .iocol.brain .io-val span{color:var(--violet)}
@media(max-width:820px){.io3{grid-template-columns:1fr}}
.src-chip{display:inline-block;font-size:11.5px;font-weight:800;padding:3px 10px;border-radius:999px;margin:2px 4px 2px 0}
.src-chip.in{background:rgba(111,240,162,.16);color:var(--brand);border:1px solid var(--brand-d)}
.src-chip.out{background:rgba(255,202,92,.16);color:var(--warn);border:1px solid #a5741f}
.src-chip.cx{background:rgba(104,209,245,.16);color:var(--sky);border:1px solid #1f7f96}
.src-chip.br{background:rgba(200,166,255,.16);color:var(--violet);border:1px solid #6a4fa0}
.rb-title{font-size:13px;font-weight:800;color:var(--brand);margin:4px 0 10px;letter-spacing:.01em}
.rb-title span{color:var(--mut);font-weight:600}
.rb-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:10px}
.rbc{text-align:center;padding:6px 8px;position:relative}
.rbc:not(:last-child)::after{content:"→";position:absolute;right:-8px;top:44%;color:#7bc9a1;font-weight:800;font-size:14px}
.rbc .rbl{font-size:10.5px;font-weight:800;text-transform:uppercase;letter-spacing:.02em;color:#1f7a4d}
.rbc .rbv{font-size:34px;font-weight:800;color:#0e3d2a;line-height:1;margin:8px 0 3px;letter-spacing:-.02em}
.rbc .rbs{font-size:10px;color:#3a6b54}
@media(max-width:560px){.rbc:not(:last-child)::after{display:none}}
.fnhead2{display:flex;justify-content:space-between;gap:12px;font-size:11px;color:var(--mut);margin-bottom:10px;font-weight:700}
.fnhead2 .rr{color:var(--sky)}
.fn{display:flex;flex-direction:column;gap:9px}
.fn .row{display:grid;grid-template-columns:158px 1fr 112px;gap:16px;align-items:center}
.fn .lab{text-align:right} .fn .lab .n{font-size:22px;font-weight:800;line-height:1}
.fn .lab .t{font-size:10.5px;text-transform:uppercase;letter-spacing:.05em;color:var(--mut);font-weight:700;margin-top:3px}
.fn .lab .lconv{font-size:10px;color:var(--brand);font-weight:800;margin-top:5px;white-space:nowrap}
.fn .track{position:relative;height:44px;display:flex;align-items:center}
.fn .fill{height:100%;border-radius:10px;min-width:70px;display:flex;align-items:center;padding-left:15px;
  font-size:12px;font-weight:800;color:#052012;
  background:linear-gradient(90deg,var(--brand-deep),var(--brand-2));box-shadow:0 0 24px rgba(111,240,162,.12)}
.fn .conv{position:absolute;right:8px;font-size:11px;color:var(--ink2);background:rgba(12,27,21,.85);
  border:1px solid var(--line2);border-radius:999px;padding:3px 11px;white-space:nowrap}
.fn .conv b{color:var(--brand)}
.fn .empc{text-align:right;color:var(--sky);font-weight:800;font-size:19px;line-height:1;font-variant-numeric:tabular-nums}
.fn .empc span{display:block;font-size:9.5px;color:var(--mut);font-weight:700;text-transform:uppercase;letter-spacing:.04em;margin-top:2px}
.bars{display:flex;flex-direction:column;gap:9px}
.brow{display:grid;grid-template-columns:170px 1fr 70px;gap:12px;align-items:center;font-size:13px}
.brow.zero{opacity:.42}
.brow .bl{color:var(--ink2);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.brow .bt{background:rgba(255,255,255,.05);border-radius:6px;height:20px;overflow:hidden}
.brow .bf{height:100%;border-radius:6px;background:linear-gradient(90deg,var(--brand-d),var(--brand));min-width:3px}
.brow .bn{text-align:right;font-weight:800} .brow .bn small{color:var(--mut);font-weight:600;font-size:10.5px}
/* matriz por fuente */
.mxwrap{overflow-x:auto}
.matrix{min-width:720px;display:flex;flex-direction:column;gap:7px}
.mx-head,.mx-row{display:grid;grid-template-columns:1.8fr .9fr .75fr .75fr .85fr 1fr 1fr;gap:8px;align-items:center}
.mx-head{font-size:10px;text-transform:uppercase;letter-spacing:.03em;color:var(--mut);font-weight:800;padding:0 12px 4px}
.mx-head span{text-align:right} .mx-head span:first-child{text-align:left}
.mx-row{background:linear-gradient(165deg,rgba(24,52,38,.6),rgba(19,41,30,.4));border:1px solid var(--line);border-radius:12px;padding:11px 12px}
.mx-row .c1{display:flex;flex-direction:column;gap:5px}
.mx-row .c1 .nm{font-size:12.5px;color:var(--ink);font-weight:700;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.mx-row .c1 .bt{background:rgba(255,255,255,.06);border-radius:5px;height:6px;overflow:hidden}
.mx-row .c1 .bf{height:100%;background:linear-gradient(90deg,var(--brand-d),var(--brand))}
.mx-cell{text-align:right;font-variant-numeric:tabular-nums}
.mx-cell .v{font-size:15px;font-weight:800;color:var(--ink)}
.mx-cell .p{font-size:9.5px;color:var(--mut);display:block}
.mx-cell .emp{font-size:9px;color:var(--sky);display:block;font-weight:700}
.mx-cell.hi .v{color:var(--brand)} .mx-cell.cv .v{color:var(--sky)}
.mx-cell.mut .v{color:var(--mut);font-weight:700}
.mx-row.mx-tot{background:rgba(148,163,184,.14);border-color:var(--line2)}
.mx-row.mx-tot .c1 .nm{color:var(--ink);font-weight:800}
.mx-row.mx-gtot{background:linear-gradient(120deg,rgba(111,240,162,.20),rgba(34,211,238,.16));border:1.5px solid var(--brand);border-radius:12px;padding-top:15px;padding-bottom:15px;margin-top:6px}
.mx-row.mx-gtot .c1 .nm{color:var(--brand);font-weight:900;font-size:15px}
.mx-row.mx-gtot .gsub{display:block;font-size:9.5px;color:var(--mut);font-weight:600;margin-top:2px}
.mx-row.mx-gtot .mx-cell .v{font-size:18px}
.mx-row.mx-gtot .mx-cell.hi .v{color:var(--brand)}
.mx-sep{font-size:11px;font-weight:800;letter-spacing:.04em;text-transform:uppercase;padding:10px 4px 4px;color:var(--brand)}
.mx-sep.out{color:var(--warn)}
.mx-row.mx-ob{background:linear-gradient(165deg,rgba(52,42,24,.35),rgba(41,30,19,.25));border-color:#4a3b22}
.mx-sep.br{color:var(--violet)}
.mx-row.mx-br{background:linear-gradient(165deg,rgba(40,30,55,.4),rgba(25,20,40,.3));border-color:#3f3560}
.mx-row.mx-br .c1 .nm{color:var(--violet);font-weight:800}
.mxd{background:transparent;border:none;padding:0}
.mxd>summary{list-style:none;cursor:pointer} .mxd>summary::-webkit-details-marker{display:none}
.mx-cell.op-clk{cursor:pointer} .mx-cell.op-clk .emp{color:var(--sky)}
.mxd[open]>summary .op-clk .emp::after{content:" (abierto)";color:var(--mut)}
.mxd .mx-deals{margin:2px 0 7px;padding:10px 14px;background:rgba(104,209,245,.05);border:1px solid rgba(104,209,245,.2);border-radius:10px;display:flex;flex-wrap:wrap;gap:6px;font-size:11px;color:var(--ink2)}
.mxd .mx-deals b{width:100%;color:var(--sky);font-size:11px;margin-bottom:2px}
.mxd .mx-deals span{background:rgba(104,209,245,.1);border:1px solid rgba(104,209,245,.25);padding:3px 9px;border-radius:6px}
/* 24h */
.bigblock{display:flex;gap:22px;align-items:center;background:linear-gradient(165deg,rgba(24,52,38,.7),rgba(19,41,30,.4));border:1px solid var(--line);border-radius:16px;padding:22px 24px;margin-bottom:20px;flex-wrap:wrap}
.bigblock .bn2{font-size:52px;font-weight:800;color:var(--brand);line-height:1;letter-spacing:-.03em}
.bigblock .bx{font-size:13px;color:var(--ink2)} .bigblock .bx b{color:var(--ink)}
.brow .sub{font-size:10px;color:var(--mut);font-weight:600;display:block;margin-top:2px}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:13px}
.stat{background:linear-gradient(165deg,rgba(24,52,38,.7),rgba(19,41,30,.5));border:1px solid var(--line);border-radius:14px;padding:17px}
.stat .sv{font-size:27px;font-weight:800;line-height:1} .stat .sl{font-size:11.5px;color:var(--ink2);margin-top:6px}
.stat.ok{border-color:rgba(87,224,138,.4)} .stat.ok .sv{color:var(--ok)}
.stat.warn{border-color:rgba(255,202,92,.4)} .stat.warn .sv{color:var(--warn)}
.stat.bad{border-color:rgba(255,113,137,.4)} .stat.bad .sv{color:var(--bad)}
.q3{display:grid;grid-template-columns:repeat(4,1fr);gap:14px}
.qcol{background:linear-gradient(165deg,rgba(24,52,38,.6),rgba(19,41,30,.4));border:1px solid var(--line);border-radius:16px;padding:20px;text-align:center}
.qcol .qi{font-size:22px} .qcol .qv{font-size:32px;font-weight:800;margin:8px 0 2px;color:var(--brand)} .qcol .ql{font-size:12px;color:var(--ink2)}
.qcol .qp{font-size:12px;color:var(--sky);font-weight:800;margin-top:4px}
.qcol .qsplit{font-size:11px;color:var(--ink2);margin-top:8px;padding-top:8px;border-top:1px dashed var(--line2);font-weight:700}
.qcol .qsplit small{color:var(--mut);font-weight:600}
.qcol .qnote{font-size:9.5px;color:var(--mut);margin-top:6px;font-style:italic}
.brow.big24 .bn{font-size:19px} .brow.big24 .bn .sub{font-size:10px}
.bf.ok{background:linear-gradient(90deg,var(--brand-d),var(--brand))!important}
.bf.bad{background:linear-gradient(90deg,#b23b4e,var(--bad))!important}
.bf.mut{background:linear-gradient(90deg,#2c5443,#4a7a63)!important}
.razd{margin-top:16px;border:1px solid var(--line2);border-radius:12px;overflow:hidden;background:rgba(12,27,21,.4)}
.razd>summary{list-style:none;cursor:pointer;padding:11px 14px;font-size:12.5px;font-weight:800;color:var(--bad);display:flex;align-items:center;gap:8px;user-select:none}
.razd>summary::-webkit-details-marker{display:none}
.razd .chev{font-size:9px;transition:transform .2s;color:var(--mut)}
.razd[open] .chev{transform:rotate(90deg)}
.razd .razbox{margin:0;border:none;border-top:1px solid var(--line2);border-radius:0}
.elist{list-style:none;text-align:left;font-size:12.5px;color:var(--ink2);display:flex;flex-direction:column;gap:9px}
.elist li{padding-left:20px;position:relative} .elist li::before{content:"→";position:absolute;left:0;color:var(--warn)}
.fstep.bad2 b{color:var(--bad)}
.sqlintro{list-style:none;margin:0 0 20px;display:flex;flex-direction:column;gap:10px}
.sqlintro li{font-size:13px;line-height:1.55;color:var(--ink2);padding:12px 15px;background:var(--card2);border:1px solid var(--line);border-left:3px solid var(--brand);border-radius:10px}
.sqlintro li b{color:var(--ink)}
.part{font-size:13.5px;font-weight:800;color:var(--brand);margin:6px 0 14px;padding-bottom:8px;border-bottom:1px solid var(--line);letter-spacing:.01em}
.part.part-bad{color:var(--bad)}
/* SQL · niveles desplegables */
.sqlvl3{display:grid;grid-template-columns:repeat(3,1fr);gap:16px;align-items:start}
.lvl{background:linear-gradient(165deg,rgba(24,52,38,.5),rgba(19,41,30,.35));border:1px solid var(--line2);border-radius:16px;overflow:hidden}
.lvl.lvl-bad{background:linear-gradient(165deg,rgba(52,28,32,.45),rgba(41,22,26,.3));border-color:rgba(255,107,91,.28)}
.lvl.lvl3{background:linear-gradient(165deg,rgba(28,40,58,.5),rgba(20,30,45,.35));border-color:rgba(34,211,238,.28)}
.lvl .ph{font-size:11.5px;color:var(--mut);line-height:1.5;margin-bottom:12px}
.lvl-subh{font-size:11px;font-weight:800;letter-spacing:.03em;text-transform:uppercase;color:var(--ink2);margin:16px 0 4px}
.lvl-sum{list-style:none;cursor:pointer;display:flex;align-items:center;gap:11px;padding:15px 16px;user-select:none}
.lvl-sum::-webkit-details-marker{display:none}
.lvl-badge{flex:none;width:26px;height:26px;border-radius:8px;display:flex;align-items:center;justify-content:center;font-weight:900;font-size:14px;color:#04120b}
.lvl-badge.b1{background:var(--brand)} .lvl-badge.b2{background:var(--bad);color:#fff} .lvl-badge.b3{background:var(--sky);color:#04120b}
.lvl-tit{flex:1;font-size:13px;font-weight:800;color:var(--ink);line-height:1.35} .lvl-tit small{color:var(--mut);font-weight:600}
.lvl-n{flex:none;font-size:20px;font-weight:900;color:var(--ink);font-variant-numeric:tabular-nums}
.lvl.lvl-bad .lvl-n{color:var(--bad)} .lvl.lvl3 .lvl-n{color:var(--sky)}
.lvl-sum .chev{flex:none;font-size:10px;color:var(--mut);transition:transform .2s}
.lvl[open] .lvl-sum .chev{transform:rotate(90deg)}
.lvl-body{padding:0 16px 18px;border-top:1px solid var(--line);margin-top:2px;padding-top:16px}
.lvl3-grid{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-top:12px}
.lvl3-h{font-size:12px;font-weight:800;color:var(--ink2);margin-bottom:10px}
.bf.bf-cold{background:linear-gradient(90deg,#64748b,#94a3b8)} .bf.bf-warm{background:linear-gradient(90deg,#f59e0b,#fbbf24)} .bf.bf-adv{background:linear-gradient(90deg,#22c55e,#6ff0a2)}
.paid3{background:rgba(34,211,238,.06);border:1px solid rgba(34,211,238,.25);border-radius:14px;padding:15px}
.paid3-empty{color:var(--ink2);font-size:12.5px;line-height:1.55}
.paid3-h{font-size:12.5px;font-weight:800;color:var(--ink)} .paid3-h span{font-weight:600;color:var(--mut);font-size:10.5px}
.paid3-tot{font-size:13px;color:var(--ink2);margin:6px 0 12px} .paid3-tot b{font-size:22px;color:var(--sky);font-weight:900}
.ptr{display:flex;justify-content:space-between;align-items:center;padding:6px 0;border-bottom:1px solid rgba(148,163,184,.12);font-size:12.5px}
.ptr:last-child{border-bottom:none} .ptr-l{color:var(--ink2)} .ptr-n{font-weight:800;color:var(--ink)} .ptr-n small{color:var(--mut);font-weight:600;font-size:10.5px}
.paid3-foot{margin-top:11px;font-size:11px;color:var(--mut);line-height:1.5}
@media(max-width:860px){ .sqlvl3{grid-template-columns:1fr} .lvl3-grid{grid-template-columns:1fr} }
.p2{display:grid;grid-template-columns:1.35fr 1fr;gap:16px}
.pcol{background:linear-gradient(165deg,rgba(24,52,38,.7),rgba(19,41,30,.5));border:1px solid var(--line);border-radius:16px;padding:20px}
.pcol.b{border-color:rgba(255,202,92,.3)}
.pcol h4{font-size:14px;font-weight:800;margin-bottom:4px} .pcol .ph{font-size:11.5px;color:var(--mut);margin-bottom:16px;line-height:1.5}
.flow{display:flex;align-items:stretch;gap:8px;flex-wrap:wrap}
.fstep{flex:1;min-width:74px;background:rgba(12,27,21,.5);border:1px solid var(--line);border-radius:12px;padding:12px 10px;text-align:center}
.fstep b{display:block;font-size:24px;font-weight:800;color:var(--ink);line-height:1} .fstep span{font-size:10px;color:var(--mut);display:block;margin-top:5px;line-height:1.3}
.fstep.ok b{color:var(--brand)}
.farr{display:flex;flex-direction:column;align-items:center;justify-content:center;color:var(--mut);font-weight:800;font-size:15px;min-width:40px}
.farr .fp{font-size:10.5px;color:var(--brand);font-weight:800}
.razbox{margin-top:16px;background:rgba(255,113,137,.06);border:1px solid rgba(255,113,137,.25);border-radius:12px;padding:14px}
.razbox .rh{font-size:12.5px;font-weight:800;color:var(--bad);margin-bottom:2px}
.razbox .rs{font-size:11px;color:var(--mut);margin-bottom:10px}
.mrow{display:grid;grid-template-columns:1fr 78px;gap:8px;font-size:12px;padding:6px 0;border-top:1px solid rgba(255,113,137,.15)}
.mrow .ml{color:var(--ink2)} .mrow .mn{text-align:right;font-weight:800;color:var(--ink)} .mrow .mn small{color:var(--mut);font-weight:600;font-size:10px}
.emailbox{text-align:center;padding:8px 0}
.emailbox .eb{font-size:44px;font-weight:800;color:var(--warn);line-height:1}
.emailbox ul{list-style:none;margin-top:14px;text-align:left;font-size:12px;color:var(--ink2);display:flex;flex-direction:column;gap:8px}
.emailbox li{padding-left:20px;position:relative} .emailbox li::before{content:"→";position:absolute;left:0;color:var(--warn)}
.chip{display:inline-block;font-size:10px;font-weight:800;padding:2px 8px;border-radius:999px;margin-left:6px}
.chip.discov{background:rgba(104,209,245,.15);color:var(--sky)} .chip.demo{background:rgba(111,240,162,.15);color:var(--brand)}
.chip.best{background:rgba(200,166,255,.15);color:var(--violet)}
.pipe-legend{display:flex;gap:14px;flex-wrap:wrap;font-size:12px;color:var(--ink2);margin-bottom:16px}
.pipe-legend b{color:var(--ink)}
details.chdeals{border:1px solid var(--line);border-radius:10px;margin-bottom:8px;overflow:hidden;background:linear-gradient(165deg,rgba(24,52,38,.5),rgba(19,41,30,.3))}
details.chdeals>summary{list-style:none;cursor:pointer;display:grid;grid-template-columns:170px 1fr 70px;gap:12px;align-items:center;padding:9px 12px;font-size:13px}
details.chdeals>summary::-webkit-details-marker{display:none}
details.chdeals>summary .bl{color:var(--ink2)} details.chdeals>summary .bl::before{content:"▸ ";color:var(--sky)}
details.chdeals[open]>summary .bl::before{content:"▾ "}
details.chdeals .dl{padding:2px 14px 12px 28px;display:flex;flex-wrap:wrap;gap:6px}
details.chdeals .dl span{font-size:11px;background:rgba(104,209,245,.1);border:1px solid rgba(104,209,245,.25);color:var(--ink2);padding:3px 9px;border-radius:6px}
.tblwrap{overflow-x:auto}
.tbl{width:100%;border-collapse:collapse;font-size:13px;min-width:560px}
.tbl th{text-align:right;font-size:10.5px;text-transform:uppercase;letter-spacing:.03em;color:var(--mut);font-weight:700;padding:10px 12px;border-bottom:1px solid var(--line2);white-space:nowrap}
.tbl th:first-child,.tbl td:first-child{text-align:left}
.tbl td{padding:12px;border-bottom:1px solid rgba(44,84,67,.4);font-variant-numeric:tabular-nums;text-align:right;white-space:nowrap}
.tbl tr:last-child td{border-bottom:none}
.tbl td.hi{color:var(--brand);font-weight:800} .tbl td.cv{color:var(--sky);font-weight:800}
.strat{display:flex;gap:18px;align-items:center;margin-top:20px;padding:20px 24px;border-radius:16px;
  background:linear-gradient(135deg,#123a2a,#0f2f32);border:1px solid var(--brand-d);border-left:4px solid var(--brand);
  box-shadow:0 8px 34px rgba(87,224,138,.18);font-size:14px;line-height:1.6;color:#eafff4}
.strat .strat-i{font-size:34px;flex:0 0 auto}
.strat b{color:var(--brand)}
.note{background:linear-gradient(150deg,rgba(111,240,162,.12),rgba(111,240,162,.02));border:1px solid var(--line2);border-radius:14px;padding:16px 18px;font-size:13px;color:var(--ink2);margin-top:18px}
.note b{color:var(--brand)}
.ins{display:flex;flex-direction:column;gap:10px}
.ins .i{display:flex;gap:12px;align-items:flex-start;background:linear-gradient(165deg,rgba(24,52,38,.6),rgba(19,41,30,.4));border:1px solid var(--line);border-radius:12px;padding:15px 17px}
.ins .i .dot{flex:0 0 auto;width:9px;height:9px;border-radius:50%;margin-top:6px;background:var(--brand);box-shadow:0 0 12px var(--brand)}
.ins .i.warn .dot{background:var(--warn);box-shadow:0 0 12px var(--warn)} .ins .i.bad .dot{background:var(--bad);box-shadow:0 0 12px var(--bad)}
.ins .i p{font-size:13px;color:var(--ink);margin:0}
.acts{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:13px}
.act{background:linear-gradient(165deg,rgba(24,52,38,.7),rgba(19,41,30,.5));border:1px solid var(--line);border-left:3px solid var(--brand);border-radius:12px;padding:15px 17px;font-size:13px;color:var(--ink2)}
.act b{color:var(--ink);display:block;margin-bottom:3px;font-size:13.5px}
.pend{background:repeating-linear-gradient(135deg,rgba(255,202,92,.06),rgba(255,202,92,.06) 12px,transparent 12px,transparent 24px);
  border:1px dashed rgba(255,202,92,.45);border-radius:14px;padding:18px 20px;font-size:13px;color:var(--ink2)}
.pend b{color:var(--warn)}
footer{padding:34px 0 56px;text-align:center;color:var(--mut);font-size:12px;border-top:1px solid var(--line);margin-top:10px}
@media(max-width:860px){ .kg,.cg{grid-template-columns:1fr 1fr} .p2{grid-template-columns:1fr} .q3{grid-template-columns:repeat(2,1fr)} }
@media(max-width:560px){ .kg{grid-template-columns:1fr 1fr} .cg{grid-template-columns:1fr} .fn .row{grid-template-columns:88px 1fr}
  .brow{grid-template-columns:120px 1fr 58px} }
"""


def render_exec(d):
    cum = d["cum"]
    tr = d["trends"]
    ex = d["exec_extra"]
    def fmt(n):
        try: return f"{int(n):,}".replace(",", ".")
        except (TypeError, ValueError): return str(n)
    def pv(a, b):
        return f"{round(a / b * 100)}%" if b else "—"
    def pvf(a, b):
        if not b: return "—"
        r = a / b * 100
        return "<1%" if 0 < r < 1 else f"{round(r)}%"
    def arrow(t):
        # % variación vs los 7 días previos (flecha+color) · +N nuevos de esta semana (color por crecimiento)
        last7 = t.get("last7", 0); prev7 = t.get("prev7", 0)
        up = last7 >= prev7
        sym = "▲" if up else "▼"; cls = "up" if up else "down"
        pct_txt = f"{(last7 - prev7) / prev7 * 100:+.0f}%" if prev7 > 0 else "nuevo"
        numcls = "zero" if last7 == 0 else ("up" if up else "down")
        return (f'<span class="trend {cls}">{sym} {pct_txt}</span>'
                f'<span class="trend {numcls}">+{last7}</span>'
                f'<span style="color:var(--mut);font-weight:600;font-size:10.5px">nuevos · 7d</span>')

    opp_c = ex["opp_contacts"]; cli_c = ex["cli_contacts"]
    opp_e = d["opp_companies"]; cli_e = d["cli_companies"]
    # KPIs principales de Oportunidades/Clientes → SOLO inbound
    opp_ci = ex.get("opp_contacts_mkt", opp_c); cli_ci = ex.get("cli_contacts_mkt", cli_c)
    opp_ei = ex.get("opp_emp_mkt", opp_e); cli_ei = ex.get("cli_emp_mkt", cli_e)
    reun_total = ex["reun_total"]; reun_st = ex["reun_by_stage"]; reun_tr = ex["reun_trend"]
    free_total = cum.get("free", 0); free7 = ex["free_last7"]
    # MQL = de facto (contenido consumido); SQL = de consultoría gestionable (los que cuadran)
    mql_d = d["origin"].get("content", cum["mql"])
    sql_d = d["sql_disp"].get("total", cum["sql"])
    total_nf = ex.get("total_contactos", cum["total"])   # contactos SIN Freemium (inbound)
    # OUTBOUND (Juanma) y TOTALES GLOBALES (inbound + outbound)
    ob = ex.get("out", {"contactos": 0, "lead": 0, "mql": 0, "sql": 0, "opp": 0, "cli": 0, "opp_emp": 0, "cli_emp": 0})
    g_contactos = total_nf + ob["contactos"]
    g_lead = cum["lead"] + ob["lead"]
    g_mql = mql_d + ob["mql"]; g_sql = sql_d + ob["sql"]
    g_opp = opp_ci + ob["opp"]; g_cli = cli_ci + ob["cli"]
    g_opp_e = opp_ei + ob["opp_emp"]; g_cli_e = cli_ei + ob["cli_emp"]
    # ── Oportunidades REALES = negocios con deal asociado (no el lifecycle "opportunity" inflado por
    #    automatismos/importaciones). Suma inbound + outbound + Brain para cuadrar con la matriz. ──
    opp_inb_real = sum(len(v) for v in ex.get("deals_by_chan", {}).values())
    opp_out_real = sum(len(v) for v in ex.get("deals_by_chan_out", {}).values())
    opp_brain_real = ex.get("brain_open", 0)
    opp_real = opp_inb_real + opp_out_real + opp_brain_real
    pq = d["preq"]
    ag_contact = pq.get("ag_calls_unique", 0) + pq.get("ag_reuniones", 0)   # llamadas + agendas de Agustín
    def _short_stage(s):
        s = (s or "").lower()
        if "discov" in s: return "discovery"
        if "demo" in s or "reuni" in s: return "demo"
        if "needs" in s or "valid" in s: return "needs valid."
        if "best" in s: return "best case"
        if "contest" in s: return "contestado"
        if "align" in s: return "alineación"
        return (s[:12] or "otra")
    # Reuniones en pipeline = negocios vivos (ventas + brain) por persona
    # Mostramos TODOS los propietarios (incluye Agustín, que antes quedaba fuera del top-4)
    reun_pipe_break = " · ".join(f'{c} {esc(o)}' for o, c in ex.get("reun_owner", [])[:6]) or "—"
    reun_pipe_tot = ex.get("reun_owner_total", ex.get("pipeline_count", 0))
    # Nota: "Sin asignar" son casi todos negocios de Brain (relaciones de Alex sin propietario)
    _rown = dict(ex.get("reun_owner", []))
    reun_sinasig = _rown.get("Sin asignar", 0)

    # ---------- 1 · EXECUTIVE SUMMARY ----------
    def kpi(lab, val, t, sub):
        return (f'<div class="kc"><div class="kl">{lab}</div><div class="kv tnum">{fmt(val)}</div>'
                f'<div class="kt">{arrow(t)}<span>· {sub}</span></div></div>')
    def kpi_emp(lab, val_c, emp, t, sub):
        return (f'<div class="kc"><div class="kl">{lab}</div><div class="kv tnum">{fmt(val_c)}</div>'
                f'<div class="kt">{arrow(t)}<span>· {sub}</span></div>'
                f'<div class="emprow">🏢 <span class="eb tnum">{fmt(emp)}</span> empresas / negocios</div></div>')
    def io(inb, out):  # etiqueta pequeña inbound/outbound
        return f'<span style="color:var(--mut)">inb {fmt(inb)} · out {fmt(out)}</span>'
    def kpi_io(lab, val, t, inb, out):
        return (f'<div class="kc"><div class="kl">{lab}</div><div class="kv tnum">{fmt(val)}</div>'
                f'<div class="kt">{arrow(t)}</div>'
                f'<div class="kt" style="margin-top:5px">{io(inb, out)}</div></div>')
    def kpi_emp_io(lab, val_c, emp, t, inb, out, conv):
        return (f'<div class="kc"><div class="kl">{lab}</div><div class="kv tnum">{fmt(val_c)}</div>'
                f'<div class="kt">{arrow(t)}<span style="color:var(--mut)">· {conv}</span></div>'
                f'<div class="kt" style="margin-top:5px">{io(inb, out)}</div>'
                f'<div class="emprow">🏢 <span class="eb tnum">{fmt(emp)}</span> empresas / negocios</div></div>')
    kpi_html = (
        kpi_io("Nuevos contactos", g_contactos, tr["contactos"], total_nf, ob["contactos"]) +
        kpi_io("Leads", g_lead, tr["leads"], cum["lead"], ob["lead"]) +
        kpi_io("MQL", g_mql, tr["mql"], mql_d, ob["mql"]) +
        kpi_io("SQL", g_sql, tr["sql"], sql_d, ob["sql"]) +
        # ── 2ª fila ──
        f'<div class="kc"><div class="kl">Llamadas precualif.</div><div class="kv tnum">{fmt(ag_contact)}</div>'
        f'<div class="kt" style="color:var(--mut)">SQL ≥3.000 · Agustín · desde 9 jul</div>'
        f'<div class="kt" style="margin-top:5px;color:var(--ink2)">📞 {pq.get("ag_calls_unique",0)} teléfono · 📅 {pq.get("ag_reuniones",0)} agenda</div></div>'
        + f'<div class="kc"><div class="kl">Oportunidades <span style="color:var(--mut);font-weight:600;font-size:10px">contactos · con negocio</span></div>'
        f'<div class="kv tnum">{fmt(ex.get("opp_contactos",0))}</div>'
        f'<div class="kt"><span style="color:var(--mut)">contactos en etapa oportunidad con deal asociado</span></div>'
        f'<div class="kt" style="margin-top:5px"><span style="color:var(--mut)">negocios: inb {fmt(opp_inb_real)} · out {fmt(opp_out_real)} · 🧠 brain {fmt(opp_brain_real)}</span></div>'
        f'<div class="emprow">🏢 <span class="eb tnum">{fmt(ex.get("opp_empresas",0) or opp_real)}</span> empresas / negocios</div></div>'
        + f'<div class="kc"><div class="kl">Clientes</div><div class="kv tnum">{fmt(ex.get("cli_split",{}).get("contactos",0))}</div>'
        f'<div class="kt" style="color:var(--mut)">contactos de la cartera real · pipeline «Clientes»</div>'
        f'<div class="emprow">🏢 <span class="eb tnum">{fmt(ex.get("clientes_activos",0))}</span> empresas cliente activas</div></div>'
        + f'<div class="kc"><div class="kl">Churn</div><div class="kv tnum">{fmt(ex.get("churn",{}).get("contactos",0))}</div>'
        f'<div class="kt" style="color:var(--mut)">han sido cliente desde el 1 ene y hoy ya no lo son</div>'
        f'<div class="emprow">🏢 <span class="eb tnum">{fmt(ex.get("churn",{}).get("empresas",0))}</span> empresas (Churned / Dormidos)</div></div>')
    # contactos por etapa (reales)
    _opp_ct = ex.get("opp_contactos", 0)
    _cli_ct = ex.get("cli_split", {}).get("contactos", 0)
    _churn_ct = ex.get("churn", {}).get("contactos", 0)
    _churn_pct = pvf(_churn_ct, _churn_ct + _cli_ct)
    # tasas: sobre contactos (comparable etapa a etapa)
    rates = [
        ("Lead → MQL", pv(g_mql, g_lead), "global · sobre contactos"),
        ("MQL → SQL", pv(g_sql, g_mql), "global · sobre contactos"),
        ("SQL → Oportunidad", pvf(_opp_ct, g_sql), "contactos con negocio / SQL"),
        ("Oportunidad → Cliente", pvf(_cli_ct, _opp_ct), "contactos cliente / oportunidad"),
        ("Cliente → Churn", _churn_pct, "contactos · desde 1 ene"),
    ]
    rate_html = "".join(
        f'<div class="rbc"><div class="rbl">{lab}</div><div class="rbv tnum">{val}</div>'
        f'<div class="rbs">{sub}</div></div>'
        for lab, val, sub in rates)

    # ---------- INBOUND vs OUTBOUND · dos columnas ----------
    def mini_funnel(st):
        top = st[0][1] or 1
        rows = ""
        for i, (lab, val) in enumerate(st):
            w = max(5, round(val / top * 100))
            conv = "" if i == 0 else f'<span class="mf-c">{pv(val, top)}</span>'
            rows += (f'<div class="mf-row"><div class="mf-l"><b class="tnum">{fmt(val)}</b> {lab}</div>'
                     f'<div class="mf-bar"><div class="mf-fill" style="width:{w}%"></div></div>{conv}</div>')
        return rows
    # Oportunidad = negocios reales con deal (por vía); Cliente = cuentas de cliente por fuente
    inb_st = [("Contactos", total_nf), ("Leads", cum["lead"]), ("MQL", mql_d), ("SQL", sql_d), ("Oportunidad (negocio)", opp_inb_real), ("Cliente", ex.get("cli_split",{}).get("inbound",0))]
    out_st = [("Contactos", ob["contactos"]), ("Leads", ob["lead"]), ("MQL", ob["mql"]), ("SQL", ob["sql"]), ("Oportunidad (negocio)", opp_out_real), ("Cliente", ex.get("cli_split",{}).get("outbound",0))]
    inb_fn = mini_funnel(inb_st); out_fn = mini_funnel(out_st)

    # ---------- 2 · EVOLUCIÓN (4 gráficos con total por mes) ----------
    _imp_note = ('<br>⚠️ El total infla porque cuenta por <b>fecha de creación</b>, no por evolución real: ha habido '
                 '<b>importaciones automáticas</b> que generaron SQLs/oportunidades de golpe (y no descuenta los que se '
                 'eliminan, se descartan o no cualifican). El dato vivo real es el de los KPIs de arriba.')
    charts = [
        ("MQL", mql_d, ex["svg_mql_m"], ex.get("note_mql", "")),
        ("SQL alcanzados", cum["sql"], ex["svg_sql_m"], ex.get("note_sql", "") + _imp_note),
        ("Oportunidades", opp_e, ex["svg_opp_m"], ex.get("note_opp", "") + _imp_note),
        ("Clientes", cli_e, ex["svg_cli_m"], ex.get("note_cli", "")),
    ]
    charts_html = "".join(
        f'<div class="chartc"><div class="chd"><h3>{lab}</h3><span class="cbig tnum">{fmt(val)}</span></div>'
        f'<div class="cn">acumulado diario · 1 ene → hoy · el nº sobre la línea es el total al cierre de cada mes</div>{svg}'
        f'<div class="cfoot">{note}</div></div>'
        for lab, val, svg, note in charts)

    # ---------- 3 · FUNNEL ----------
    # Oportunidad = reales (con deal); Cliente = cuentas activas del pipeline Clientes
    stages = [("Contactos", g_contactos, None), ("Leads", g_lead, None), ("MQL", g_mql, None),
              ("SQL", g_sql, None), ("Oportunidad", opp_real, None), ("Cliente", ex.get("clientes_activos", 0), None)]
    top = stages[0][1] or 1
    fn_rows = ""
    for i, (lab, val, emp) in enumerate(stages):
        w = max(6, round(val / top * 100))
        lconv = "" if i == 0 else f'<div class="lconv">↳ {pv(val, top)} del total de contactos</div>'
        empcell = f'<div class="empc">🏢 {fmt(emp)}<span>empresas</span></div>' if emp is not None else '<div class="empc"></div>'
        fn_rows += (f'<div class="row"><div class="lab"><div class="n tnum">{fmt(val)}</div>'
                    f'<div class="t">{lab}</div>{lconv}</div><div class="track">'
                    f'<div class="fill" style="width:{w}%"></div></div>{empcell}</div>')

    # ---------- CONTACTOS POR FUENTE · matriz acumulada ----------
    cm = ex["chan_matrix"]
    cm_tot = sum(e["contactos"] for _, e in cm) or 1
    cmax = max((e["contactos"] for _, e in cm), default=0) or 1
    def cell(v, extra="", cls=""):
        return f'<div class="mx-cell {cls}"><span class="v tnum">{fmt(v)}</span>{extra}</div>'
    dbc_m = ex.get("deals_by_chan", {})
    # Unir canales con contactos + canales que SOLO tienen negocio (para que las oportunidades por fila sumen el total)
    _cmd = {lbl: dict(e) for lbl, e in cm}
    for lbl in dbc_m:
        if lbl not in _cmd:
            _cmd[lbl] = {"contactos": 0, "leads": 0, "mql": 0, "sql": 0, "opp_c": 0, "cli_c": 0}
    cm_merged = sorted(_cmd.items(), key=lambda x: (-x[1]["contactos"], -len(dbc_m.get(x[0], []))))
    mx_rows = ""
    for lbl, e in cm_merged:
        items = dbc_m.get(lbl, [])
        opp_deals = len(items)   # oportunidades REALES = negocios asociados en pipeline
        pct_c = f'<span class="p">{pv(e["contactos"], cm_tot)}</span>'
        bar_w = round(e["contactos"] / cmax * 100)
        conv_o = pvf(opp_deals, e["contactos"])
        opp_cell = (f'<div class="mx-cell op-clk"><span class="v tnum">{opp_deals}</span><span class="emp">🏢 ver ▾</span></div>'
                    if items else cell(opp_deals, '<span class="p">—</span>'))
        row_inner = (
            f'<div class="c1"><span class="nm">{esc(lbl)}</span>'
            f'<div class="bt"><div class="bf" style="width:{bar_w}%"></div></div></div>'
            + cell(e["contactos"], pct_c)
            + cell(e["leads"]) + cell(e["mql"]) + cell(e["sql"], cls="hi")
            + opp_cell
            + f'<div class="mx-cell cv"><span class="v tnum">{conv_o}</span><span class="p">contacto→op.</span></div>')
        if items:
            deals_list = "".join(f'<span>{esc(nm)} · {esc(sl)}</span>' for nm, sl in items)
            mx_rows += (f'<details class="mxd"><summary class="mx-row">{row_inner}</summary>'
                        f'<div class="mx-deals"><b>Oportunidades de {esc(lbl)}:</b> {deals_list}</div></details>')
        else:
            mx_rows += f'<div class="mx-row">{row_inner}</div>'
    # fila TOTAL (suma = total de contactos)
    t_c = sum(e["contactos"] for _, e in cm); t_l = sum(e["leads"] for _, e in cm)
    t_m = sum(e["mql"] for _, e in cm); t_s = sum(e["sql"] for _, e in cm)
    t_o = sum(len(v) for v in dbc_m.values())
    mx_total = (
        '<div class="mx-row mx-tot">'
        '<div class="c1"><span class="nm">Total inbound</span></div>'
        + cell(t_c) + cell(t_l) + cell(t_m) + cell(t_s, cls="hi") + cell(t_o)
        + f'<div class="mx-cell cv"><span class="v tnum">{pvf(t_o, t_c)}</span></div>'
        + '</div>')
    # OUTBOUND rows + total outbound + total global
    cmo = ex.get("chan_matrix_out", [])
    dbco_m = ex.get("deals_by_chan_out", {})
    # Unir fuentes con contactos + fuentes que SOLO tienen negocio (para que las filas sumen el total outbound)
    _cmod = {lbl: dict(e) for lbl, e in cmo}
    for lbl in dbco_m:
        if lbl not in _cmod:
            _cmod[lbl] = {"contactos": 0, "leads": 0, "mql": 0, "sql": 0}
    cmo_merged = sorted(_cmod.items(), key=lambda x: (-x[1]["contactos"], -len(dbco_m.get(x[0], []))))
    mx_rows_out = ""
    for lbl, e in cmo_merged:
        items = dbco_m.get(lbl, [])
        opp_deals = len(items)   # oportunidades OUTBOUND = negocios asociados en pipeline
        conv_o = pvf(opp_deals, e["contactos"])
        opp_cell = (f'<div class="mx-cell op-clk"><span class="v tnum">{opp_deals}</span><span class="emp">🏢 ver ▾</span></div>'
                    if items else cell(opp_deals, '<span class="p">—</span>'))
        row_inner = (
            f'<div class="c1"><span class="nm">{esc(lbl)}</span></div>'
            + cell(e["contactos"]) + cell(e["leads"]) + cell(e["mql"]) + cell(e["sql"], cls="hi")
            + opp_cell
            + f'<div class="mx-cell cv"><span class="v tnum">{conv_o}</span><span class="p">contacto→op.</span></div>')
        if items:
            deals_list = "".join(f'<span>{esc(nm)} · {esc(sl)}</span>' for nm, sl in items)
            mx_rows_out += (f'<details class="mxd"><summary class="mx-row mx-ob">{row_inner}</summary>'
                            f'<div class="mx-deals"><b>Oportunidades de {esc(lbl)}:</b> {deals_list}</div></details>')
        else:
            mx_rows_out += f'<div class="mx-row mx-ob">{row_inner}</div>'
    oc_c = sum(e["contactos"] for _, e in cmo); oc_l = sum(e["leads"] for _, e in cmo)
    oc_m = sum(e["mql"] for _, e in cmo); oc_s = sum(e["sql"] for _, e in cmo)
    oc_o = sum(len(v) for v in dbco_m.values())   # TODAS las oportunidades outbound con negocio (cuadra con el KPI)
    mx_total_out = (
        '<div class="mx-row mx-tot">'
        '<div class="c1"><span class="nm">Total outbound</span></div>'
        + cell(oc_c) + cell(oc_l) + cell(oc_m) + cell(oc_s, cls="hi") + cell(oc_o)
        + f'<div class="mx-cell cv"><span class="v tnum">{pvf(oc_o, oc_c)}</span></div>'
        + '</div>') if cmo_merged else ''
    sep_in = '<div class="mx-sep in">🟢 Inbound · por canal de adquisición</div>'
    sep_out = '<div class="mx-sep out">🟠 Outbound · fuentes no-inbound (comercial/prospección · importaciones · offline · integración). «Comercial/prospección» = cuentas enterprise creadas a mano por ventas (Wingo, PC Componentes, Telefónica, Publicis…), sin fuente de marketing.</div>' if cmo_merged else ''
    # BRAIN · oportunidades de relaciones estratégicas (sin embudo de contactos conectado)
    brain_o = ex.get("brain_open", 0)
    sep_brain = '<div class="mx-sep br">🧠 Brain · relaciones estratégicas (solo oportunidades)</div>' if brain_o else ''
    mx_brain = (
        '<div class="mx-row mx-br">'
        '<div class="c1"><span class="nm">🧠 Brain</span></div>'
        + '<div class="mx-cell mut"><span class="v">—</span></div>' * 4
        + cell(brain_o)
        + '<div class="mx-cell"><span class="p">negocios Brain</span></div>'
        + '</div>') if brain_o else ''
    g_opp_all = t_o + oc_o + brain_o
    g_total = (
        '<div class="mx-row mx-gtot">'
        '<div class="c1"><span class="nm">TOTAL GLOBAL</span><span class="gsub">inbound + outbound + brain</span></div>'
        + cell(t_c + oc_c) + cell(t_l + oc_l) + cell(t_m + oc_m) + cell(t_s + oc_s, cls="hi") + cell(g_opp_all)
        + f'<div class="mx-cell cv"><span class="v tnum">{pvf(t_o + oc_o, t_c + oc_c)}</span></div>'
        + '</div>')
    matrix_html = (
        '<div class="mxwrap"><div class="matrix">'
        '<div class="mx-head"><span>Canal · % s/total contactos</span><span>Contactos</span><span>Leads</span>'
        '<span>MQL</span><span>SQL</span><span>Oport. (negocio asoc.)</span><span>Contacto→Op.</span></div>'
        + sep_in + mx_rows + mx_total
        + sep_out + mx_rows_out + mx_total_out
        + sep_brain + mx_brain
        + g_total + '</div></div>')

    # ---------- 24H (sin Freemium: volumen = lead+MQL+SQL) ----------
    def nn(e): return e.get("lead", 0) + e.get("mql", 0) + e.get("sql", 0)
    ch24 = sorted(d["channels"], key=lambda x: -nn(x[1]))
    d24_total = sum(nn(e) for _, e in d["channels"])
    bmax = max((nn(e) for _, e in d["channels"]), default=0) or 1
    def sub24(e):
        parts = []
        if e.get("lead"): parts.append(f'{e["lead"]} lead')
        if e.get("mql"): parts.append(f'{e["mql"]} MQL')
        if e.get("sql"): parts.append(f'{e["sql"]} SQL')
        return f'<span class="sub">{" · ".join(parts)}</span>' if parts else ''
    b24 = "".join(
        f'<div class="brow big24{"" if nn(e) else " zero"}"><span class="bl">{e.get("icon","•")} {esc(lbl)}</span>'
        f'<div class="bt"><div class="bf" style="width:{round(nn(e)/bmax*100) if nn(e) else 0}%"></div></div>'
        f'<span class="bn tnum">{nn(e)}{sub24(e)}</span></div>'
        for lbl, e in ch24)

    # ---------- 5 · CALIDAD (4 bloques) + volumen de consultas ----------
    ql = ex["quality"]; qt = ql["total"] or 1
    pr = ex.get("pref", {"tel": 0, "mail": 0, "total": 0}); pr_t = pr["total"] or 1
    qcols = (
        f'<div class="qcol"><div class="qi">✉️</div><div class="qv tnum">{fmt(ql["corp"])}</div><div class="ql">Email corporativo</div><div class="qp">{pv(ql["corp"], qt)}</div></div>'
        f'<div class="qcol"><div class="qi">📞</div><div class="qv tnum">{fmt(ql["phone"])}</div><div class="ql">Con teléfono</div><div class="qp">{pv(ql["phone"], qt)}</div></div>'
        f'<div class="qcol"><div class="qi">🏢</div><div class="qv tnum">{fmt(ql["company"])}</div><div class="ql">Empresa identificada</div><div class="qp">{pv(ql["company"], qt)}</div></div>'
        f'<div class="qcol"><div class="qi">🗣️</div><div class="qv tnum">{fmt(pr["total"])}</div><div class="ql">Preferencia de contacto</div>'
        f'<div class="qp">{pv(pr["total"], qt)} lo indican</div>'
        f'<div class="qsplit">📞 {pr["tel"]} <small>({pv(pr["tel"], pr_t)})</small> · ✉️ {pr["mail"]} <small>({pv(pr["mail"], pr_t)})</small></div>'
        f'<div class="qnote">campo del formulario desde el 9 jul</div></div>')
    vq = ex.get("volq", {}); vq_t = sum(vq.values()) or 1
    VOLROWS = [("✅ ≥ 3.000 consultas/mes", vq.get("ge3000", 0), "ok"),
               ("🤷 «No lo sé»", vq.get("nose", 0), ""),
               ("⚠️ < 3.000 consultas/mes", vq.get("lt3000", 0), "bad"),
               ("❔ Sin dato declarado", vq.get("sindato", 0), "mut")]
    vqmax = max((n for _, n, _ in VOLROWS), default=0) or 1
    volq_html = "".join(
        f'<div class="brow"><span class="bl">{lbl}</span><div class="bt"><div class="bf {c}" style="width:{round(n/vqmax*100)}%"></div></div>'
        f'<span class="bn tnum">{fmt(n)}<br><small>{pv(n, vq_t)}</small></span></div>'
        for lbl, n, c in VOLROWS)

    # ---------- 6 · LEADS por origen (+ lead ads desplegable) ----------
    orig_rows = [(k, v) for k, v in d["origin"]["sorted"]]
    omax = max((v for _, v in orig_rows), default=0) or 1
    otot = d["origin"]["total"] or 1
    leadads = ex.get("leadads", [])
    la_tot = sum(v for _, v in leadads)
    leads_html = ""
    for k, v in orig_rows[:9]:
        if k == "Lead Ads (paid)" and leadads:
            inner = "".join(f'<span>{esc(n)} · <b style="color:var(--sky)">{c}</b></span>' for n, c in leadads)
            leads_html += (
                f'<details class="chdeals"><summary><span class="bl">{esc(k)} · paid media</span>'
                f'<div class="bt"><div class="bf" style="width:{round(v/omax*100)}%;background:linear-gradient(90deg,#155e7a,var(--sky))"></div></div>'
                f'<span class="bn tnum">{fmt(v)}<br><small>{pv(v, otot)}</small></span></summary>'
                f'<div class="dl">{inner}</div></details>')
        else:
            leads_html += (
                f'<div class="brow"><span class="bl">{esc(k)}</span><div class="bt"><div class="bf" style="width:{round(v/omax*100)}%"></div></div>'
                f'<span class="bn tnum">{fmt(v)}<br><small>{pv(v, otot)}</small></span></div>')

    # ---------- 7 · MQL contenido ----------
    CONTENT = d["origin"]["content_set"]
    content_rows = [(k, v) for k, v in d["origin"]["sorted"] if k in CONTENT]
    cmx = max((v for _, v in content_rows), default=0) or 1
    ctot = sum(v for _, v in content_rows) or 1
    content_html = "".join(
        f'<div class="brow"><span class="bl">{esc(k)}</span><div class="bt"><div class="bf" style="width:{round(v/cmx*100)}%"></div></div>'
        f'<span class="bn tnum">{v}<br><small>{pv(v, ctot)}</small></span></div>'
        for k, v in content_rows) or '<p class="sd">Sin datos de contenido.</p>'

    # ---------- 8 · SQL 2 columnas ----------
    pq = d["preq"]
    ag_base = pq.get("ag_sql", 0) or 1
    ag_contact = pq.get("ag_calls_unique", 0) + pq.get("ag_reuniones", 0)
    raz = pq.get("ag_razones", [])
    raz_tot = sum(n for _, n in raz) or 1
    raz_rows = "".join(
        f'<div class="mrow"><span class="ml">{esc(r)}</span><span class="mn">{n} <small>{pv(n, raz_tot)}</small></span></div>'
        for r, n in raz[:6]) or '<div class="mrow"><span class="ml">Sin razones registradas</span><span class="mn">—</span></div>'

    # ---------- 9 · MOTIVOS DESCARTE ----------
    desc = d["descarte"]
    desc_tot = sum(n for _, n in desc) or 1
    dmax = max((n for _, n in desc), default=0) or 1
    desc_html = "".join(
        f'<div class="brow"><span class="bl">{esc(r)}</span><div class="bt"><div class="bf" style="width:{round(n/dmax*100)}%;background:linear-gradient(90deg,var(--bad),#ffa7b6)"></div></div>'
        f'<span class="bn tnum">{n}<br><small>{pv(n, desc_tot)}</small></span></div>'
        for r, n in desc[:8])
    desc_interp = ""
    if desc:
        r0, n0 = desc[0]
        desc_interp = f'<div class="note">El <b>{pv(n0, desc_tot)}</b> de los descartes con motivo son por «{esc(r0)}». Total con razón registrada: <b>{desc_tot}</b>.</div>'

    # ---------- 8 · SQL en 3 niveles ----------
    sd_ = d["sql_disp"]
    sql_total = sd_.get("total", 0)
    # NIVEL 1 · Seguimiento de SQLs de paid media (informe de Agustín · campañas de pago)
    pt3 = d.get("paid_tracker")
    def _pn(v):
        try: return int(v)
        except (TypeError, ValueError): return 0
    if pt3 and pt3.get("stats"):
        s3 = pt3["stats"]
        n1 = _pn(s3.get("total"))
        pt3_tot = n1 or 1
        pt3_defs = [("🟢", "Cualificados", s3.get("qualified")),
                    ("🔵", "En proceso", s3.get("open")),
                    ("⚪", "Sin contactar", s3.get("uncontacted")),
                    ("✅", "Ganados", s3.get("won")),
                    ("🔴", "Perdidos", s3.get("lost"))]
        # Ordenar de mayor a menor volumen
        pt3_defs = sorted(pt3_defs, key=lambda x: -_pn(x[2]))
        pt3_rows = "".join(
            f'<div class="ptr"><span class="ptr-l">{ic} {lab}</span>'
            f'<span class="ptr-n tnum">{_pn(v)} <small>{pv(_pn(v), pt3_tot)}</small></span></div>'
            for ic, lab, v in pt3_defs if _pn(v))
        afc = s3.get("avg_first_contact_days")
        afc_html = ""
        if afc is not None:
            try: afc_html = f'<div class="paid3-foot">⏱️ Primer contacto medio: <b>{round(float(afc),1)} días</b></div>'
            except (TypeError, ValueError): afc_html = ""
        agustin_html = (
            f'<div class="paid3"><div class="paid3-h">Estado de los SQLs de paid media · en vivo '
            f'<span>(informe de Agustín · campañas de pago · desde 1 jul)</span></div>'
            f'<div class="ptr-box">{pt3_rows}</div>{afc_html}</div>')
    else:
        n1 = pq.get("ag_sql", 0)
        agustin_html = ('<div class="paid3 paid3-empty">Pendiente de conectar el informe de Agustín '
                        '(seguimiento de SQLs de paid media). Al conectarlo, se muestra en vivo el estado: '
                        'cualificados, en proceso, sin contactar, ganados y perdidos.</div>')
    # Flujo de precualificación de Agustín (SQL → agendados → oportunidad)
    agustin_flow_html = (
        '<div class="flow" style="margin-top:14px">'
        f'<div class="fstep"><b>{pq.get("ag_sql",0)}</b><span>SQL<br>precualificados</span></div>'
        f'<div class="farr"><span class="fp">{pv(ag_contact, ag_base)}</span>→</div>'
        f'<div class="fstep"><b>{ag_contact}</b><span>agendados /<br>llamados</span></div>'
        f'<div class="farr"><span class="fp">{pv(pq.get("ag_opp",0), ag_base)}</span>→</div>'
        f'<div class="fstep ok"><b>🎯 {pq.get("ag_opp",0)}</b><span>oportunidad</span></div>'
        '</div>')
    # NIVEL 2 · Descartados / descualificados (desc_tot, desc_html ya calculados arriba)
    n2 = desc_tot
    # NIVEL 3 · Los que quedan (sin identificar) · a precualificar por mail
    n3 = max(0, sql_total - n1 - n2)
    email_flow_html = (
        '<div class="emailbox">'
        f'<div class="eb tnum">{fmt(n3)}</div>'
        '<div style="font-size:12px;color:var(--ink2);margin-top:6px">SQL sin fuente identificada · pasan al circuito de mail</div>'
        '</div>'
        '<ul class="elist" style="margin-top:14px">'
        '<li>Email automático que pregunta/confirma el volumen de consultas</li>'
        '<li>Los de <b>≥3.000</b> consultas → se cualifican y pasan a Agustín</li>'
        '<li>Los de <b>&lt;3.000</b> → lista HubSpot «Descalificación SQL» (reactivables si crecen)</li>'
        '<li>Razón de descarte registrada para el evolutivo</li>'
        '</ul>')

    # ---------- 10 · OPORTUNIDADES abiertas (pipeline real, sin clientes) ----------
    dbc = ex.get("deals_by_chan", {})   # {canal: [(nombre, etapa), ...]} solo abiertas inbound
    opp_ch = sorted(((lbl, items) for lbl, items in dbc.items()), key=lambda x: -len(x[1]))
    opp_ch_tot = sum(len(items) for _, items in opp_ch) or 1
    omx = max((len(items) for _, items in opp_ch), default=0) or 1
    def _stgnice(sl):
        s = (sl or "").lower()
        # El pipeline de ventas no tiene una etapa "Demo" separada: la demo/reunión ocurre
        # dentro de «Needs Validation & Solution Alignment» (id presentationscheduled).
        if "discov" in s: return "Discovery"
        if "needs validation" in s or "solution align" in s or "demo" in s or "reuni" in s:
            return "Demo / Validación"
        if "best" in s: return "Best Case"
        if "close won" in s or "ganad" in s: return "Cierre ganado"
        return sl or ""
    def _stgchip(sl):
        s = (sl or "").lower()
        c = "discov" if "discov" in s else ("demo" if ("needs validation" in s or "solution align" in s or "demo" in s or "reuni" in s) else ("best" if "best" in s else ""))
        nice = _stgnice(sl)
        return f'<span class="chip {c}">{esc(nice)}</span>' if sl else ""
    opp_ch_html = ""
    for lbl, items in opp_ch:
        inner = "".join(f'<span>{esc(nm)} {_stgchip(sl)}</span>' for nm, sl in items) or '<span>Sin negocios listados</span>'
        n = len(items)
        opp_ch_html += (
            f'<details class="chdeals"><summary><span class="bl">{esc(lbl)}</span>'
            f'<div class="bt"><div class="bf" style="width:{round(n/omx*100)}%;background:linear-gradient(90deg,#155e7a,var(--sky))"></div></div>'
            f'<span class="bn tnum">{n}<br><small>{pv(n, opp_ch_tot)}</small></span></summary>'
            f'<div class="dl">{inner}</div></details>')
    opp_ch_html = opp_ch_html or '<p class="sd">Sin oportunidades abiertas por canal.</p>'
    pipe_legend = "".join(
        f'<span><b>{c}</b> {_stgchip(nm)}</span>' for nm, c in ex.get("stage_dist", []))
    pipe_val = ex.get("pipeline_value", 0)
    pipe_cnt = ex.get("pipeline_count", opp_ch_tot)
    pipe_known = ex.get("pipeline_value_known", 0)

    # ---------- RENDIMIENTO POR CANAL (mismo dato que la matriz · suma = total contactos) ----------
    dbc_t = ex.get("deals_by_chan", {})
    cf = ex["chan_matrix"]
    def _row(lbl, e):
        opp = len(dbc_t.get(lbl, []))
        return (f'<tr><td>{esc(lbl)}</td><td class="tnum">{fmt(e["contactos"])}</td><td class="tnum">{fmt(e["leads"])}</td>'
                f'<td class="tnum">{fmt(e["mql"])}</td><td class="tnum hi">{fmt(e["sql"])}</td><td class="tnum">{opp}</td>'
                f'<td class="tnum cv">{pvf(opp, e["contactos"])}</td></tr>')
    rows_ch = "".join(_row(lbl, e) for lbl, e in cf)
    # fila TOTAL
    tt = {k: sum(e.get(k, 0) for _, e in cf) for k in ("contactos", "leads", "mql", "sql")}
    tt_opp = sum(len(v) for v in dbc_t.values())
    rows_ch += (f'<tr style="border-top:2px solid var(--line2);font-weight:800">'
                f'<td>TOTAL</td><td class="tnum">{fmt(tt["contactos"])}</td><td class="tnum">{fmt(tt["leads"])}</td>'
                f'<td class="tnum">{fmt(tt["mql"])}</td><td class="tnum hi">{fmt(tt["sql"])}</td><td class="tnum">{tt_opp}</td>'
                f'<td class="tnum cv">{pvf(tt_opp, tt["contactos"])}</td></tr>')

    # ---------- INSIGHTS ----------
    insights = []
    if d["chan_funnel"]:
        tot_sql = sum(e["sql"] for _, e in d["chan_funnel"]) or 1
        lbl0, e0 = d["chan_funnel"][0]
        if e0["sql"] > 0:
            insights.append(("", f'<b>{esc(lbl0)}</b> es el canal que más SQL genera: {e0["sql"]} ({pv(e0["sql"], tot_sql)} del total).'))
        conv_ch = [(lbl, e) for lbl, e in d["chan_funnel"] if e["contactos"] >= 20]
        if conv_ch:
            lb, e = max(conv_ch, key=lambda x: x[1]["sql"] / x[1]["contactos"])
            insights.append(("", f'<b>{esc(lb)}</b> tiene la mejor tasa contacto→SQL: {pv(e["sql"], e["contactos"])}.'))
    if desc:
        r0, n0 = desc[0]
        insights.append(("warn", f'El motivo principal de descarte es «{esc(r0)}» ({pv(n0, desc_tot)} de los descartes).'))
    if content_rows:
        insights.append(("", f'El contenido que más leads de consideración genera es <b>{esc(content_rows[0][0])}</b> ({content_rows[0][1]}).'))
    grow = max(tr.items(), key=lambda x: x[1].get("delta", 0))
    if grow[1].get("delta", 0) > 0:
        insights.append(("", f'Tendencia al alza en <b>{grow[0]}</b>: +{grow[1]["delta"]} en los últimos 7 días vs los 7 previos.'))
    drop = min(tr.items(), key=lambda x: x[1].get("delta", 0))
    if drop[1].get("delta", 0) < 0:
        insights.append(("bad", f'Atención: <b>{drop[0]}</b> baja {drop[1]["delta"]} en los últimos 7 días respecto a los 7 previos.'))
    insights = insights[:5]
    ins_html = "".join(f'<div class="i {c}"><span class="dot"></span><p>{txt}</p></div>' for c, txt in insights) \
        or '<p class="sd">Sin señales suficientes para generar insights hoy.</p>'

    # ---------- ACCIONES ----------
    acts = []
    if desc:
        r0 = desc[0][0].lower()
        if "volumen" in r0 or "icp" in r0 or "target" in r0 or "pequeñ" in r0:
            acts.append(("Afinar el ICP en captación", "El principal descarte es de perfil/volumen fuera de objetivo: revisar segmentación de campañas y filtros del formulario."))
        elif "responde" in r0:
            acts.append(("Acelerar el primer contacto", "Muchos descartes por falta de respuesta: reducir el tiempo de reacción sobre nuevos SQL."))
        else:
            acts.append(("Revisar la cualificación", f'El motivo de descarte dominante es «{esc(desc[0][0])}»: revisar el proceso de cualificación.'))
    if d["sql_disp"].get("pendiente", 0) > 0:
        acts.append(("Reducir SQL pendientes", f'Hay {d["sql_disp"]["pendiente"]} SQL sin gestionar todavía: priorizar su seguimiento.'))
    if d["chan_funnel"]:
        conv_ch = [(lbl, e) for lbl, e in d["chan_funnel"] if e["contactos"] >= 20]
        if conv_ch:
            best = max(conv_ch, key=lambda x: x[1]["sql"] / x[1]["contactos"])
            acts.append(("Doblar en el canal más eficiente", f'{esc(best[0])} convierte mejor a SQL: valorar más inversión/foco ahí.'))
    acts.append(("Conectar el gasto de Paid", "Falta el gasto de Google/Meta/LinkedIn para leer CPL y coste por oportunidad reales."))
    acts_html = "".join(f'<div class="act"><b>{b}</b>{t}</div>' for b, t in acts[:5])

    body = f"""
<div class="wrap">
<header class="xhead">
  <div class="xtop">
    <span class="xbrand"><b>gurus</b><i>•</i><b>up</b></span>
    <details class="dictx"><summary><span class="chev">▶</span>📖 Diccionario</summary>
      <div class="dwrap">
        <div class="dhdr">Etapas del ciclo de vida del contacto (en orden)</div>
        <div class="d"><b>Lead</b><span>Etapa del ciclo de vida: ha entrado con algo de interés, pero aún no sabemos si nos encaja.</span></div>
        <div class="d"><b>MQL</b><span>Etapa del ciclo de vida: el contacto ha consumido contenido de valor (ebook, webinar…). Interés medio.</span></div>
        <div class="d"><b>SQL</b><span>Etapa del ciclo de vida: tiene una necesidad real y pide demo/consultoría. Listo para ventas.</span></div>
        <div class="d"><b>Oportunidad</b><span>Etapa del ciclo de vida de un contacto que ya tiene un <b>negocio (deal) asociado</b>. Varios contactos pueden compartir el mismo negocio, pero es un único deal.</span></div>
        <div class="d"><b>Cliente</b><span>Etapa del ciclo de vida: contacto con negocio asociado que <b>ya ha convertido y compra</b>. Varios contactos pueden pertenecer al mismo negocio de cliente.</span></div>
        <div class="d"><b>Otros</b><span>Etapa del ciclo de vida fuera del proceso comercial: correos <b>@gurusup.com</b>, proveedores, gente externa o quien pide trabajar con nosotros. Incluye también algunas pruebas/test (para no crear más etapas).</span></div>
        <div class="dhdr">Otros conceptos</div>
        <div class="d"><b>Churn</b><span>Cliente que se da de baja en el periodo.</span></div>
        <div class="d"><b>Pipeline</b><span>Oportunidades abiertas y su recorrido hasta cliente.</span></div>
        <div class="d"><b>Conversión</b><span>% de contactos que pasan de una etapa a la siguiente.</span></div>
      </div>
    </details>
  </div>
  <h1>Dashboard <span>ejecutivo</span> global</h1>
  <p class="hero-1l">Qué entra, cómo evoluciona y dónde se pierde negocio. Datos en vivo desde HubSpot; embudo acumulado desde el 1 de enero de 2026.</p>
  <div class="upd">Última actualización: <b>{esc(d["generado"])}</b> (hora España) · se refresca automáticamente</div>
</header>

<section style="padding-top:30px;margin-top:16px">
  <div class="q">01 · ¿Cuánto negocio está entrando? · GLOBAL</div>
  <h2 class="sh">Executive summary</h2>
  <div class="sd wide"><b>Volumen total del CRM y sus etapas desde el 1 de enero</b>, incluye:
    <span class="src-chip in">🟢 Inbound</span><span class="src-chip out">🟠 Outbound</span><span class="src-chip cx">💬 Atención al cliente (CX)</span><span class="src-chip br">🧠 Brain</span>.
    El número grande es el total de contactos; debajo, <b>inb</b> (inbound) y <b>out</b> (outbound). En Oportunidades el número grande es <b>volumen de contactos</b> y el nº de <b>empresas / negocios</b> va debajo; en Clientes se muestran las <b>cuentas activas</b> del pipeline «Clientes».</div>
  <div class="kg">{kpi_html}</div>
  <div style="height:26px"></div>
  <div class="rb-title">📊 Tasas de conversión del embudo <span>· todas sobre contactos, comparable etapa a etapa · ver nota *</span></div>
  <div class="ratesbanner">
    <div class="rb-grid">{rate_html}</div>
  </div>
  <div class="fnote">* <b>¿Qué contactos no pasan a Lead?</b> Se excluyen del embudo la etapa «otros»: <b>{d.get("excl_internal",0)} internos (@gurusup)</b> y <b>{d.get("excl_tests",0)} pruebas/test</b>. Además, hay contactos que se crearon y luego se <b>eliminaron</b> (pruebas): tienen fecha de creación pero ya no existen en el CRM, por eso no se contabilizan. Los <b>Freemium</b> (altas por la app) también quedan fuera del embudo comercial. El churn se mostrará en cuanto se conecte su fuente.</div>
</section>

<section>
  <div class="q">02 · ¿Dónde está cada contacto?</div>
  <h2 class="sh">Embudos por vía <span class="tot">· Inbound · Outbound · Brain</span></h2>
  <div class="sd">Desglose del embudo por vía. Cada columna es su volumen de <b>contactos</b> por etapa y el % <b>sobre su total de contactos</b>. El <b>pipeline de ventas es compartido</b>: inbound y outbound lo trabajan de forma conjunta.</div>
  <div class="io3">
    <div class="iocol in">
      <div class="io-h">🟢 Inbound · <b>Agustín</b> <span class="io-tot tnum">{fmt(total_nf)}</span></div>
      <div class="mf">{inb_fn}</div>
      <div class="io-val">💰 Valor estimado pipeline<span>{("€"+fmt(round(ex.get("inb_value",0)))) if ex.get("inb_value") else "— (importes sin cargar)"}</span></div>
    </div>
    <div class="iocol out">
      <div class="io-h">🟠 Outbound · <b>Juanma</b> <span class="io-tot tnum">{fmt(ob["contactos"])}</span></div>
      <div class="mf">{out_fn}</div>
      <div class="io-val">💰 Valor estimado pipeline<span>{("€"+fmt(round(ex.get("out_value",0)))) if ex.get("out_value") else "— (importes sin cargar)"}</span></div>
    </div>
    <div class="iocol brain">
      <div class="io-h">🧠 Brain · <b>Alex</b> <span class="io-tot tnum">{fmt(ex.get("brain_open", 0))}</span></div>
      <div class="mf">
        <div class="mf-row"><div class="mf-l"><b class="tnum">{fmt(ex.get("brain_open", 0))}</b> Oportunidades abiertas</div><div class="mf-bar"><div class="mf-fill" style="width:100%"></div></div><span class="mf-c"></span></div>
      </div>
      <div class="pend" style="margin-top:12px">⏳ Embudo completo de contactos <b>Brain / CX</b> (lead→cliente) pendiente de conectar.</div>
      <div class="io-val">💰 Valor estimado pipeline<span>{("€"+fmt(round(ex.get("brain_value",0)))) if ex.get("brain_value") else "— (importes sin cargar)"}</span></div>
    </div>
  </div>
</section>

<section>
  <div class="q">03 · ¿Estamos creciendo?</div>
  <h2 class="sh">Evolución acumulada</h2>
  <div class="sd">Crecimiento día a día <b style="color:var(--brand)">desde el 1 de enero</b>. Sobre cada línea, el total acumulado al cierre de cada mes y, más pequeño, lo generado ese mes.</div>
  <div class="cg">{charts_html}</div>
  <div class="note">⚠️ <b>Por qué el total del gráfico no coincide con el KPI:</b> estos evolutivos cuentan contactos que <b>alcanzaron</b> cada etapa por su fecha de creación (<b>generación acumulada</b>), no el estado actual — si un contacto avanzó de etapa, sigue contando aquí. El KPI de arriba muestra el <b>estado a día de hoy</b>. Por eso difieren.
  <br><br>🔎 <b>Dos picos revisados:</b> el de <b>MQL en junio</b> viene sobre todo de fuente <b>OFFLINE / importación</b> (etiqueta «Otros»), no de un canal inbound real. El de <b>Oportunidades en marzo (+50)</b> son contactos <b>marcados como «oportunidad» sin negocio (deal) asociado</b> — importación/automatismo, no oportunidades reales del pipeline (conviene limpiarlos).</div>
</section>

<section>
  <div class="q">04 · ¿Qué canal genera negocio real?</div>
  <h2 class="sh">Rendimiento por canal <span class="tot">· global</span></h2>
  <div class="sd">Cómo rinde cada canal del contacto al negocio (acumulado desde el 1 de enero, sin Freemium), separado en <b style="color:var(--brand)">🟢 Inbound</b>, <b style="color:var(--warn)">🟠 Outbound</b> y <b style="color:var(--violet)">🧠 Brain</b>, con su total y el <b>TOTAL GLOBAL</b> al final. En Oportunidad <b>solo los que tienen negocio (deal) asociado</b> — así el total de esta columna <b>cuadra con el KPI de Oportunidades reales</b> de arriba. Última columna: <b>conversión contacto → oportunidad</b>.</div>
  {matrix_html}
</section>

<div class="divbanner">
  <div class="db-l">🔎</div>
  <div><div class="db-t">Estado y desglose de contactos · <span>Inbound</span></div>
  <div class="db-s">A partir de aquí, el detalle del embudo de inbound marketing: calidad del dato, origen, contenido, SQL, pipeline y cierre.</div></div>
</div>

<section>
  <div class="q">05 · ¿Qué calidad tiene el dato?</div>
  <h2 class="sh">Calidad de los nuevos contactos</h2>
  <div class="sd">Sobre el total de contactos desde el 1 de enero: completitud del dato (email corporativo, teléfono, empresa) y preferencia de contacto declarada.</div>
  <div class="q3">{qcols}</div>
</section>

<section>
  <div class="q">06 · ¿Qué pasa con los contactos en etapa lead?</div>
  <h2 class="sh">Estado de los contactos · etapa lead <span class="tot">· {fmt(d["origin"]["total"])}</span></h2>
  <div class="sd">Por qué origen / contenido han entrado (blog, calculadora, webinar, formulario, app…), con % sobre el total. «Lead Ads (paid)» es desplegable por red.</div>
  <div class="bars">{leads_html}</div>
  <div class="strat">
    <div class="strat-i">🌱→🎯</div>
    <div><b>Qué hacemos con leads y MQL:</b> los <b>nutrimos con contenido de GuruSup</b> (nurturing) y un <b>lead score</b> que sube con cada acción, hasta que maduran a SQL. Si un lead <b>encaja con el perfil target</b> —aunque aún no llegue a 3.000 consultas/mes— saltamos una <b>alerta a ventas</b> para contactarle con la necesidad detectada según el <b>contenido que ha consumido</b>.</div>
  </div>
</section>

<section>
  <div class="q">07 · ¿Qué consumen los MQL?</div>
  <h2 class="sh">Estado de los MQL <span class="tot">· {fmt(ctot)}</span> · contenido consumido</h2>
  <div class="sd">Qué activos de contenido consumen los leads de consideración (MQL de facto) antes de pasar a SQL.</div>
  <div class="bars">{content_html}</div>
</section>

<section>
  <div class="q">08 · ¿Qué ocurre con los SQL?</div>
  <h2 class="sh">Estado de los SQL <span class="tot">· {fmt(d["sql_disp"]["total"])}</span></h2>
  <div class="sd wide">De los <b>{fmt(sql_total)} SQL</b>, cada uno cae en uno de <b>tres estados</b>. <i>Pulsa cada columna para desplegar el detalle.</i></div>

  <div class="sqlvl3">
    <details class="lvl">
      <summary class="lvl-sum">
        <span class="lvl-badge b1">①</span>
        <span class="lvl-tit">Tratados por Agustín <small>· seguimiento de SQLs de paid media</small></span>
        <span class="lvl-n">{fmt(n1)}</span>
        <span class="chev">▶</span>
      </summary>
      <div class="lvl-body">
        <div class="ph">SQLs de <b>paid media</b> (campañas de pago) que gestiona Agustín (su informe en vivo). Así están repartidos:</div>
        {agustin_html}
      </div>
    </details>

    <details class="lvl lvl-bad">
      <summary class="lvl-sum">
        <span class="lvl-badge b2">②</span>
        <span class="lvl-tit">Descartados <small>· descualificados + razón</small></span>
        <span class="lvl-n">{fmt(n2)}</span>
        <span class="chev">▶</span>
      </summary>
      <div class="lvl-body">
        <div class="ph">SQL ya <b>descartados / descualificados</b>, con el motivo registrado:</div>
        <div class="bars">{desc_html}</div>
        {desc_interp}
      </div>
    </details>

    <details class="lvl lvl3">
      <summary class="lvl-sum">
        <span class="lvl-badge b3">③</span>
        <span class="lvl-tit">Los que quedan <small>· sin identificar → a mail</small></span>
        <span class="lvl-n">{fmt(n3)}</span>
        <span class="chev">▶</span>
      </summary>
      <div class="lvl-body">
        <div class="ph"><b>Flujo automatizado desde el 9 jul</b> (para quitar fricción tras decidir que solo cualifican ≥3.000 consultas): quien entra por el <b>formulario de contacto web</b> con <b>≥3.000</b> → email a <b>Agustín</b>; con <b>&lt;3.000</b> → email automático de descarte.</div>
        <div class="lvl-subh">≥3.000 consultas · pasan a Agustín</div>
        {agustin_flow_html}
        <div class="sd" style="margin-top:8px;font-size:12px">Han entrado <b>{pq.get("ag_sql",0)}</b> por esta vía; <b>{pq.get("ag_descartados",0)}</b> se descartaron (no pasaron a ventas) y <b>{pq.get("ag_opp",0)}</b> se convirtieron en oportunidad.</div>
        <details class="razd" style="margin-top:14px">
          <summary><span class="chev">▶</span> ✉️ &lt;3.000 consultas · circuito de mail de descarte</summary>
          <div class="razbox" style="background:rgba(34,211,238,.05);border-color:rgba(34,211,238,.22)">
            {email_flow_html}
          </div>
        </details>
      </div>
    </details>
  </div>
</section>

<section>
  <div class="q">09 · ¿Cómo va el pipeline?</div>
  <h2 class="sh">Oportunidades <span class="tot">· {fmt(pipe_cnt)}</span> abiertas de inbound</h2>
  <div class="sd">Solo <b>oportunidades abiertas</b> del pipeline de ventas que vienen de campañas inbound (se excluyen clientes/ganados). <b>Pulsa un canal</b> para ver los negocios y su etapa. El pipeline tiene <b>3 etapas</b>: <b>Discovery → Demo/Validación → Best Case</b> (no hay una etapa «Demo» aparte: la <b>demo/reunión ocurre dentro de «Needs Validation & Solution Alignment»</b>).</div>
  <div class="cards" style="margin-bottom:18px">
    <div class="stat ok"><div class="sv tnum">{("€"+fmt(round(pipe_val))) if pipe_val else "—"}</div><div class="sl">Valor estimado del pipeline abierto{("" if pipe_val else " · importes no cargados en los deals")}</div></div>
    <div class="stat"><div class="sv tnum">{fmt(pipe_cnt)}</div><div class="sl">Negocios abiertos ({pipe_known} con importe)</div></div>
  </div>
  <div class="pipe-legend">Etapas: {pipe_legend or '<span>Sin etapas registradas</span>'}</div>
  {opp_ch_html}
</section>

<section>
  <div class="q">10 · ¿Cerramos?</div>
  <h2 class="sh">Clientes <span class="tot">· {fmt(ex.get("cli_split",{}).get("contactos",0))} contactos · {fmt(ex.get("cli_split",{}).get("total",0))} empresas</span></h2>
  <div class="sd"><b>Cartera real</b> del pipeline «Clientes» (excluye Churn/Dormidos y las altas freemium de la app). Cifra grande = <b>contactos</b>; empresas = cuentas. Fuente real del negocio (por <code>hs_analytics_source</code>): el total es la <b>suma de inbound + outbound</b>.</div>
  <div class="cards">
    <div class="stat"><div class="sv tnum">{fmt(ex.get("cli_split",{}).get("total",0))}</div><div class="sl">Cuentas de cliente activas · {fmt(ex.get("cli_split",{}).get("contactos",0))} contactos</div></div>
    <div class="stat ok"><div class="sv tnum">{fmt(ex.get("cli_split",{}).get("inbound",0))}</div><div class="sl">🟢 Inbound · orgánico / paid / social</div></div>
    <div class="stat warn"><div class="sv tnum">{fmt(ex.get("cli_split",{}).get("outbound",0))}</div><div class="sl">🟠 Outbound / otros · offline · importación · integración · tráfico directo</div></div>
  </div>
  <div class="note">Dato real del pipeline «Clientes» ({fmt(ex.get("cli_split",{}).get("total",0))} cuentas). La mayoría entran por <b>outbound / offline / importación / integración de la app</b>; muy pocas por canales de <b>inbound</b> de marketing. Se cuenta por <b>cuenta/empresa</b> (los contactos con ciclo de vida «cliente» incluyen altas freemium de la app y no reflejan la cartera real).</div>
</section>

<section>
  <div class="q">11 · ¿Perdemos clientes?</div>
  <h2 class="sh">Churn <span class="tot">· {fmt(ex.get("churn",{}).get("contactos",0))} contactos · {fmt(ex.get("churn",{}).get("empresas",0))} empresas</span></h2>
  <div class="sd"><b>Clientes que lo fueron desde el 1 de enero y hoy ya no lo son</b>: cuentas del pipeline «Clientes» que han pasado a etapa <b>Churned</b> o <b>Dormidos / Inactivos</b>. Cifra grande = contactos; empresas = cuentas.</div>
  <div class="cards">
    <div class="stat bad"><div class="sv tnum">{fmt(ex.get("churn",{}).get("contactos",0))}</div><div class="sl">🔻 Churn · contactos<br><span style="color:var(--mut)">{fmt(ex.get("churn",{}).get("empresas",0))} empresas · Churned / Dormidos</span></div></div>
    <div class="stat"><div class="sv tnum">{_churn_pct}</div><div class="sl">Tasa de churn<br><span style="color:var(--mut)">churn / (churn + clientes activos)</span></div></div>
  </div>
  <div class="note">Churn real medido por <b>cuenta de cliente</b> en el pipeline «Clientes» (etapas Churned + Dormidos/Inactivos). La <b>tasa de churn</b> = cuentas perdidas / (perdidas + activas). La etapa «Churn» del <i>ciclo de vida del contacto</i> casi no se usa en el CRM (solo la tienen contactos sueltos), por eso el churn fiable es el de cuentas del pipeline.</div>
</section>

<footer>GuruSup · Dashboard ejecutivo · datos HubSpot en vivo · {esc(d["generado"])} (hora España) · documento confidencial</footer>
</div>
"""
    return ('<!DOCTYPE html><html lang="es"><head><meta charset="UTF-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1.0">'
            '<title>GuruSup · Dashboard Ejecutivo</title><style>' + EXEC_CSS + '</style></head><body>'
            + body + '</body></html>')


TEMPLATE = r"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<style>
:root {{
  --guru-900:#08120e; --guru-500:#57e08a; --guru-400:#1f9d5f; --guru-300:#c7f3d9;
  --surface:#0f1e18; --card:#132a20; --border:#20402f;
  --green:#34d399; --amber:#f5b544; --red:#f2647a; --blue:#3b82f6; --orange:#f97316;
  --teal:#5bc8f2; --text:#eafff4; --text-2:#b3d2c4; --muted:#6f8c7e;
  --salmon:#ff6b5b; --salmon-dk:#e0574a; --green-bright:#79f2a6; --green-deep:#0e5136;
}}
*,*::before,*::after {{ box-sizing:border-box; margin:0; padding:0; }}
html {{ font-size:15px; }}
body {{ background:var(--guru-900); color:var(--text); font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','Inter',sans-serif; line-height:1.5; min-height:100vh; }}
.header {{ position:sticky; top:0; z-index:100; background:rgba(9,20,15,.96); backdrop-filter:blur(16px); border-bottom:1px solid var(--border); padding:0 24px; }}
.header-inner {{ display:flex; align-items:center; gap:16px; padding:14px 0 12px; flex-wrap:wrap; }}
.logo-box {{ width:40px; height:40px; background:linear-gradient(135deg,var(--guru-500),var(--guru-400)); border-radius:10px; display:flex; align-items:center; justify-content:center; font-weight:800; font-size:15px; color:#fff; flex-shrink:0; box-shadow:0 0 16px rgba(87,224,138,.4); }}
.header-title {{ flex:1; min-width:180px; }}
.header-title h1 {{ font-size:16px; font-weight:700; }}
.header-title p {{ font-size:12px; color:var(--muted); }}
.live-badge {{ background:rgba(16,185,129,.12); border:1px solid rgba(16,185,129,.3); color:var(--green); font-size:11px; font-weight:600; padding:4px 10px; border-radius:20px; display:flex; align-items:center; gap:5px; white-space:nowrap; }}
.live-dot {{ width:6px; height:6px; border-radius:50%; background:var(--green); animation:pulse 2s infinite; }}
@keyframes pulse {{ 0%,100%{{opacity:1}} 50%{{opacity:.3}} }}
.sync-bar {{ font-size:11px; color:var(--muted); padding:5px 24px 6px; border-top:1px solid rgba(20,60,45,.6); background:rgba(9,20,15,.7); }}
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
.gl-card {{ display:flex; gap:11px; align-items:flex-start; background:rgba(255,255,255,.03); border:1px solid var(--border); border-radius:9px; padding:11px 13px; }}
.gl-card.gl-wide {{ grid-column:1 / -1; border-color:rgba(87,224,138,.3); background:rgba(87,224,138,.05); }}
.gl-card .gl-e {{ font-size:20px; flex:0 0 auto; line-height:1.2; }}
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
  margin:40px 0 20px; padding:18px 22px; border-radius:14px;
  background:linear-gradient(100deg, #1f9d5f, #57e08a);
  border:1px solid rgba(87,224,138,.5); box-shadow:0 6px 22px rgba(87,224,138,.25); }}
.evo-l {{ display:flex; align-items:center; gap:14px; }}
.evo-ico {{ font-size:26px; }}
.evo-t {{ font-size:16px; font-weight:800; color:#04160d; letter-spacing:.01em; }}
.evo-s {{ font-size:12px; color:rgba(4,22,13,.82); margin-top:2px; }}
.evo-badge {{ font-size:11px; font-weight:800; letter-spacing:.08em; padding:6px 12px; border-radius:20px;
  background:rgba(4,22,13,.18); color:#04160d; white-space:nowrap; border:1px solid rgba(4,22,13,.28); }}
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
.flow-branch.nobrd {{ margin-top:0; border-top:none; padding-top:0; }}
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
.fb-demo {{ margin-top:14px; background:rgba(87,224,138,.07); border:1px solid rgba(87,224,138,.28); border-radius:9px; padding:11px 13px; font-size:12px; line-height:1.5; color:var(--text-2); }}
.fb-conv {{ display:flex; gap:10px; margin-top:12px; flex-wrap:wrap; }}
.fbc {{ flex:1; min-width:200px; border-radius:9px; padding:12px 14px; font-size:13px; }}
.fbc.ok {{ background:rgba(16,185,129,.1); border:1px solid rgba(16,185,129,.35); color:#a7f3d0; }}
.fbc.bad {{ background:rgba(239,68,68,.1); border:1px solid rgba(239,68,68,.35); color:#fecaca; }}
.fs-star {{ color:#fff; font-weight:800; }}
.flow-freenote {{ margin-top:6px; background:rgba(255,255,255,.07); border:1px solid rgba(255,255,255,.18); border-radius:8px; padding:10px 13px; font-size:12px; color:#fff; line-height:1.5; font-weight:400; }}
.fb-razbox {{ margin-top:14px; border:1px solid rgba(239,68,68,.28); background:rgba(239,68,68,.05); border-radius:10px; padding:13px 14px; }}
.fb-raz-head {{ font-size:13px; color:var(--text); margin-bottom:10px; line-height:1.4; }}
.fbr-row {{ display:flex; align-items:center; gap:10px; margin-bottom:7px; }}
.fbr-l {{ flex:0 0 40%; font-size:12px; color:var(--text-2); line-height:1.3; }}
.fbr-barwrap {{ flex:1; background:rgba(255,255,255,.05); border-radius:5px; height:12px; overflow:hidden; }}
.fbr-bar {{ height:12px; border-radius:5px; background:linear-gradient(90deg,#e0574a,#ff6b5b); }}
.fbr-n {{ flex:0 0 62px; text-align:right; font-size:13px; font-weight:800; color:var(--guru-300); }}
.fbr-p {{ font-size:11px; color:var(--muted); font-weight:600; }}
.fbr-foot {{ font-size:10px; color:var(--muted); margin-top:8px; line-height:1.4; }}
.fb-mid {{ display:flex; align-items:stretch; gap:8px; margin-top:14px; flex-wrap:wrap; }}
.fb-mid-step {{ flex:1; min-width:150px; background:rgba(255,255,255,.04); border:1px solid var(--border); border-radius:10px; padding:12px 13px; }}
.fb-mid-step b {{ display:block; font-size:26px; font-weight:800; color:var(--text); line-height:1; }}
.fb-mid-step span {{ font-size:11px; color:var(--muted); line-height:1.35; display:block; margin-top:5px; }}
.fb-mid-step.fb-mid-ok {{ border-color:rgba(16,185,129,.4); background:rgba(16,185,129,.09); }}
.fb-mid-step.fb-mid-ok b {{ color:#6ee7b7; }}
.fb-mid-step.fb-mid-mid {{ border-color:rgba(245,158,11,.4); background:rgba(245,158,11,.08); }}
.fb-mid-step.fb-mid-mid b {{ color:#fcd34d; }}
@media(max-width:640px){{ .fb-mid {{ flex-direction:column; }} }}
.fb-reconc {{ display:block; font-size:11px; font-weight:600; color:var(--muted); margin-top:4px; }}
.fb-reconc b {{ color:var(--text); }}
.sqlcols {{ display:grid; grid-template-columns:1fr 1fr; gap:14px; margin-top:16px; }}
@media(max-width:760px){{ .sqlcols {{ grid-template-columns:1fr; }} }}
.sqlcol {{ border:1px solid var(--border); border-radius:12px; padding:14px; }}
.sqlcol-ok {{ background:rgba(16,185,129,.05); border-color:rgba(16,185,129,.3); }}
.sqlcol-bad {{ background:rgba(239,68,68,.05); border-color:rgba(239,68,68,.3); }}
.sqlcol-h {{ font-size:13px; font-weight:700; margin-bottom:12px; }}
.sqlcol-h b {{ font-size:16px; }}
.sqlcol-h span {{ font-size:11px; color:var(--muted); font-weight:600; }}
.sqlflow {{ display:flex; flex-direction:column; align-items:center; gap:4px; }}
.sfv-step {{ width:100%; text-align:center; background:rgba(255,255,255,.04); border:1px solid var(--border); border-radius:9px; padding:10px 12px; }}
.sfv-step b {{ display:block; font-size:26px; font-weight:800; color:var(--text); line-height:1; }}
.sfv-step span {{ font-size:11px; color:var(--muted); line-height:1.35; }}
.sfv-step.sfv-mid {{ border-color:rgba(245,158,11,.4); background:rgba(245,158,11,.08); }}
.sfv-step.sfv-mid b {{ color:#fcd34d; }}
.sfv-step.sfv-ok {{ border-color:rgba(16,185,129,.45); background:rgba(16,185,129,.1); }}
.sfv-step.sfv-ok b {{ color:#6ee7b7; }}
.sfv-arrow {{ font-size:18px; color:var(--muted); font-weight:800; }}
.fb-lsbox {{ margin-top:14px; border:1px solid var(--border); background:rgba(255,255,255,.03); border-radius:10px; padding:13px 14px; }}
.fb-ls-head {{ font-size:13px; color:var(--text); margin-bottom:10px; line-height:1.4; }}
.ls-list {{ display:grid; grid-template-columns:1fr 1fr; gap:6px 16px; }}
@media(max-width:640px){{ .ls-list {{ grid-template-columns:1fr; }} }}
.ls-row {{ display:flex; align-items:center; gap:8px; font-size:12px; color:var(--text-2); padding:5px 8px; border-radius:7px; background:rgba(255,255,255,.02); }}
.ls-row.ls-adv {{ background:rgba(16,185,129,.08); }}
.ls-row.ls-warm {{ background:rgba(245,158,11,.07); }}
.ls-row.ls-cold {{ background:rgba(239,68,68,.06); }}
.ls-l {{ flex:1; line-height:1.3; }}
.ls-n {{ font-weight:800; color:var(--text); }}
.ls-p {{ font-size:11px; color:var(--muted); font-weight:600; }}
@media(max-width:640px){{ .fbr-l {{ flex-basis:48%; }} }}

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
/* Grupo ESTADOS (salmón) vs grupo ACCIONES/EVOLUCIÓN → empresas (teal) */
.f-c-state {{ --fc:var(--guru-500); --fv:var(--guru-300); }}
.f-c-state {{ background:rgba(87,224,138,.05); }}
.f-c-action {{ --fc:var(--teal); --fv:var(--teal); }}
.f-c-action {{ background:rgba(34,211,238,.06); }}
.day-kpis {{ display:grid; grid-template-columns:repeat(6,1fr); gap:10px; }}
@media(max-width:900px){{ .day-kpis {{ grid-template-columns:repeat(3,1fr); }} }}
@media(max-width:520px){{ .day-kpis {{ grid-template-columns:repeat(2,1fr); }} }}
.df-card {{ flex:1; min-width:110px; background:var(--card); border:1px solid var(--border); border-top:3px solid var(--guru-500); border-radius:10px; padding:9px 12px; }}
.df-card .fc-value {{ font-size:30px; }}
.df-card .fc-label {{ font-size:10px; }}
.df-card .fc-sub {{ font-size:10px; margin-top:4px; }}
.df-state {{ border-top-color:var(--guru-500); background:rgba(87,224,138,.05); }}
.df-action {{ border-top-color:var(--teal); background:rgba(34,211,238,.10); box-shadow:0 0 0 1px rgba(34,211,238,.35), 0 4px 18px rgba(34,211,238,.15); position:relative; }}
.df-action .fc-value {{ color:var(--teal); }}
.df-action::before {{ content:"ACCIÓN"; position:absolute; top:-9px; right:10px; font-size:9px; font-weight:800; letter-spacing:.08em; color:#0a2a2f; background:var(--teal); padding:2px 7px; border-radius:10px; }}
/* Panel destacado del bloque 24h (fondo con degradado en la paleta, más claro que el resto) */
.hero24 {{ background:linear-gradient(135deg, rgba(87,224,138,.16) 0%, rgba(20,60,45,.28) 50%, rgba(34,211,238,.16) 100%); border:1px solid rgba(87,224,138,.35); border-radius:18px; padding:20px 22px 14px; margin-bottom:30px; box-shadow:0 8px 34px rgba(87,224,138,.12); }}
.hero24 .section-label {{ color:var(--guru-300); }}
.hero24-cap {{ margin-top:14px; }}
.down-link {{ text-align:left; margin:-10px 0 18px; padding-left:70px; font-size:13px; color:var(--text-2); }}
.down-link .dl-arrow {{ display:block; font-size:22px; color:var(--guru-300); font-weight:800; line-height:1; margin-bottom:2px; }}
.down-link b {{ color:var(--guru-300); }}
@media(max-width:760px){{ .down-link {{ text-align:center; padding-left:0; }} }}
.df-op {{ align-self:center; font-size:22px; font-weight:800; color:var(--muted); flex:0 0 auto; }}
.df-arrow {{ color:var(--guru-300); }}
/* Árbol de dos ramas (24h) · Contactos = origen de ambas */
.daytree {{ display:flex; align-items:stretch; gap:14px; flex-wrap:wrap; }}
.dt-root {{ flex:0 0 auto; min-width:180px; align-self:stretch; display:flex; flex-direction:column; justify-content:center; text-align:center; background:linear-gradient(135deg,rgba(87,224,138,.16),rgba(34,211,238,.12)); border:2px solid rgba(87,224,138,.4); border-radius:16px; padding:14px 18px; box-shadow:0 6px 24px rgba(87,224,138,.18); }}
.dt-root .fc-label {{ font-size:11px; text-transform:uppercase; letter-spacing:.06em; }}
.dt-root .fc-value {{ font-size:54px; font-weight:800; background:linear-gradient(135deg,#1f9d5f,#57e08a); -webkit-background-clip:text; background-clip:text; -webkit-text-fill-color:transparent; }}
.dt-root .fc-sub {{ font-size:10px; }}
.dt-branches {{ flex:1; min-width:280px; display:flex; flex-direction:column; gap:10px; }}
.dt-branch {{ display:flex; align-items:center; gap:10px; }}
.dt-body {{ padding:10px 12px; }}
.dt-arm {{ flex:0 0 auto; font-size:26px; font-weight:800; color:var(--guru-300); }}
.dt-free .dt-arm {{ color:var(--teal); }}
.dt-body {{ flex:1; border:1px solid var(--border); border-radius:12px; padding:12px 14px; }}
.dt-com .dt-body {{ background:rgba(87,224,138,.05); border-color:rgba(87,224,138,.28); }}
.dt-free .dt-body {{ background:rgba(34,211,238,.05); border-color:rgba(34,211,238,.28); }}
.df-free-card {{ flex:0 0 auto; min-width:120px; border-top-color:var(--teal); background:rgba(34,211,238,.08); text-align:center; }}
.df-free-card .fc-value {{ font-size:34px; color:var(--teal); }}
.dt-free-txt {{ flex:1; align-self:center; font-size:13px; color:var(--text-2); line-height:1.5; }}
.dt-btag {{ font-size:12px; font-weight:700; color:var(--text-2); margin-bottom:10px; }}
.dt-btag b {{ color:var(--guru-300); font-size:14px; }}
.dt-free-tag b {{ color:var(--teal); }}
.dt-row {{ display:flex; align-items:stretch; gap:8px; flex-wrap:wrap; }}
@media(max-width:760px){{ .daytree {{ flex-direction:column; }} .dt-branch {{ flex-direction:column; align-items:stretch; }} .dt-arm {{ transform:rotate(90deg); align-self:center; }} .dt-row {{ flex-direction:column; }} .df-op {{ transform:rotate(90deg); align-self:center; }} }}
.free-kpi {{ margin-top:12px; background:var(--card); border:1px solid var(--border); border-radius:10px; padding:14px 16px; display:flex; align-items:baseline; gap:12px; }}
.free-kpi .fk-num {{ font-size:32px; font-weight:800; color:var(--teal); }}
.free-kpi .fk-txt {{ font-size:12px; color:var(--text-2); }}

.channels-grid {{ display:grid; grid-auto-flow:column; grid-auto-columns:minmax(0,1fr); gap:8px; }}
@media(max-width:900px){{ .channels-grid {{ grid-auto-flow:row; grid-template-columns:repeat(3,1fr); }} }}
@media(max-width:550px){{ .channels-grid {{ grid-template-columns:repeat(2,1fr); }} }}
.ch-card {{ background:var(--card); border:1px solid var(--border); border-radius:10px; padding:12px 9px; position:relative; overflow:hidden; }}
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
.table td {{ font-size:13px; color:var(--text-2); padding:10px 12px 10px 0; border-bottom:1px solid rgba(20,60,45,.5); }}
.table td strong {{ color:var(--text); font-weight:600; }}
.table tr.stage-divider td {{ background:rgba(255,255,255,.03); font-size:10px; font-weight:700; text-transform:uppercase; color:var(--muted); padding:6px 0; }}
.pill {{ display:inline-block; font-size:11px; font-weight:600; padding:3px 9px; border-radius:20px; white-space:nowrap; }}
.pill-demo {{ background:rgba(16,185,129,.15); color:var(--green); }}
.pill-discov {{ background:rgba(87,224,138,.15); color:#F5D5C8; }}
.pill-best {{ background:rgba(245,158,11,.15); color:var(--amber); }}
.pill-lost {{ background:rgba(239,68,68,.15); color:#fca5a5; }}
.dt-next {{ font-weight:700; color:var(--guru-300); white-space:nowrap; }}
.dt-past {{ color:var(--muted); white-space:nowrap; }}
.dt-none {{ color:var(--muted); }}
.new-tag {{ font-size:10px; font-weight:700; padding:2px 7px; border-radius:10px; background:rgba(16,185,129,.2); color:var(--green); text-transform:uppercase; }}
.alert {{ border-radius:8px; padding:10px 14px; font-size:12px; margin-top:14px; display:flex; align-items:flex-start; gap:8px; }}
.alert-muted {{ background:rgba(123,118,160,.06); border:1px solid rgba(123,118,160,.2); color:var(--muted); }}
.caption {{ font-size:11px; color:var(--muted); margin-top:8px; line-height:1.6; }}
.og-sub {{ font-size:11px; font-weight:800; letter-spacing:.05em; text-transform:uppercase; color:var(--muted); margin:16px 0 10px; }}
.og-pct {{ font-size:14px; font-weight:700; color:var(--muted); }}
.og-head {{ display:flex; gap:12px; margin-bottom:18px; flex-wrap:wrap; }}
.og-stat {{ flex:1; min-width:150px; background:rgba(255,255,255,.03); border:1px solid var(--border); border-radius:10px; padding:12px 14px; }}
.og-stat > b {{ display:block; font-size:26px; font-weight:800; color:var(--text); line-height:1.1; }}
.og-stat span {{ font-size:11px; color:var(--muted); line-height:1.35; display:block; margin-top:4px; }}
.og-stat span b {{ font-size:11px; font-weight:700; color:inherit; }}
.og-stat {{ border-top-width:3px; }}
.og-tag {{ font-size:10px; font-weight:800; letter-spacing:.07em; color:var(--muted); margin-bottom:4px; }}
.og-stat.og-total {{ background:rgba(87,224,138,.08); border-color:rgba(87,224,138,.35); border-top-color:var(--guru-500); }}
.og-stat.og-total > b {{ color:var(--guru-300); }}
.og-stat.og-content {{ background:rgba(16,185,129,.08); border-color:rgba(16,185,129,.35); border-top-color:var(--green); }}
.og-stat.og-content > b {{ color:#6ee7b7; }}
.og-stat.og-content .og-tag {{ color:#6ee7b7; }}
.og-stat.og-noinfo {{ background:rgba(123,118,160,.08); border-color:rgba(123,118,160,.3); border-top-color:var(--muted); }}
.og-row {{ display:flex; align-items:center; gap:10px; margin-bottom:8px; }}
.og-l {{ flex:0 0 40%; font-size:12px; color:var(--text-2); line-height:1.3; }}
.og-barwrap {{ flex:1; background:rgba(255,255,255,.05); border-radius:5px; height:13px; overflow:hidden; }}
.og-bar {{ height:13px; border-radius:5px; background:linear-gradient(90deg,#6f8c7e,#a5a1c8); }}
.og-row.og-content .og-bar {{ background:linear-gradient(90deg,#0E7490,#22D3EE); }}
.og-row.og-noinfo .og-bar {{ background:linear-gradient(90deg,#5a5680,#6f8c7e); }}
.og-n {{ flex:0 0 62px; text-align:right; font-size:13px; font-weight:800; color:var(--guru-300); }}
.og-p {{ font-size:11px; color:var(--muted); font-weight:600; }}
@media(max-width:640px){{ .og-l {{ flex-basis:50%; }} }}
.drz-head {{ display:flex; gap:12px; margin-bottom:18px; flex-wrap:wrap; }}
.drz-stat {{ flex:1; min-width:150px; background:rgba(255,255,255,.03); border:1px solid var(--border); border-radius:10px; padding:12px 14px; }}
.drz-stat b {{ display:block; font-size:26px; font-weight:800; color:var(--text); line-height:1.1; }}
.drz-stat span {{ font-size:11px; color:var(--muted); line-height:1.35; display:block; margin-top:4px; }}
.drz-stat-top {{ background:rgba(87,224,138,.08); border-color:rgba(87,224,138,.35); }}
.drz-stat-top b {{ color:var(--guru-300); }}
.drz-row {{ display:flex; align-items:center; gap:10px; margin-bottom:9px; }}
.drz-rank {{ flex:0 0 22px; height:22px; line-height:22px; text-align:center; font-size:11px; font-weight:800; color:var(--muted); background:rgba(255,255,255,.05); border-radius:6px; }}
.drz-l {{ flex:0 0 38%; font-size:12px; color:var(--text-2); line-height:1.35; }}
.drz-barwrap {{ flex:1; background:rgba(255,255,255,.05); border-radius:5px; height:14px; overflow:hidden; }}
.drz-bar {{ height:14px; border-radius:5px; background:linear-gradient(90deg,var(--guru-500),var(--guru-400)); }}
.drz-bar-top {{ background:linear-gradient(90deg,#FF6B5B,#FF8A65); box-shadow:0 0 10px rgba(87,224,138,.35); }}
.drz-n {{ flex:0 0 74px; text-align:right; font-size:14px; font-weight:800; color:var(--guru-300); }}
.drz-pct {{ font-size:11px; color:var(--muted); font-weight:600; }}
@media(max-width:600px){{ .drz-l {{ flex-basis:46%; font-size:11px; }} .drz-stat b {{ font-size:22px; }} }}
/* Flujo de precualificación */
.preq {{ background:var(--card); border:1px solid var(--border); border-radius:14px; padding:20px; }}
.preq-top {{ text-align:center; font-size:15px; font-weight:700; color:var(--text); background:rgba(87,224,138,.12); border:1px solid rgba(87,224,138,.3); border-radius:10px; padding:12px; }}
.preq-arrow {{ text-align:center; font-size:11px; color:var(--muted); font-weight:700; letter-spacing:.04em; margin:10px 0; }}
.preq-branches {{ display:grid; grid-template-columns:1fr 1fr; gap:14px; }}
@media(max-width:640px){{ .preq-branches {{ grid-template-columns:1fr; }} }}
.preq-card {{ border-radius:12px; padding:16px; border:1px solid var(--border); }}
.preq-sales {{ background:rgba(87,224,138,.08); border-color:rgba(87,224,138,.35); }}
.preq-free {{ background:rgba(34,211,238,.08); border-color:rgba(34,211,238,.3); }}
.preq-h {{ font-size:13px; font-weight:800; margin-bottom:7px; }}
.preq-sales .preq-h {{ color:var(--guru-300); }}
.preq-free .preq-h {{ color:var(--teal); }}
.preq-b {{ font-size:12px; color:var(--text-2); line-height:1.55; }}
.preq-tag {{ display:inline-block; font-size:10px; font-weight:800; text-transform:uppercase; letter-spacing:.05em; padding:2px 8px; border-radius:20px; margin-bottom:8px; }}
.preq-sales .preq-tag {{ background:rgba(87,224,138,.2); color:var(--guru-300); }}
.preq-free .preq-tag {{ background:rgba(34,211,238,.18); color:var(--teal); }}
.pqs {{ display:flex; gap:8px; margin-top:12px; flex-wrap:wrap; }}
.pqs-item {{ flex:1; min-width:120px; background:rgba(255,255,255,.04); border:1px solid var(--border); border-radius:8px; padding:9px 11px; }}
.pqs-item b {{ display:block; font-size:20px; font-weight:800; color:var(--text); line-height:1.1; }}
.pqs-item span {{ font-size:10px; color:var(--muted); line-height:1.35; }}
.pqs-item.pqs-ok {{ border-color:rgba(16,185,129,.35); background:rgba(16,185,129,.08); }}
.pqs-item.pqs-ok b {{ color:#6ee7b7; }}
.pqs-item.pqs-bad {{ border-color:rgba(239,68,68,.35); background:rgba(239,68,68,.08); }}
.pqs-item.pqs-bad b {{ color:#fca5a5; }}
.pqflow {{ display:flex; align-items:stretch; gap:6px; margin-top:12px; flex-wrap:wrap; }}
.pqf-step {{ flex:1; min-width:96px; background:rgba(255,255,255,.04); border:1px solid var(--border); border-radius:8px; padding:9px 10px; text-align:center; }}
.pqf-step b {{ display:block; font-size:18px; font-weight:800; color:var(--text); line-height:1.1; }}
.pqf-step span {{ font-size:10px; color:var(--muted); line-height:1.3; }}
.pqf-step.pqf-ok {{ border-color:rgba(16,185,129,.4); background:rgba(16,185,129,.09); }}
.pqf-step.pqf-ok b {{ color:#6ee7b7; }}
.pqf-arrow {{ align-self:center; color:var(--muted); font-size:15px; display:flex; flex-direction:column; align-items:center; }}
.pqf-pct {{ font-size:11px; font-weight:800; color:var(--guru-300); }}
.pqf-channel {{ margin-top:10px; font-size:12px; color:var(--text-2); background:rgba(255,255,255,.03); border:1px solid var(--border); border-radius:8px; padding:8px 12px; }}
.pqf-ch-tel {{ color:#6ee7b7; font-weight:700; }}
.pqf-ch-vid {{ color:#c4b5fd; font-weight:700; }}
.pqvol {{ display:flex; gap:8px; margin-top:10px; flex-wrap:wrap; }}
.pqvol-item {{ flex:1; min-width:120px; background:rgba(255,255,255,.04); border:1px solid var(--border); border-radius:8px; padding:9px 11px; }}
.pqvol-item b {{ display:block; font-size:22px; font-weight:800; color:var(--text); line-height:1; }}
.pqvol-item span {{ font-size:10px; color:var(--muted); line-height:1.35; }}
.pqvol-item.pqvol-ok {{ border-color:rgba(16,185,129,.4); background:rgba(16,185,129,.08); }}
.pqvol-item.pqvol-ok b {{ color:#6ee7b7; }}
.pqvol-item.pqvol-bad {{ border-color:rgba(239,68,68,.35); background:rgba(239,68,68,.07); }}
.pqvol-item.pqvol-bad b {{ color:#fca5a5; }}
.pqvol-note {{ width:100%; margin-top:8px; font-size:10.5px; line-height:1.45; color:var(--guru-300); background:rgba(251,191,36,.08); border:1px solid rgba(251,191,36,.28); border-radius:8px; padding:8px 11px; }}
.pqvol-note b {{ color:#fcd34d; font-weight:800; }}
.pqf-sub {{ font-size:11px; font-weight:800; letter-spacing:.04em; text-transform:uppercase; color:var(--guru-300); margin:16px 0 8px; }}
.pqbig {{ display:flex; align-items:center; gap:16px; margin-top:12px; }}
.pqbig-n {{ font-size:46px; font-weight:800; color:#fca5a5; line-height:1; flex:0 0 auto; }}
.pqbig-t {{ font-size:11px; color:var(--text-2); line-height:1.45; }}
.pqbig-ul {{ margin:0; padding-left:18px; font-size:12px; color:var(--text-2); line-height:1.55; }}
.pqbig-ul li {{ margin-bottom:3px; }}
@media(max-width:640px){{ .pqflow {{ flex-direction:column; }} .pqf-arrow {{ flex-direction:row; gap:6px; transform:rotate(90deg); }} .pqbig {{ flex-direction:column; align-items:flex-start; }} }}
.preq-pref {{ margin-top:16px; }}
.cpref {{ display:flex; align-items:center; gap:20px; background:rgba(255,255,255,.03); border:1px solid var(--border); border-radius:12px; padding:16px 18px; flex-wrap:wrap; }}
.cpref-donut {{ width:110px; height:110px; border-radius:50%; flex:0 0 auto; display:flex; align-items:center; justify-content:center; }}
.cpref-hole {{ width:70px; height:70px; border-radius:50%; background:var(--card); display:flex; flex-direction:column; align-items:center; justify-content:center; }}
.cpref-hole b {{ font-size:24px; font-weight:800; color:var(--text); line-height:1; }}
.cpref-hole span {{ font-size:9px; color:var(--muted); }}
.cpref-leg {{ flex:1; min-width:220px; }}
.cpref-t {{ font-size:13px; font-weight:700; margin-bottom:10px; }}
.cpref-t span {{ font-weight:400; font-size:11px; color:var(--muted); }}
.cpref-row {{ font-size:13px; color:var(--text-2); margin-bottom:6px; display:flex; align-items:center; gap:8px; }}
.cpref-dot {{ width:11px; height:11px; border-radius:3px; display:inline-block; }}
.cpref-note {{ font-size:11px; color:var(--muted); margin-top:6px; }}
.pm-head {{ display:flex; gap:10px; margin-bottom:16px; flex-wrap:wrap; }}
.pm-stat {{ flex:1; min-width:130px; background:rgba(255,255,255,.03); border:1px solid var(--border); border-radius:10px; padding:12px 14px; }}
.pm-stat b {{ display:block; font-size:24px; font-weight:800; color:var(--text); line-height:1.1; }}
.pm-stat span {{ font-size:10px; color:var(--muted); line-height:1.35; display:block; margin-top:4px; }}
.pm-stat.pm-spend {{ background:rgba(168,85,247,.08); border-color:rgba(168,85,247,.35); }}
.pm-stat.pm-spend b {{ color:#c4b5fd; }}
.pm-stat.pm-ok {{ background:rgba(16,185,129,.08); border-color:rgba(16,185,129,.35); }}
.pm-stat.pm-ok b {{ color:#6ee7b7; }}
.pm-pend {{ font-size:13px; color:var(--muted); font-weight:600; }}
.pm-table {{ margin-top:16px; }}
.pm-table td {{ font-variant-numeric:tabular-nums; }}
/* Pipeline Paid (Agustín) · Paid Leads Tracker */
.pt-empty {{ font-size:13px; color:var(--muted); line-height:1.5; padding:6px 0; }}
.pt-kpis {{ display:grid; grid-template-columns:repeat(6,1fr); gap:8px; }}
.pt-kpi {{ background:rgba(255,255,255,.03); border:1px solid var(--border); border-radius:10px; padding:12px 12px; }}
.pt-kpi b {{ display:block; font-size:26px; font-weight:800; color:var(--text); line-height:1; font-variant-numeric:tabular-nums; }}
.pt-kpi span {{ font-size:10px; color:var(--muted); line-height:1.3; display:block; margin-top:5px; }}
.pt-kpi.pt-qualified b {{ color:#6ee7b7; }}
.pt-kpi.pt-won {{ background:rgba(16,185,129,.09); border-color:rgba(16,185,129,.35); }}
.pt-kpi.pt-won b {{ color:#6ee7b7; }}
.pt-kpi.pt-lost {{ background:rgba(239,68,68,.07); border-color:rgba(239,68,68,.3); }}
.pt-kpi.pt-lost b {{ color:#fca5a5; }}
.pt-kpi.pt-uncontacted b {{ color:#fcd34d; }}
.pt-afc {{ font-size:12px; color:var(--text-2); margin:12px 0 2px; }}
.pt-afc b {{ color:var(--guru-300); }}
.pt-cols {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(240px,1fr)); gap:20px; margin-top:16px; }}
.pt-h {{ font-size:11px; font-weight:800; letter-spacing:.04em; text-transform:uppercase; color:var(--guru-300); margin-bottom:10px; }}
.fbr-bar.pt-bar2 {{ background:linear-gradient(90deg,#1f6feb,#5bc8f2); }}
.fbr-bar.pt-bar3 {{ background:linear-gradient(90deg,#7a3b1f,#f59e0b); }}
@media(max-width:720px){{ .pt-kpis {{ grid-template-columns:repeat(3,1fr); }} }}

@media(max-width:600px){{
  .header {{ padding:0 14px; }} .header-title h1 {{ font-size:14px; }} .header-title p {{ font-size:10px; }}
  .live-badge {{ display:none; }} .main {{ padding:18px 14px 50px; }}
  .funnel {{ flex-direction:column; gap:8px; }} .f-arrow {{ width:100%; height:20px; transform:rotate(90deg); }}
  .fc-value {{ font-size:32px; }} .card {{ padding:16px 14px; overflow-x:auto; }} .table {{ min-width:300px; }}
  .section-label {{ font-size:10px; margin-top:26px; }}
}}
#gs-gate {{ position:fixed; inset:0; z-index:9999; background:#08120e; display:flex; align-items:center; justify-content:center; }}
#gs-gate .box {{ background:#132a20; border:1px solid #20402f; border-radius:16px; padding:40px 36px; width:340px; text-align:center; }}
#gs-gate .logo {{ width:48px; height:48px; border-radius:12px; margin:0 auto 20px; background:linear-gradient(135deg,#1f9d5f,#57e08a); display:flex; align-items:center; justify-content:center; font-weight:800; color:#fff; }}
#gs-gate h2 {{ font-size:18px; font-weight:700; margin-bottom:4px; }} #gs-gate p {{ font-size:13px; color:#6f8c7e; margin-bottom:24px; }}
#gs-gate input {{ width:100%; padding:11px 14px; border-radius:8px; border:1px solid #20402f; background:#0f1e18; color:#eafff4; font-size:15px; margin-bottom:12px; outline:none; letter-spacing:.08em; }}
#gs-gate button {{ width:100%; padding:11px; border-radius:8px; border:none; cursor:pointer; background:linear-gradient(135deg,#1f9d5f,#57e08a); color:#fff; font-size:15px; font-weight:700; }}
#gs-gate .err {{ color:#ef4444; font-size:12px; margin-top:8px; display:none; }}
.refresh-fab {{ position:fixed; right:20px; top:16px; z-index:1000; cursor:pointer;
  background:linear-gradient(135deg,#1f9d5f,#57e08a); color:#fff; border:none; border-radius:30px;
  padding:10px 16px; font-size:13px; font-weight:700; box-shadow:0 6px 20px rgba(87,224,138,.4); }}
.refresh-fab:hover {{ filter:brightness(1.05); }}
.refresh-toast {{ position:fixed; right:20px; top:60px; z-index:1000; max-width:340px;
  background:#132a20; border:1px solid var(--border); border-radius:12px; padding:14px 16px;
  font-size:12px; color:var(--text-2); line-height:1.5; box-shadow:0 8px 28px rgba(0,0,0,.4);
  opacity:0; transform:translateY(10px); pointer-events:none; transition:opacity .2s, transform .2s; }}
.refresh-toast.show {{ opacity:1; transform:translateY(0); pointer-events:auto; }}
.refresh-toast .rt-btn {{ display:inline-block; margin-top:10px; cursor:pointer; border:none;
  background:var(--guru-500); color:#fff; font-weight:700; font-size:12px; padding:7px 12px; border-radius:8px; }}
@media(max-width:600px){{ .refresh-fab {{ right:12px; bottom:12px; padding:10px 14px; font-size:13px; }} }}
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
  <div class="header-title"><h1>{title}</h1><p>{fecha_larga} · {periodo_txt}</p></div></div>
  <div class="sync-bar">Generado el {generado} · embudos acumulados {fun_label} · gráficos anuales {chart_label}</div></div>

<div class="main">

  <details class="glossary">
    <summary><span class="gl-ico">📖</span> Minidiccionario · qué significa cada término <span class="gl-hint">(pulsa para desplegar)</span></summary>
    <div class="gl-grid">
      <div class="gl-card"><span class="gl-e">👤</span><div><b>Contacto</b><span>Cualquier persona (un email) que entra en el CRM. Excluye tests, empleados e importaciones.</span></div></div>
      <div class="gl-card"><span class="gl-e">🌱</span><div><b>Lead</b><span>Contacto <strong>sin cualificar</strong>: ha entrado, pero aún no sabemos su interés.</span></div></div>
      <div class="gl-card"><span class="gl-e">📘</span><div><b>MQL <span class="gl-en">· Marketing Qualified Lead</span></b><span>Lead que ha <strong>consumido contenido</strong> (ebook, webinar, blog…). Interés medio.</span></div></div>
      <div class="gl-card"><span class="gl-e">🎯</span><div><b>SQL <span class="gl-en">· Sales Qualified Lead</span></b><span>Tiene una <strong>necesidad real</strong> y <strong>pide demo/reunión</strong> con ventas. Listo para trabajar.</span></div></div>
      <div class="gl-card"><span class="gl-e">💼</span><div><b>Oportunidad</b><span>SQL con <strong>negocio (deal) abierto</strong> en el pipeline. Se cuenta por <strong>empresa</strong>.</span></div></div>
      <div class="gl-card"><span class="gl-e">🏆</span><div><b>Cliente</b><span>Empresa que ha <strong>cerrado</strong> y ya compra. Se cuenta por empresa.</span></div></div>
      <div class="gl-card gl-wide"><span class="gl-e">🛠️</span><div><b>Pipeline de ventas <span class="gl-en">· pipeline de negocio</span></b><span>Se <strong>abre al crear un nuevo deal</strong> (oportunidad) y recorre las etapas del negocio: <strong>Discovery → Demo → Best Case → Cliente</strong>. Muestra en qué punto está cada empresa camino a cliente.</span></div></div>
      <div class="gl-card"><span class="gl-e">🔄</span><div><b>Funnel / embudo</b><span>El <strong>viaje</strong> del contacto de principio a fin: Contacto → Lead → MQL → SQL → Oportunidad → Cliente.</span></div></div>
      <div class="gl-card"><span class="gl-e">📅</span><div><b>Reunión agendada</b><span>Demo/discovery citada + llamadas de los SDR en el período.</span></div></div>
      <div class="gl-card"><span class="gl-e">🚫</span><div><b>Descarte</b><span>SQL que no avanza. Se anota el <strong>motivo</strong> (precio, volumen, timing…).</span></div></div>
      <div class="gl-card"><span class="gl-e">🧊</span><div><b>Freemium</b><span>Alta <strong>gratis por la app</strong>. No entra en el embudo comercial.</span></div></div>
      <div class="gl-card"><span class="gl-e">🔭</span><div><b>TOFU <span class="gl-en">· Top of the Funnel</span></b><span>Fase de <strong>descubrimiento</strong>: el lead curiosea, se informa por encima. Poca intención (blog, artículos).</span></div></div>
      <div class="gl-card"><span class="gl-e">📗</span><div><b>MOFU <span class="gl-en">· Middle of the Funnel</span></b><span>Fase de <strong>consideración</strong>: consume contenido <strong>más formativo/de valor</strong> (ebook, webinar, newsletter). Se está formando.</span></div></div>
      <div class="gl-card"><span class="gl-e">🎯</span><div><b>BOFU <span class="gl-en">· Bottom of the Funnel</span></b><span>Fase de <strong>decisión</strong>: compara y evalúa herramientas (calculadora ROI, comparativas, demo). Alta intención.</span></div></div>
    </div>
  </details>

  <div class="hero24">
    <div class="section-label" style="margin:0 0 14px;">Contactos generados · últimas 24h</div>
    {day_funnel}
    <div class="caption hero24-cap">ℹ️ Volumen de nuevos contactos de las últimas 24h y en qué se dividen (Leads + MQL + SQL). Los <strong>SQL</strong> derivan en <strong>llamadas/videollamadas</strong> realizadas por los SDR (Agustín/Juanma). <strong>Freemium</strong> va aparte (fuera del embudo comercial). Reuniones hoy: {meet_names}</div>
  </div>

  <div class="down-link"><span class="dl-arrow">↓</span> Y estos contactos, <b>¿de qué canales vienen?</b></div>

  <div class="section-label">Canales de adquisición · últimas 24h</div>
  <div class="channels-grid">{ch_cards}</div>

  <div class="section-label">Flujo de precualificación de nuevos contactos · seguimiento de Agustín desde el 9 de julio</div>
  <div class="preq">
    <div class="preq-top">📩 Nuevo contacto pide <strong>demo</strong> (formulario web ES/EN de HubSpot) → se evalúa su <strong>volumen de consultas/mes</strong> <span style="color:var(--muted);font-weight:400;">(acción implantada el 9 jul; los datos son evolutivos <b>a partir de esa fecha</b>, no de todo el histórico). Todos son <b>SQL</b>.</span></div>
    <div class="preq-arrow">▼ ▼ ▼</div>
    <div class="preq-branches">
      <div class="preq-card preq-sales">
        <div class="preq-tag">Precualificación · a Agustín</div>
        <div class="preq-h">➕ +3.000 consultas/mes · o «no conozco el volumen»</div>
        <div class="preq-b">SQL que <strong>sí precualifican</strong>: se genera una <strong>tarea automática a Agustín</strong> para <strong>agendar la demo</strong> y contactar por el <strong>canal indicado en el formulario</strong> (llamada o email). Si no cualifica, se registra la <strong>razón de descarte</strong>.</div>
        {preq_sales_stats}
      </div>
      <div class="preq-card preq-free">
        <div class="preq-tag">Descarte inicial · automatizado</div>
        <div class="preq-h">➖ −3.000 consultas/mes</div>
        <div class="preq-b">SQL con <strong>volumen insuficiente</strong> (&lt;3.000 consultas): <strong>descarte inicial automático</strong> — reciben un email de agradecimiento. No pasan a Agustín.</div>
        {preq_free_stats}
      </div>
    </div>
    <div class="preq-pref">{canal_pref_html}</div>
  </div>

  <div class="section-label">Seguimiento de ventas · estado de los SQL · últimas 24h</div>
  <div class="card">
    <div class="card-header"><span class="card-title">SQL del período · empresa, canal y estado</span>
      <span class="badge badge-green">📞 Seguimiento comercial</span></div>
    <table class="table"><thead><tr><th>SQL</th><th>Empresa · canal</th><th>Razón de descarte</th></tr></thead>
    <tbody>{call_rows}</tbody></table>
    <div class="alert alert-muted"><span>ℹ️</span><div>Solo <strong>contactos en etapa SQL</strong> del período (no leads). La <strong>razón de descarte</strong> aparece si el SQL se ha descartado; si está vacía (—), sigue en proceso o aún no tiene motivo registrado.</div></div>
  </div>

  <div class="evo-banner">
    <div class="evo-l"><span class="evo-ico">📈</span><div><div class="evo-t">A partir de aquí · Evolutivo anual acumulado</div><div class="evo-s">Fin de las últimas 24h. Todo lo que sigue suma el histórico desde el 1 de enero de 2026</div></div></div>
    <span class="evo-badge">ACUMULADO · {chart_label}</span>
  </div>

  <div class="section-label">Flujo del contacto al cliente · proceso y conversión · acumulado {fun_label}</div>
  <div class="fn-box">
    <div class="fn-title">🔄 Del contacto al cliente</div>
    <div class="fn-note">Cada etapa, por qué se clasifica así, su volumen y el % de conversión respecto a la etapa anterior</div>
    {flow_full}
  </div>
  <div class="caption">ℹ️ Cómo leer el embudo: <strong>«Leads» y «MQL» son acumulativos</strong> —incluyen a los contactos que ya avanzaron a etapas posteriores (SQL, oportunidad o cliente)—, por eso cada etapa es menor que la anterior. <strong>«Oportunidad» y «Cliente» se cuentan como empresas únicas</strong> (una por compañía), no como contactos; por eso no suman contra los contactos/leads. <strong>MQL y SQL se calculan como % sobre leads</strong> (no sobre el total de contactos, que incluye freemium y no forma parte del embudo comercial).</div>

  <div class="section-label">Leads · origen y desglose · acumulado desde el 1 de enero</div>
  <div class="card">
    {origin_html}
    <div class="alert alert-muted"><span>💡</span><div><b>TOFU/MOFU/BOFU:</b> los <b>MOFU/BOFU</b> han consumido contenido de valor (consideración/decisión) = <b>MQL de facto</b>; los <b>TOFU</b> están en descubrimiento (menos intención). Clasificado por el formulario/evento de conversión de HubSpot.
    <br><br>⚠️ <b>¿Por qué aquí hay más «MQL» que en el embudo de arriba?</b> Arriba, «MQL {mql_stage}» es la <b>etapa de ciclo de vida</b> de HubSpot (contactos que ventas/marketing han <b>promocionado</b> a MQL o más). Aquí, «MOFU/BOFU» cuenta a <b>todos los que han consumido contenido</b> (comportamiento), aunque HubSpot los siga marcando como «lead». La diferencia = leads que consumen contenido pero <b>aún no están promocionados</b> a etapa MQL en el CRM (oportunidad de nutrición). Tu nuevo workflow (calculadora → MQL) irá cerrando esa brecha.
    <br><br>🧹 Se han <b>excluido {excl_noinfo} leads/MQL sin origen identificado</b> (sin evento de conversión) de todos los totales (contactos, leads, acumulados) por no aportar dato fiable.</div></div>
  </div>

  <div class="section-label">Paid media · gasto y embudo · acumulado desde el 1 de enero</div>
  <div class="card">
    {paid_html}
    <div class="alert alert-muted"><span>💰</span><div>Embudo de los canales de <strong>pago</strong> (Google Ads + Social Ads) desde el 1 de enero: contactos → leads → MQL → SQL → oportunidades (empresas), con % de conversión. El <strong>gasto</strong> aún no está conectado (lo estamos trabajando); en cuanto se cargue, se calculan CPL, coste por SQL y por oportunidad automáticamente.</div></div>
  </div>

  <div class="section-label">Pipeline Paid (Agustín) · seguimiento de inbound de paid · <span style="color:var(--guru-300)">desde el 1 de julio</span></div>
  <div class="card">
    {paidtracker_html}
    <div class="alert alert-muted"><span>⚡</span><div>Pipeline de ventas donde se trabajan los <strong>inbound de paid media</strong> (Google Ads + Social Ads), sincronizado en vivo desde el <strong>Paid Leads Tracker</strong>. Datos <strong>desde el 1 de julio</strong> (el resto del informe viene de HubSpot). Se refresca en cada actualización del dashboard.</div></div>
  </div>

  <div class="section-label">Estado de los SQL · gestión, conversión y descarte · acumulado</div>
  <div class="fn-box">
    {flow_branch}
  </div>

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
      Oportunidades inbound reales (se excluyen deals heredados/comercial mal atribuidos como Xtrim o Plenergy) ·
      🧠 <strong style="color:var(--guru-300)">{brain_count}</strong> en Pipeline <strong>Brain</strong> ·
      💼 <strong style="color:var(--guru-300)">{ventas_count}</strong> en <strong>ventas normales</strong></div>
    <input type="text" id="emp-search" onkeyup="filtrarEmpresas()" placeholder="🔍 Buscar empresa…"
      style="width:100%;padding:10px 14px;border-radius:8px;border:1px solid var(--border);background:var(--surface);color:var(--text);font-size:14px;margin-bottom:14px;outline:none;">
    <table class="table" id="emp-table"><thead><tr><th>Empresa</th><th>Canal</th><th>Etapa / estado</th><th>📅 Última reunión</th><th>Razón de descarte</th></tr></thead>
    <tbody>{deal_rows}</tbody></table>
    <div id="emp-empty" style="display:none;padding:14px 0;font-size:13px;color:var(--muted);text-align:center;">Sin resultados</div>
    <div class="alert alert-muted"><span>ℹ️</span><div>Solo oportunidades <strong>activas</strong> cuyo contacto entró por canal de marketing, por etapa del pipeline (Discovery → Demo → Best Case). Cada fila muestra empresa, canal y etapa/estado, <strong>ordenadas dentro de cada etapa por canal</strong>. La fecha es la <strong>última reunión</strong> (en <span class="dt-next">salmón</span> si es futura). Reparto por canal: {chan_dist_txt}.</div></div>
  </div>

  <div style="margin-top:40px;text-align:center;font-size:12px;color:var(--muted);">
    GuruSup · Dashboard Diario · generado el {generado} (hora España)
  </div>
</div>

<button class="refresh-fab" onclick="pedirActualizacion()" title="Forzar una actualización de los datos ahora">🔄 Actualizar datos</button>
<div id="refresh-toast" class="refresh-toast"></div>

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
window.pedirActualizacion=function(){{
  window.open('https://github.com/pilar-galan/gurusup-radar-ia/actions/workflows/refresh_dashboard.yml','_blank','noopener');
  var t=document.getElementById('refresh-toast');
  t.innerHTML='Se ha abierto <b>GitHub Actions</b> en otra pestaña. Pulsa <b>“Run workflow”</b> y, en ~1 minuto, vuelve aquí y recarga. <button class="rt-btn" onclick="location.reload()">Recargar ahora</button>';
  t.classList.add('show');
  setTimeout(function(){{ t.classList.remove('show'); }}, 15000);
}};
</script>
</body>
</html>"""


if __name__ == "__main__":
    main()
