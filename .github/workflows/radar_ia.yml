name: GuruSup Radar IA

on:
  schedule:
    - cron: '0 7 * * *'
  workflow_dispatch:

jobs:
  radar:
    runs-on: ubuntu-latest

    steps:
      - name: Checkout repo
        uses: actions/checkout@v4

      - name: Python 3.11
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Instalar dependencias Python
        run: pip install -r requirements.txt

      - name: Instalar Chromium para Playwright
        run: playwright install --with-deps chromium

      - name: Ejecutar Radar IA
        env:
          DISCORD_WEBHOOK:   ${{ secrets.DISCORD_WEBHOOK }}
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
        run: python radar_ia.py
