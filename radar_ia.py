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
        url = (
            "https://news.google.com/rss/search"
            f"?q={requests.utils.quote(query)}&hl=en&gl=US&ceid=US:en"
        )
        feed = feedparser.parse(url)
        if feed.entries:
            e = feed.entries[0]
            title   = html.unescape(re.sub(r"\s+-\s+\S.*$", "", e.title))
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

def parse_json_safe(text):
    """Extract JSON from Claude response, handling markdown code blocks."""
    text = text.strip()
    # Remove ```json ... ``` or ``` ... ``` wrappers
    text = re.sub(r"^```(?:json)?\s*\n?", "", text)
    text = re.sub(r"\n?```\s*$", "", text)
    return json.loads(text.strip())

def analyze_with_claude(articles_raw):
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)

        news_text = "\n\n".join(
            f"[{cat}]\nTítulo: {a['title']}\nFuente: {a['source']}\nResumen: {a['summary']}"
            for cat, _, a in articles_raw
        )

        prompt = f"""Eres el analista de inteligencia de mercado de GuruSup, startup española de AI agents para customer support.
GuruSup compite con Decagon, Sierra, Ada e Intercom Fin. Su cliente ideal (ICP) son startups B2C en hipercrecimiento (Series A-C, España/LATAM, 5k-50k tickets/mes).

Para cada una de las 3 noticias, genera el contenido del resumen diario en ESPAÑOL.
Responde ÚNICAMENTE con el siguiente JSON (sin texto antes ni después, sin bloques de código markdown):

{{
  "SECTOR": {{
    "title": "título descriptivo y potente en español, máximo 90 caracteres",
    "paragraph": "2-3 frases en español resumiendo la noticia de forma concisa y directa",
    "kpis": ["primer dato o métrica clave", "segundo dato o métrica clave", "tercer dato o métrica clave"],
    "recommendation": "una frase en español sobre el riesgo, oportunidad o diferenciación para GuruSup"
  }},
  "COMPETENCIA": {{
    "title": "...",
    "paragraph": "...",
    "kpis": ["...", "...", "..."],
    "recommendation": "..."
  }},
  "TENDENCIAS": {{
    "title": "...",
    "paragraph": "...",
    "kpis": ["...", "...", "..."],
    "recommendation": "..."
  }}
}}

Noticias de hoy:
{news_text}"""

        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=2500,
            messages=[{"role": "user", "content": prompt}],
        )

        raw = resp.content[0].text
        print(f"  Claude raw response (first 200 chars): {raw[:200]}")

        result = parse_json_safe(raw)
        print(f"  ✓ Claude analysis OK — keys: {list(result.keys())}")
        return result

    except json.JSONDecodeError as err:
        print(f"  ✗ JSON parse error: {err}")
        print(f"  Full Claude response: {resp.content[0].text[:1000]}")
        return {}
    except Exception as err:
        print(f"  ✗ Claude error: {type(err).__name__}: {err}")
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
        a     = analysis.get(cat, {})
        medal = medals[cat]

        title = a.get("title") or article["title"]
        para  = a.get("paragraph") or article["summary"][:300]
        kpis  = a.get("kpis") or []
        rec   = a.get("recommendation") or ""

        kpi_block = "\n".join(f"📊  {k}" for k in kpis) if kpis else ""
        rec_block = f"\n\n> 💡 **GuruSup:** {rec}" if rec else ""
        description = f"{para}\n\n{kpi_block}{rec_block}".strip()

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
    print(f"\n{'='*50}")
    print(f"GuruSup Radar IA — {today}")
    print(f"{'='*50}")

    print(f"\n[1/3] Buscando noticias...")
    articles_raw = []
    for cat, medal, query in QUERIES:
        article = fetch_top_article(query)
        if article:
            articles_raw.append((cat, medal, article))
            print(f"  ✓ {cat}: {article['title'][:70]}…")
        else:
            print(f"  ✗ {cat}: sin resultados")

    if not articles_raw:
        print("  Sin noticias — abortando.")
        return

    print(f"\n[2/3] Analizando con Claude...")
    analysis = {}
    if ANTHROPIC_KEY:
        analysis = analyze_with_claude(articles_raw)
        if not analysis:
            print("  ⚠️  Claude falló — enviando con datos RSS básicos")
    else:
        print("  ⚠️  Sin ANTHROPIC_API_KEY — usando datos RSS sin análisis")

    print(f"\n[3/3] Enviando a Discord...")
    embeds = build_embeds(articles_raw, analysis, today)
    r = requests.post(DISCORD_WEBHOOK, json={"embeds": embeds})

    if r.status_code == 204:
        print("  ✅ Enviado correctamente")
    else:
        print(f"  ❌ Error {r.status_code}: {r.text}")

if __name__ == "__main__":
    main()
