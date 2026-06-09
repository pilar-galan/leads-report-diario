#!/usr/bin/env python3
import feedparser, requests, json, html, os, re
from datetime import datetime
from playwright.sync_api import sync_playwright

DISCORD_WEBHOOK = os.environ["DISCORD_WEBHOOK"]
ANTHROPIC_KEY   = os.environ.get("ANTHROPIC_API_KEY", "")

DAYS_ES   = ["Lunes","Martes","Miércoles","Jueves","Viernes","Sábado","Domingo"]
MONTHS_ES = ["enero","febrero","marzo","abril","mayo","junio","julio","agosto",
             "septiembre","octubre","noviembre","diciembre"]

QUERIES = [
    ("SECTOR",      "🥇", "AI agents customer support CX innovation 2026"),
    ("COMPETENCIA", "🥈", "Intercom Decagon Sierra Ada Fin AI customer support startup funding"),
    ("TENDENCIAS",  "🥉", "customer experience AI trends report 2026"),
]

def format_date_es():
    n = datetime.now()
    return f"{DAYS_ES[n.weekday()]}, {n.day} de {MONTHS_ES[n.month-1]} de {n.year}"

def fetch_top_article(query):
    try:
        url = f"https://news.google.com/rss/search?q={requests.utils.quote(query)}&hl=en&gl=US&ceid=US:en"
        feed = feedparser.parse(url)
        if feed.entries:
            e = feed.entries[0]
            title   = html.unescape(re.sub(r"\s+-\s+\S.*$", "", e.title))
            summary = html.unescape(re.sub("<[^>]+>", "", e.get("summary", "")))[:600]
            return {
                "title": title,
                "link": e.link,
                "source": e.get("source", {}).get("title", "Google News"),
                "summary": summary,
            }
    except Exception as err:
        print(f"  RSS error: {err}")
    return None

def analyze_with_claude(articles_raw):
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
        news_text = "\n\n".join(
            f"[{cat}]\nTítulo: {a['title']}\nFuente: {a['source']}\nResumen: {a['summary']}"
            for cat, _, a in articles_raw
        )
        prompt = f"""Eres el analista de GuruSup (startup española de AI agents para customer support,
compite con Decagon, Sierra, Ada, Intercom Fin; ICP: startups B2C Series A-C España/LATAM 5k-50k tickets/mes).
Genera el resumen diario EN ESPAÑOL. Responde ÚNICAMENTE con este JSON exacto sin texto adicional:
{{"SECTOR":{{"title":"titular potente en español máx 90 chars","paragraph":"2-3 frases, qué pasó y por qué importa, máx 4 líneas","kpis":["dato numérico impactante con contexto","dato numérico impactante con contexto","dato numérico impactante con contexto"],"recommendation":"1-2 frases: por qué le interesa a GuruSup y qué oportunidad/acción concreta tiene"}},"COMPETENCIA":{{"title":"...","paragraph":"...","kpis":["...","...","..."],"recommendation":"..."}},"TENDENCIAS":{{"title":"...","paragraph":"...","kpis":["...","...","..."],"recommendation":"..."}}}}
Noticias:\n{news_text}"""
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=2500,
            messages=[{"role": "user", "content": prompt}]
        )
        raw = re.sub(r"^```(?:json)?\s*\n?", "", resp.content[0].text.strip())
        raw = re.sub(r"\n?```\s*$", "", raw)
        result = json.loads(raw.strip())
        print(f"  Claude OK: {list(result.keys())}")
        return result
    except Exception as err:
        print(f"  Claude error: {err}")
        return {}

def esc(t):
    return str(t).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

def card_block(cat, medal, article, a):
    title = esc(a.get("title") or article["title"])
    para  = esc(a.get("paragraph") or article["summary"][:400])
    kpis  = a.get("kpis") or []
    rec   = esc(a.get("recommendation") or "")
    src   = esc(article["source"])
    link  = article["link"]

    kpi_rows = "".join(f"""
        <tr>
          <td width="16" valign="top" style="padding:5px 0;color:#FF6B5B;font-size:15px;font-weight:900;font-family:Arial;">&#x25CF;</td>
          <td style="padding:5px 0 5px 6px;font-size:15px;color:#0D1B2E;line-height:1.5;font-family:Arial,sans-serif;">{esc(k)}</td>
        </tr>""" for k in kpis)

    rec_block = f"""
        <tr><td colspan="2" style="border-top:1px solid #C8D0DA;padding-top:14px;">
          <table cellpadding="0" cellspacing="0" width="100%" style="background:#D6DCE4;border-radius:8px;">
            <tr><td style="padding:13px 16px;">
              <p style="margin:0 0 5px 0;font-size:12px;font-weight:700;color:#FF6B5B;letter-spacing:.05em;font-family:Arial,sans-serif;">&#x1F4A1;&nbsp; POR QU&#xC9; LE INTERESA A GURUSUP</p>
              <p style="margin:0;font-size:14px;color:#1A2B3C;line-height:1.65;font-family:Arial,sans-serif;">{rec}</p>
            </td></tr>
          </table>
        </td></tr>""" if rec else ""

    return f"""
    <tr><td style="padding-bottom:18px;">
      <table cellpadding="0" cellspacing="0" width="100%" style="background:#E8ECF0;border-radius:12px;border-left:5px solid #FF6B5B;">
        <tr><td style="padding:20px 22px 18px 22px;">
          <p style="margin:0 0 12px 0;">
            <span style="background:#FFFFFF;color:#0D1B2E;font-size:10px;font-weight:800;padding:4px 11px;border-radius:4px;letter-spacing:.12em;text-transform:uppercase;border:1px solid #C8D0DA;font-family:Arial,sans-serif;">{medal}&nbsp; {cat}</span>
          </p>
          <p style="margin:0 0 6px 0;font-family:Georgia,serif;font-size:22px;font-weight:bold;color:#0D1B2E;line-height:1.3;">{title}</p>
          <p style="margin:0 0 14px 0;font-size:12px;color:#556070;font-family:Arial,sans-serif;">&#x1F4F0;&nbsp; <strong style="color:#2D3E50;">{src}</strong></p>
          <p style="margin:0 0 16px 0;font-size:16px;color:#1A2B3C;line-height:1.7;font-family:Arial,sans-serif;">{para}</p>
          <table cellpadding="0" cellspacing="0" width="100%" style="margin-bottom:4px;">
            {kpi_rows}
            {rec_block}
          </table>
        </td></tr>
      </table>
    </td></tr>"""

def generate_html(today, articles_raw, analysis):
    blocks = "".join(
        card_block(cat, medal, article, analysis.get(cat, {}))
        for cat, medal, article in articles_raw
    )
    return f"""<!DOCTYPE html>
<html lang="es">
<head><meta charset="UTF-8"></head>
<body style="margin:0;padding:0;background:#0A0E1A;">
<table cellpadding="0" cellspacing="0" width="100%" style="background:#0A0E1A;">
<tr><td align="center" style="padding:24px 16px;">
  <table cellpadding="0" cellspacing="0" width="660" style="max-width:660px;">

    <!-- BANNER -->
    <tr><td style="background:#0D1117;border-radius:12px 12px 0 0;padding:28px 30px 24px;border-bottom:3px solid #FF6B5B;">
      <table cellpadding="0" cellspacing="0" width="100%"><tr>
        <td valign="middle">
          <p style="margin:0 0 5px 0;color:#555E6E;font-size:10px;font-weight:700;letter-spacing:.18em;text-transform:uppercase;font-family:Arial,sans-serif;">Radar IA &nbsp;&#xB7;&nbsp; CX &nbsp;&#xB7;&nbsp; ATC</p>
          <p style="margin:0 0 6px 0;color:#FF6B5B;font-size:40px;font-family:Georgia,serif;font-style:italic;font-weight:bold;line-height:1;">GuruSup</p>
          <p style="margin:0;color:#8B949E;font-size:13px;font-family:Arial,sans-serif;">{esc(today)}</p>
        </td>
        <td align="right" valign="middle" style="padding-left:20px;">
          <div style="background:#FFFFFF;color:#0D1B2E;font-size:12px;font-weight:700;padding:12px 20px;border-radius:24px;font-family:Arial,sans-serif;line-height:1.45;text-align:center;white-space:nowrap;">&#x1F525; Lo que no te<br>puedes perder hoy</div>
        </td>
      </tr></table>
    </td></tr>

    <!-- CONTENIDO -->
    <tr><td style="background:#0F1420;border-radius:0 0 12px 12px;padding:20px 20px 4px;">
      <table cellpadding="0" cellspacing="0" width="100%">
        {blocks}
      </table>
    </td></tr>

    <!-- FOOTER -->
    <tr><td style="padding:14px 0 6px;text-align:center;">
      <p style="margin:0;font-size:11px;color:#2D3748;font-family:Arial,sans-serif;">GuruSup Radar IA &nbsp;&#xB7;&nbsp; generado autom&#xE1;ticamente &nbsp;&#xB7;&nbsp; {esc(today)}</p>
    </td></tr>

  </table>
</td></tr>
</table>
</body>
</html>"""

def take_screenshot(html_content, out="/tmp/radar.png"):
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 720, "height": 900}, device_scale_factor=2)
        page.set_content(html_content, wait_until="networkidle")
        page.screenshot(path=out, full_page=True)
        browser.close()
    print(f"  Imagen OK: {out}")

def send_to_discord(image_path):
    with open(image_path, "rb") as f:
        r = requests.post(
            DISCORD_WEBHOOK,
            files={"file": ("radar.png", f, "image/png")},
            data={"payload_json": json.dumps({"content": ""})}
        )
    print("  Discord OK" if r.status_code in (200, 204) else f"  Discord error {r.status_code}: {r.text}")

def main():
    today = format_date_es()
    print(f"GuruSup Radar IA — {today}")
    articles_raw = []
    for cat, medal, query in QUERIES:
        article = fetch_top_article(query)
        if article:
            articles_raw.append((cat, medal, article))
            print(f"  {cat}: {article['title'][:60]}...")
    if not articles_raw:
        print("Sin noticias."); return
    analysis     = analyze_with_claude(articles_raw) if ANTHROPIC_KEY else {}
    html_content = generate_html(today, articles_raw, analysis)
    take_screenshot(html_content)
    send_to_discord("/tmp/radar.png")

if __name__ == "__main__":
    main()
