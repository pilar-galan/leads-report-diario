#!/usr/bin/env python3
"""
GuruSup Radar IA — Daily Discord news digest
Runs via GitHub Actions every morning at 9h Spain time
"""
import feedparser
import requests
import json
import html
import os
import re
from datetime import datetime

DISCORD_WEBHOOK = os.environ["DISCORD_WEBHOOK"]
ANTHROPIC_KEY   = os.environ.get("ANTHROPIC_API_KEY", "")

DAYS_ES   = ["Lunes","Martes","Miércoles","Jueves","Viernes","Sábado","Domingo"]
MONTHS_ES = ["enero","febrero","marzo","abril","mayo","junio",
             "julio","agosto","septiembre","octubre","noviembre","diciembre"]

# One search query per category — tune these if needed
QUERIES = [
    ("SECTOR",      "🥇", "AI agents customer support CX innovation 2026"),
    ("COMPETENCIA", "🥈", "Intercom Decagon Sierra Ada Fin Zendesk AI customer support startup"),
    ("TENDENCIAS",  "🥉", "customer experience artificial intelligence trends report 2026"),
]

def format_date_es():
    n = datetime.now()
    return f"{DAYS_ES[n.weekday()]}, {n.day} de {MONTHS_ES[n.month-1]} de {n.year}"

def fetch_top_article(query):
    try:
        url = (
            "https://news.google.com/rss/search"
            f"?q={requests.utils.quote(query)}&hl=en&gl=US&ceid=US:en"
        )
        feed = feedparser.parse(url)
        if feed.entries:
            e = feed.entries[0]
            # Strip trailing " - Source Name" from title
            title = html.unescape(re.sub(r"\s+-\s+\S.*$", "", e.title))
            summary = html.unescape(re.sub("<[^>]+>", "", e.get("summary", "")))[:600]
            return {
                "title":   title,
                "link":    e.link,
                "source":  e.get("source", {}).get("title", "Google News"),
                "summary": summary,
            }
    except Exception as err:
        print(f"  RSS error for '{query}': {err}")
    return None

def analyze_with_claude(articles_raw):
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)

        news_text = "\n\n".join(
            f"[{cat}]\nTítulo: {a['title']}\nFuente: {a['source']}\nResumen: {a['summary']}"
            for cat, _, a in articles_raw
        )

        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=2000,
            messages=[{
                "role": "user",
                "content": (
                    "Eres el analista de inteligencia de mercado de GuruSup "
                    "(startup española de AI agents para customer support; "
                    "compite con Decagon, Sierra, Ada, Intercom Fin; "
                    "ICP: startups B2C Series A-C en España/LATAM con 5k-50k tickets/mes).\n\n"
                    "Para cada noticia genera contenido para un canal de Discord. "
                    "Devuelve SOLO este JSON sin texto adicional:\n"
                    "{\n"
                    '  "SECTOR":      { "title": "max 90 chars", "paragraph": "2-3 frases", '
                    '"kpis": ["dato 1","dato 2","dato 3"], "recommendation": "1 frase" },\n'
                    '  "COMPETENCIA": { igual },\n'
                    '  "TENDENCIAS":  { igual }\n'
                    "}\n\n"
                    f"Noticias de hoy:\n{news_text}"
                ),
            }],
        )
        return json.loads(resp.content[0].text)
    except Exception as err:
        print(f"  Claude error: {err}")
        return {}

def build_embeds(articles_raw, analysis, today):
    embeds = [{
        "color": 1711400,
        "description": (
            f"**RADAR IA  ·  CX  ·  ATC**\n"
            f"# *GuruSup*\n"
            f"{today}  ·  *Lo que no te puedes perder hoy!*"
        ),
    }]

    medals = {"SECTOR": "🥇", "COMPETENCIA": "🥈", "TENDENCIAS": "🥉"}

    for cat, _, article in articles_raw:
        a      = analysis.get(cat, {})
        medal  = medals[cat]
        title  = a.get("title", article["title"])
        para   = a.get("paragraph", article["summary"][:300])
        kpis   = a.get("kpis", [])
        rec    = a.get("recommendation", "")

        kpi_block = "\n".join(f"📊  {k}" for k in kpis)
        rec_block  = f"\n\n> 💡 **GuruSup:** {rec}" if rec else ""
        description = f"{para}\n\n{kpi_block}{rec_block}"

        embeds.append({
            "color":       16739163,
            "author":      {"name": f"▌ {cat}"},
            "title":       f"{medal}  {title}",
            "description": description,
            "url":         article["link"],
            "footer":      {"text": f"Fuente: {article['source']}"},
        })

    return embeds

def main():
    today = format_date_es()
    print(f"GuruSup Radar IA — {today}")

    articles_raw = []
    for cat, medal, query in QUERIES:
        article = fetch_top_article(query)
        if article:
            articles_raw.append((cat, medal, article))
            print(f"  ✓ {cat}: {article['title'][:70]}…")
        else:
            print(f"  ✗ {cat}: no article found")

    if not articles_raw:
        print("No articles found — aborting.")
        return

    analysis = {}
    if ANTHROPIC_KEY:
        print("Analizando con Claude Haiku…")
        analysis = analyze_with_claude(articles_raw)
    else:
        print("Sin ANTHROPIC_API_KEY — usando datos RSS directos.")

    embeds = build_embeds(articles_raw, analysis, today)

    print("Enviando a Discord…")
    r = requests.post(DISCORD_WEBHOOK, json={"embeds": embeds})
    if r.status_code == 204:
        print("✅ Enviado correctamente")
    else:
        print(f"❌ Error {r.status_code}: {r.text}")

if __name__ == "__main__":
    main()
