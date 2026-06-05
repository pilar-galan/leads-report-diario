#!/usr/bin/env python3
"""
GuruSup Radar IA — Daily Discord image digest
Generates a pixel-perfect image of the approved mockup and sends it to Discord.
"""
import feedparser, requests, json, html, os, re
from datetime import datetime
from playwright.sync_api import sync_playwright

DISCORD_WEBHOOK = os.environ["DISCORD_WEBHOOK"]
ANTHROPIC_KEY   = os.environ.get("ANTHROPIC_API_KEY", "")

DAYS_ES   = ["Lunes","Martes","Miércoles","Jueves","Viernes","Sábado","Domingo"]
MONTHS_ES = ["enero","febrero","marzo","abril","mayo","junio",
             "julio","agosto","septiembre","octubre","noviembre","diciembre"]

QUERIES = [
    ("SECTOR",      "🥇", "AI agents customer support CX innovation 2026"),
    ("COMPETENCIA", "🥈", "Intercom Decagon Sierra Ada Fin Zendesk AI customer support startup funding"),
    ("TENDENCIAS",  "🥉", "customer experience artificial intelligence trends report 2026"),
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
            return {"title": title, "link": e.link,
                    "source": e.get("source", {}).get("title", "Google News"), "summary": summary}
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
        prompt = f"""Eres el analista de inteligencia de mercado de GuruSup (startup española de AI agents para customer support, compite con Decagon, Sierra, Ada, Intercom Fin; ICP: startups B2C Series A-C en España/LATAM, 5k-50k tickets/mes).

Genera el contenido del resumen diario EN ESPAÑOL para las 3 noticias.
Responde ÚNICAMENTE con este JSON exacto (sin texto antes ni después, sin bloques de código):

{{"SECTOR":{{"title":"título potente en español máx 90 chars","paragraph":"2-3 frases concisas en español","kpis":["primer KPI o dato clave","segundo KPI o dato clave","tercer KPI o dato clave"],"recommendation":"1 frase sobre riesgo, oportunidad o diferenciación para GuruSup"}},"COMPETENCIA":{{"title":"...","paragraph":"...","kpis":["...","...","..."],"recommendation":"..."}},"TENDENCIAS":{{"title":"...","paragraph":"...","kpis":["...","...","..."],"recommendation":"..."}}}}

Noticias:
{news_text}"""

        resp = client.messages.create(
            model="claude-haiku-4-5-20251001", max_tokens=2500,
            messages=[{"role": "user", "content": prompt}]
        )
        raw = re.sub(r"^```(?:json)?\s*\n?", "", resp.content[0].text.strip())
        raw = re.sub(r"\n?```\s*$", "", raw)
        result = json.loads(raw.strip())
        print(f"  ✓ Claude OK — claves: {list(result.keys())}")
        return result
    except Exception as err:
        print(f"  ✗ Claude error: {type(err).__name__}: {err}")
        return {}

def escape(text):
    return (str(text)
            .replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))

def generate_html(today, articles_raw, analysis):
    medals = {"SECTOR": "🥇", "COMPETENCIA": "🥈", "TENDENCIAS": "🥉"}
    cards_html = ""

    for cat, _, article in articles_raw:
        a     = analysis.get(cat, {})
        medal = medals[cat]
        title = escape(a.get("title") or article["title"])
        para  = escape(a.get("paragraph") or article["summary"][:300])
        kpis  = a.get("kpis") or []
        rec   = escape(a.get("recommendation") or "")
        src   = escape(article["source"])
        link  = article["link"]

        kpi_html = "".join(
            f'<div class="kpi">📊&nbsp; <strong>{escape(k)}</strong></div>'
            for k in kpis
        )
        rec_html = f'<div class="rec">💡 <strong>GuruSup:</strong> {rec}</div>' if rec else ""

        cards_html += f"""
        <div class="card">
          <div class="card-body">
            <span class="tag">{cat}</span>
            <div class="news-title">{medal}&nbsp; {title}</div>
            <div class="para">{para}</div>
            <div class="kpis">{kpi_html}</div>
          </div>
          {rec_html}
          <div class="src">Fuente: <a href="{link}">{src}</a></div>
        </div>"""

    return f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8">
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:Helvetica,Arial,sans-serif;background:#2B2D31;padding:16px;width:700px}}
.wrapper{{background:#1A1D28;border-radius:10px;overflow:hidden}}
.banner{{padding:18px 24px 16px;display:flex;justify-content:space-between;align-items:center;border-bottom:1px solid #252836;gap:16px}}
.bl .label{{color:#fff;font-size:13px;font-weight:300;letter-spacing:.08em;text-transform:uppercase}}
.bl .brand{{color:#FF6B5B;font-size:22px;font-family:Georgia,"Times New Roman",serif;font-style:italic;margin:3px 0 4px}}
.bl .date{{color:#AEAEAE;font-size:13px}}
.bubble{{background:#fff;border-radius:12px 12px 3px 12px;padding:10px 15px;font-size:13px;color:#171717;white-space:nowrap;flex-shrink:0}}
.cards{{padding:10px}}
.card{{background:#fff;border-radius:8px;border-left:4px solid #FF6B5B;margin-bottom:8px;overflow:hidden}}
.card:last-child{{margin-bottom:0}}
.card-body{{padding:13px 15px 10px}}
.tag{{display:inline-block;background:#171717;color:#fff;font-size:11px;font-weight:700;padding:4px 10px;border-radius:3px;letter-spacing:.06em;text-transform:uppercase;margin-bottom:12px}}
.news-title{{font-family:Georgia,"Times New Roman",serif;font-size:17px;font-weight:bold;color:#0D0D0D;line-height:1.4;margin-bottom:14px}}
.para{{font-size:14px;color:#4b5563;line-height:1.65;margin-bottom:10px}}
.kpis{{margin-bottom:4px}}
.kpi{{font-size:14px;color:#4b5563;line-height:1.9}}
.kpi strong{{color:#FF6B5B}}
.rec{{background:#FAE5DC;padding:10px 15px;font-size:13px;color:#171717;font-style:italic;line-height:1.55}}
.src{{padding:7px 15px 10px;font-size:12px;color:#9ca3af}}
.src a{{color:#FF6B5B;text-decoration:none}}
</style></head>
<body><div class="wrapper">
  <div class="banner">
    <div class="bl">
      <div class="label">Radar IA / CX / ATC</div>
      <div class="brand">GuruSup</div>
      <div class="date">{escape(today)}</div>
    </div>
    <div class="bubble">Lo que no te puedes perder hoy!</div>
  </div>
  <div class="cards">{cards_html}</div>
</div></body></html>"""

def take_screenshot(html_content, output_path="/tmp/radar.png"):
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 700, "height": 800}, device_scale_factor=2)
        page.set_content(html_content, wait_until="networkidle")
        page.screenshot(path=output_path, full_page=True)
        browser.close()
    print(f"  ✓ Imagen generada: {output_path}")

def send_to_discord(image_path):
    with open(image_path, "rb") as f:
        r = requests.post(
            DISCORD_WEBHOOK,
            files={"file": ("radar_ia.png", f, "image/png")},
            data={"payload_json": json.dumps({"content": ""})}
        )
    if r.status_code in (200, 204):
        print("  ✅ Enviado correctamente a Discord")
    else:
        print(f"  ❌ Error Discord {r.status_code}: {r.text}")

def main():
    today = format_date_es()
    print(f"\n{'='*50}\nGuruSup Radar IA — {today}\n{'='*50}")

    print("\n[1/4] Buscando noticias...")
    articles_raw = []
    for cat, medal, query in QUERIES:
        article = fetch_top_article(query)
        if article:
            articles_raw.append((cat, medal, article))
            print(f"  ✓ {cat}: {article['title'][:70]}…")
        else:
            print(f"  ✗ {cat}: sin resultados")

    if not articles_raw:
        print("  Sin noticias — abortando."); return

    print("\n[2/4] Analizando con Claude...")
    analysis = analyze_with_claude(articles_raw) if ANTHROPIC_KEY else {}
    if not analysis:
        print("  ⚠️  Sin análisis Claude — usando datos RSS básicos")

    print("\n[3/4] Generando imagen...")
    html_content = generate_html(today, articles_raw, analysis)
    take_screenshot(html_content)

    print("\n[4/4] Enviando a Discord...")
    send_to_discord("/tmp/radar.png")

if __name__ == "__main__":
    main()
