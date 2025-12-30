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
    if pd.isna(v):
        return "—"
    try:
        v = float(v)
        return f"{int(v):,}€".replace(",", ".")
    except Exception:
        return str(v)

def _build_opportunity_message(row: pd.Series, avg_market: float, profit: float, count: int) -> str:
    title      = str(row.get("title", "Sem título"))
    price      = row.get("price")
    url        = str(row.get("url", ""))
    src        = str(row.get("source", ""))
    km         = row.get("km")
    km_txt     = "—" if pd.isna(km) else f"{int(float(km)):,} km".replace(",", ".")
    
    roi = (profit / price) * 100 if price > 0 else 0

    return (
        f"💎 *OPORTUNIDADE DE REVENDA* ({src.upper()})\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🚗 *{title}*\n"
        f"📍 KM: {km_txt}\n\n"
        f"💰 *Preço Atual:* {_fmt_currency(price)}\n"
        f"📊 *Média de Mercado:* {_fmt_currency(avg_market)}\n"
        f"✅ *Podes ganhar:* {_fmt_currency(profit)}\n"
        f"💡 *Baseado em:* {count} anúncios ativos\n"
        f"📈 *ROI Estimado:* {int(roi)}%\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🔗 [Ver Negócio Agora]({url})"
    )

def _send_telegram(token: str, chat_id: str, text: str) -> None:
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown", "disable_web_page_preview": False},
            timeout=10
        )
        if r.status_code != 200:
            log.error("Telegram falhou: %s %s", r.status_code, r.text)
    except Exception as e:
        log.error("Erro no Telegram: %s", e)

# ---------------------------------------------------------------------------
# Função Principal de Alertas
# ---------------------------------------------------------------------------
def send_alerts(df_new: pd.DataFrame, df_all: pd.DataFrame, cfg: Dict[str, object]) -> None:
    token = os.environ.get("TELEGRAM_TOKEN") or str(cfg.get("TELEGRAM_TOKEN") or "")
    chat  = os.environ.get("TELEGRAM_CHAT_ID") or str(cfg.get("TELEGRAM_CHAT_ID") or "")

    if not token or not chat or df_new is None or df_new.empty:
        return

    # Margem definida no config (ex: 0.15 = 15% abaixo da média)
    min_margin = float(cfg.get("ALERT_MARGIN", 0.15))

    for _, row in df_new.iterrows():
        current_price = row.get("price")
        if pd.isna(current_price) or current_price <= 0:
            continue

        # Calculamos a média e a contagem de anúncios no histórico total (df_all)
        # Filtramos preços válidos para não corromper a média
        valid_ads = df_all[df_all["price"] > 0]
        avg_market = valid_ads["price"].mean()
        ads_count = len(valid_ads)

        if pd.isna(avg_market) or ads_count == 0:
            continue

        # Cálculo do Lucro Potencial
        potential_profit = avg_market - current_price

        # Condição: Só avisa se o preço for inferior à média menos a margem
        if current_price <= (avg_market * (1 - min_margin)):
            msg = _build_opportunity_message(row, avg_market, potential_profit, ads_count)
            _send_telegram(token, chat, msg)
            log.info(f"Sucesso: Oportunidade enviada para {row.get('title')}")
