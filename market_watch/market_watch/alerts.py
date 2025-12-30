
# market_watch/market_watch/alerts.py
# -*- coding: utf-8 -*-

import os
import logging
from typing import Dict
import pandas as pd
import requests

log = logging.getLogger("market_watch.alerts")

def _fmt_currency(v):
    if pd.isna(v):
        return "—"
    try:
        v = float(v)
        return f"€{int(v):,}".replace(",", ".")
    except Exception:
        return str(v)

def _build_message(row: pd.Series) -> str:
    title  = str(row.get("title", "Sem título"))
    price  = _fmt_currency(row.get("price"))
    km     = row.get("km")
    km_txt = "—" if pd.isna(km) else f"{int(float(km)):,} km".replace(",", ".")
    url    = str(row.get("url", ""))
    src    = str(row.get("source", ""))
    return (
        f"📣 *Novo anúncio* ({src})\n"
        f"• {title}\n"
        f"• Preço: {price}\n"
        f"• KM: {km_txt}\n"
        f"{url}"
    )

def _send_telegram(token: str, chat_id: str, text: str) -> None:
    r = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
    )
    if r.status_code != 200:
        log.error("Telegram falhou: %s %s", r.status_code, r.text)
    else:
        log.info("Mensagem enviada para Telegram: %s", chat_id)

def _basic_drop_alerts(df_new: pd.DataFrame, df_all: pd.DataFrame, cfg: Dict[str, object]) -> pd.DataFrame:
    """
    Exemplo: detetar quedas de preço face à última observação do mesmo anúncio (mesmo id).
    Usa DROP_THRESHOLD_PCT e DROP_THRESHOLD_ABS.
    """
    if df_new is None or df_new.empty or df_all is None or df_all.empty:
        return pd.DataFrame(columns=df_new.columns)

    # Ordenar histórico por ts e pegar último preço conhecido por id
    hist_last = (
        df_all.sort_values("ts")
              .drop_duplicates(subset=["id"], keep="last")
              [["id", "price"]]
              .rename(columns={"price": "price_prev"})
    )
    merged = df_new.merge(hist_last, on="id", how="left")

    pct = float(cfg.get("DROP_THRESHOLD_PCT", 0.05))
    abs_ = float(cfg.get("DROP_THRESHOLD_ABS", 250.0))

    def _is_drop(row):
        p = row.get("price")
        q = row.get("price_prev")
        if pd.isna(p) or pd.isna(q):
            return False
        dp = float(q) - float(p)
        if dp < 0:  # subiu preço
            return False
        cond_pct = (dp / max(float(q), 1.0)) >= pct
        cond_abs = dp >= abs_
        return cond_pct or cond_abs

    alerts = merged[merged.apply(_is_drop, axis=1)].copy()
    return alerts

def send_alerts(df_new: pd.DataFrame, df_all: pd.DataFrame, cfg: Dict[str, object]) -> None:
    """
    Envia alertas para Telegram:
      - Novos anúncios (após filtros básicos já aplicados no main)
      - Quedas de preço (regra simples face ao último preço histórico por id)
    """
    token = os.environ.get("TELEGRAM_TOKEN") or str(cfg.get("TELEGRAM_TOKEN") or "")
    chat  = os.environ.get("TELEGRAM_CHAT_ID") or str(cfg.get("TELEGRAM_CHAT_ID") or "")

    if not token or not chat:
        log.warning("Sem TELEGRAM_TOKEN/TELEGRAM_CHAT_ID — não enviaremos alertas.")
        return

    # 1) Alertas de novos anúncios (todos os df_new filtrados)
    if df_new is not None and not df_new.empty:
        for _, row in df_new.iterrows():
            _send_telegram(token, chat, _build_message(row))

    # 2) Queda de preço face ao último preço histórico (por id)
    try:
        df_drop = _basic_drop_alerts(df_new, df_all, cfg)
        if df_drop is not None and not df_drop.empty:
            for _, row in df_drop.iterrows():
                msg = "🔻 *Queda de preço*\n" + _build_message(row)
                _send_telegram(token, chat, msg)
    except Exception as e:
        log.error("Erro na lógica de queda de preço: %s", e)
