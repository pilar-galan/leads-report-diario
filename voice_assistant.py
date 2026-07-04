#!/usr/bin/env python3
"""
GuruSup · Asistente de Voz IA
Servidor local que recibe peticiones de voz transcritas,
las procesa con Claude y devuelve la respuesta.

Uso: python voice_assistant.py
Abre en el navegador: http://localhost:5050
"""
import os, json
from flask import Flask, request, jsonify, send_from_directory
import anthropic

app = Flask(__name__, static_folder=".")

ANTHROPIC_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)

# ── Contexto de GuruSup con datos reales de HubSpot ──────────────────────────
SYSTEM_PROMPT = """Eres el asistente de IA comercial de GuruSup, una startup española de AI agents para customer support.

CONTEXTO DE NEGOCIO:
- Competidores: Decagon, Sierra, Ada, Intercom Fin
- ICP: startups B2C Series A-C, España/LATAM, 5k-50k tickets/mes
- Modelo: Consultoría + Freemium que convierte a pago

DATOS ACTUALES DEL CRM (HubSpot · 14 Jun 2026):
- Base de datos: 9.120 contactos totales
- Nuevos contactos esta semana: 97
  · Leads: 79 (18 no cualificados, 15 open activos, 5 en contacto)
  · Opportunities: 3
  · Clientes nuevos: 10
- Canales: Offline 53%, Tráfico Directo 22%, Orgánico SEO 13.5%, Paid Search 7.5%, AI Referrals 2%

PIPELINE ACTIVO:
- 89 deals abiertos · ~€53.000 en juego
- SQL Consultoría: 3 deals activos (Flywire, eboca, ZZ Test)
- SQL Freemium: 5 deals (Cooltra €10k, GoTrendier €2k, Rever, TeamSystem, COCUNAT)
- Presentaciones agendadas: 13 deals · €16.400
- Deals con fecha vencida urgentes: Waynabox €13.2k, Cooltra €10k, Redexis €5k, Plenergy €3k

FREEMIUMS:
- 41 deals en pipeline freemium · €51.625 en juego
- 3 ganados: TBF Abogados, VDS (€5k), PropHero
- 2 nuevos sin contactar esta semana: Planeta Huerto, Avantio
- Tasa conversión freemium → cliente: 7.3%

EMAIL Y ACTIVACIÓN:
- Tasa apertura email: 3% (muy baja)
- 63.5% contactos no marketable (sin permiso email)
- 0 contactos en secuencia automática de bienvenida

REVENUE:
- Mejor mes: Marzo 2026 · €18.850
- Tasa de cierre histórica: 4% (121 perdidos vs 5 ganados)
- Ticket medio: €1.150

CLIENTES ACTUALES:
- 95 clientes en total
- Canal offline genera el 100% de los cierres

Responde siempre en español, de forma directa, concisa y orientada a la acción.
Si te preguntan por datos específicos del CRM, usa los datos de contexto anteriores.
Si te piden hacer algo (generar un email, crear una propuesta, analizar un deal), hazlo.
Máximo 3-4 párrafos en respuestas largas. Usa listas cuando ayude a la claridad.
"""

# ── Historial de conversación en memoria ──────────────────────────────────────
conversation_history = []

@app.route("/")
def index():
    return send_from_directory(".", "voz.html")

@app.route("/ask", methods=["POST"])
def ask():
    global conversation_history
    data = request.json
    text = data.get("text", "").strip()
    reset = data.get("reset", False)

    if reset:
        conversation_history = []
        return jsonify({"response": "Conversación reiniciada. ¿En qué te ayudo?"})

    if not text:
        return jsonify({"error": "Sin texto"}), 400

    if not ANTHROPIC_KEY:
        return jsonify({"error": "ANTHROPIC_API_KEY no configurada. Añádela como variable de entorno."}), 500

    # Añadir mensaje del usuario al historial
    conversation_history.append({"role": "user", "content": text})

    try:
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            messages=conversation_history
        )
        answer = response.content[0].text
        # Añadir respuesta al historial
        conversation_history.append({"role": "assistant", "content": answer})
        # Limitar historial a últimos 20 mensajes
        if len(conversation_history) > 20:
            conversation_history = conversation_history[-20:]
        return jsonify({"response": answer})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/status")
def status():
    return jsonify({
        "ok": True,
        "api_key": bool(ANTHROPIC_KEY),
        "messages": len(conversation_history)
    })

if __name__ == "__main__":
    print("\n" + "═"*50)
    print("  GuruSup · Asistente de Voz IA")
    print("═"*50)
    if not ANTHROPIC_KEY:
        print("  ⚠️  Falta ANTHROPIC_API_KEY")
        print("  Ejecuta: export ANTHROPIC_API_KEY=sk-ant-...")
    else:
        print("  ✅ API Key configurada")
    print("  🌐 Abre: http://localhost:5050")
    print("═"*50 + "\n")
    app.run(host="0.0.0.0", port=5050, debug=False)
