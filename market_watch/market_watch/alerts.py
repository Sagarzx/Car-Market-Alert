# market_watch/market_watch/alerts.py
# -*- coding: utf-8 -*-

import os
import logging
from typing import Dict
import pandas as pd
import requests

log = logging.getLogger("market_watch.alerts")

# ---------------------------------------------------------------------------
# Helpers de Formatação
# ---------------------------------------------------------------------------
def _fmt_currency(v):
    if pd.isna(v): return "—"
    try:
        v = float(v)
        return f"{int(v):,}€".replace(",", ".")
    except: return str(v)

def _build_opportunity_message(row: pd.Series, avg_market: float, profit: float, count: int) -> str:
    # Usamos Marca e Modelo se existirem, senão usamos o Título
    make  = row.get("make", "")
    model = row.get("model", "")
    vehicle_name = f"{make} {model}".strip() or row.get("title", "Sem título")
    
    price  = row.get("price")
    url    = row.get("url", "")
    src    = row.get("source", "").upper()
    km     = row.get("km")
    km_txt = "—" if pd.isna(km) else f"{int(float(km)):,} km".replace(",", ".")
    roi    = (profit / price) * 100 if price > 0 else 0

    return (
        f"💎 *OPORTUNIDADE DE REVENDA* ({src})\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🚗 *{vehicle_name}*\n"
        f"📝 {row.get('title')[:50]}...\n"
        f"📍 KM: {km_txt}\n\n"
        f"💰 *Compra:* {_fmt_currency(price)}\n"
        f"📊 *Valor de Mercado:* {_fmt_currency(avg_market)}\n"
        f"✅ *LUCRO ESTIMADO:* {_fmt_currency(profit)}\n"
        f"💡 *Amostra:* {count} anúncios iguais\n"
        f"📈 *ROI:* {int(roi)}%\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🔗 [Ver Anúncio]({url})"
    )

def _send_telegram(token: str, chat_id: str, text: str) -> None:
    try:
        requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"},
            timeout=10
        )
    except Exception as e:
        log.error("Erro Telegram: %s", e)

# ---------------------------------------------------------------------------
# Função Principal: Agrupamento Inteligente por Marca/Modelo
# ---------------------------------------------------------------------------
def send_alerts(df_new: pd.DataFrame, df_all: pd.DataFrame, cfg: Dict[str, object]) -> None:
    token = os.environ.get("TELEGRAM_TOKEN") or str(cfg.get("TELEGRAM_TOKEN") or "")
    chat  = os.environ.get("TELEGRAM_CHAT_ID") or str(cfg.get("TELEGRAM_CHAT_ID") or "")

    if not token or not chat or df_new is None or df_new.empty:
        return

    min_margin = float(cfg.get("ALERT_MARGIN", 0.15))

    for _, row in df_new.iterrows():
        current_price = row.get("price")
        make = row.get("make")
        model = row.get("model")

        if pd.isna(current_price) or not make or not model:
            continue

        # 1. Filtra histórico pelo mesmo MODELO e MARCA exatos
        # Isto garante que comparas um Golf com um Golf e não com um Passat
        model_history = df_all[(df_all['make'] == make) & (df_all['model'] == model)]
        
        # Precisamos de uma base mínima de 3 carros para a média ser justa
        if len(model_history) >= 3:
            avg_market = model_history["price"].mean()
            potential_profit = avg_market - current_price

            # 2. Se o preço for X% abaixo da média do modelo... ALERTA!
            if current_price <= (avg_market * (1 - min_margin)):
                msg = _build_opportunity_message(row, avg_market, potential_profit, len(model_history))
                _send_telegram(token, chat, msg)
