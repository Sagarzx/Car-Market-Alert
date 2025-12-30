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
        return f"€{int(v):,}".replace(",", ".")
    except Exception:
        return str(v)

def _build_message(row: pd.Series, prefix: str = "📣 *Novo anúncio*") -> str:
    title  = str(row.get("title", "Sem título"))
    price  = _fmt_currency(row.get("price"))
    km     = row.get("km")
    km_txt = "—" if pd.isna(km) else f"{int(float(km)):,} km".replace(",", ".")
    url    = str(row.get("url", ""))
    src    = str(row.get("source", ""))
    
    return (
        f"{prefix} ({src.upper()})\n"
        f"• {title}\n"
        f"• Preço: {price}\n"
        f"• KM: {km_txt}\n"
        f"{url}"
    )

def _send_telegram(token: str, chat_id: str, text: str) -> None:
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"},
            timeout=10
        )
        if r.status_code != 200:
            log.error("Telegram falhou: %s %s", r.status_code, r.text)
        else:
            log.info("Mensagem enviada para Telegram.")
    except Exception as e:
        log.error("Erro na conexão com Telegram: %s", e)

# ---------------------------------------------------------------------------
# Lógica de Oportunidade (Preço abaixo da média de mercado)
# ---------------------------------------------------------------------------
def _market_opportunity_alerts(df_new: pd.DataFrame, df_all: pd.DataFrame, cfg: Dict[str, object]) -> pd.DataFrame:
    """
    Identifica anúncios onde o preço está significativamente abaixo da média do histórico.
    """
    if df_new is None or df_new.empty or df_all is None or df_all.empty:
        return pd.DataFrame()

    # Calculamos a média de preço no histórico total
    avg_market = df_all["price"].mean()
    margin = float(cfg.get("ALERT_MARGIN", 0.15)) # Ex: 0.15 = 15% abaixo da média

    if pd.isna(avg_market) or avg_market <= 0:
        return pd.DataFrame()

    threshold = avg_market * (1 - margin)
    
    # Filtramos apenas os novos que estão abaixo do threshold
    ops = df_new[df_new["price"] <= threshold].copy()
    ops["market_avg_ref"] = avg_market
    
    return ops

# ---------------------------------------------------------------------------
# Lógica de Queda de Preço (Anúncios já conhecidos que baixaram)
# ---------------------------------------------------------------------------
def _basic_drop_alerts(df_new: pd.DataFrame, df_all: pd.DataFrame, cfg: Dict[str, object]) -> pd.DataFrame:
    """
    Deteta quedas de preço face à última observação do mesmo anúncio (mesmo id).
    """
    if df_new is None or df_new.empty or df_all is None or df_all.empty:
        return pd.DataFrame()

    # Pegar último preço conhecido por id no histórico (antes de este run ser somado)
    hist_last = (
        df_all.sort_values("ts")
              .drop_duplicates(subset=["id"], keep="last")
              [["id", "price"]]
              .rename(columns={"price": "price_prev"})
    )
    
    merged = df_new.merge(hist_last, on="id", how="left")

    pct = float(cfg.get("DROP_THRESHOLD_PCT", 0.05))
    abs_val = float(cfg.get("DROP_THRESHOLD_ABS", 250.0))

    def _is_drop(row):
        p = row.get("price")
        q = row.get("price_prev")
        if pd.isna(p) or pd.isna(q):
            return False
        dp = float(q) - float(p)
        if dp <= 0: 
            return False
        cond_pct = (dp / max(float(q), 1.0)) >= pct
        cond_abs = dp >= abs_val
        return cond_pct or cond_abs

    alerts = merged[merged.apply(_is_drop, axis=1)].copy()
    return alerts

# ---------------------------------------------------------------------------
# Função Principal de Alertas
# ---------------------------------------------------------------------------
def send_alerts(df_new: pd.DataFrame, df_all: pd.DataFrame, cfg: Dict[str, object]) -> None:
    token = os.environ.get("TELEGRAM_TOKEN") or str(cfg.get("TELEGRAM_TOKEN") or "")
    chat  = os.environ.get("TELEGRAM_CHAT_ID") or str(cfg.get("TELEGRAM_
