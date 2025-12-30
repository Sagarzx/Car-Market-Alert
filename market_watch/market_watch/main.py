# market_watch/market_watch/main.py
# -*- coding: utf-8 -*-
"""
Car Market Watch - main
- Consolida scraping inteligente (extração de Marca e Modelo)
- Mantém histórico em CSV com colunas expandidas
- Evita duplicados e calcula médias por categoria
"""

import os
import sys
import time
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, List, Optional, Dict

import pandas as pd

# ---------------------------------------------------------------------------
# Configuração de logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("market_watch")

# ---------------------------------------------------------------------------
# Constantes e paths
# ---------------------------------------------------------------------------
PACKAGE_DIR = Path(__file__).resolve().parent
REPO_ROOT   = PACKAGE_DIR.parent
DATA_DIR    = REPO_ROOT / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

CSV_PATH    = DATA_DIR / "market.csv"

# COLUNAS ATUALIZADAS: Incluímos make, model e year para análise inteligente
EXPECTED_COLS: List[str] = [
    "id", "source", "title", "make", "model", "year", "price", "km", "url", "ts"
]

# ---------------------------------------------------------------------------
# Helpers de ambiente
# ---------------------------------------------------------------------------
def _get_env_float(name: str, default: float) -> float:
    val = os.environ.get(name, str(default))
    try: return float(val)
    except: return default

def _get_env_int(name: str, default: int) -> int:
    val = os.environ.get(name, str(default))
    try: return int(float(val))
    except: return default

def load_config_from_env() -> Dict[str, object]:
    return {
        "ROLLING_DAYS":       _get_env_int("ROLLING_DAYS", 30),
        "ALERT_MARGIN":       _get_env_float("ALERT_MARGIN", 0.15),
        "DROP_THRESHOLD_PCT": _get_env_float("DROP_THRESHOLD_PCT", 0.05),
        "DROP_THRESHOLD_ABS": _get_env_float("DROP_THRESHOLD_ABS", 250.0),
        "MIN_PRICE":          _get_env_int("MIN_PRICE", 5000),
        "MAX_PRICE":          _get_env_int("MAX_PRICE", 15000),
        "MAX_KM":             _get_env_int("MAX_KM", 200000),
        "RATE_LIMIT":         _get_env_float("RATE_LIMIT", 1.0),
        "TELEGRAM_TOKEN":     os.environ.get("TELEGRAM_TOKEN"),
        "TELEGRAM_CHAT_ID":   os.environ.get("TELEGRAM_CHAT_ID"),
    }

# ---------------------------------------------------------------------------
# I/O do histórico (CSV)
# ---------------------------------------------------------------------------
def load_market() -> pd.DataFrame:
    if not CSV_PATH.exists():
        log.info("Histórico novo iniciado.")
        return pd.DataFrame(columns=EXPECTED_COLS)

    try:
        df = pd.read_csv(CSV_PATH)
        # Garante que colunas novas (make/model) existem no CSV antigo se ele já existia
        for c in EXPECTED_COLS:
            if c not in df.columns: df[c] = None
        return df[EXPECTED_COLS]
    except Exception as e:
        log.error("Erro ao ler histórico: %s", e)
        return pd.DataFrame(columns=EXPECTED_COLS)

def save_market(df: pd.DataFrame) -> None:
    try:
        df.to_csv(CSV_PATH, index=False)
        log.info("Histórico guardado: %d anúncios.", len(df))
    except Exception as e:
        log.error("Falha ao gravar CSV: %s", e)

# ---------------------------------------------------------------------------
# Scraping e Normalização
# ---------------------------------------------------------------------------
def safe_concat(dfs: Iterable[pd.DataFrame], expected_columns: List[str]) -> pd.DataFrame:
    cleaned = [d for d in dfs if d is not None and not d.empty]
    if not cleaned: return pd.DataFrame(columns=expected_columns)
    return pd.concat(cleaned, ignore_index=True)

def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty: return pd.DataFrame(columns=EXPECTED_COLS)
    for c in EXPECTED_COLS:
        if c not in df.columns: df[c] = None
    
    df["price"] = pd.to_numeric(df["price"], errors="coerce")
    df["km"]    = pd.to_numeric(df["km"], errors="coerce")
    
    if "ts" not in df.columns or df["ts"].isna().all():
        df["ts"] = datetime.now(timezone.utc).isoformat()
        
    return df[EXPECTED_COLS]

# Importação dinâmica dos módulos
SCRAPERS = []
try:
    from .olx import scrape_olx
    SCRAPERS.append(("olx", scrape_olx))
except: log.info("OLX scraper não carregado.")

try:
    from .standvirtual import scrape_standvirtual
    SCRAPERS.append(("standvirtual", scrape_standvirtual))
except: log.info("Standvirtual scraper não carregado.")

def get_new_listings(cfg: Dict[str, object]) -> pd.DataFrame:
    dfs = []
    for name, fn in SCRAPERS:
        try:
            log.info("Scraping %s...", name)
            df = fn(cfg)
            dfs.append(normalize_columns(df))
            time.sleep(1.0 / float(cfg.get("RATE_LIMIT", 1.0)))
        except Exception as e:
            log.error("Erro em %s: %s", name, e)
    return safe_concat(dfs, EXPECTED_COLS)

# ---------------------------------------------------------------------------
# Main Logic
# ---------------------------------------------------------------------------
def main() -> None:
    log.info("--- Iniciando Car Market Watch ---")
    cfg = load_config_from_env()

    # 1) Carregar dados antigos
    df_hist = load_market()

    # 2) Capturar anúncios novos
    df_new = get_new_listings(cfg)
    
    # 3) Fundir e remover duplicados (mantendo o mais recente pelo ID)
    df_all = safe_concat([df_hist, df_new], EXPECTED_COLS)
    if not df_all.empty:
        df_all = df_all.sort_values("ts").drop_duplicates(subset=["id"], keep="last")

    # 4) Gravar histórico atualizado ANTES de alertar (para o alert ter base de cálculo)
    save_market(df_all)

    # 5) Enviar Alertas Inteligentes
    try:
        from .alerts import send_alerts
        # Enviamos df_new (o que acabou de entrar) e df_all (a base total para médias)
        send_alerts(df_new, df_all, cfg)
    except Exception as e:
        log.error("Erro no envio de alertas: %s", e)

    log.info("--- Ciclo Concluído ---")

if __name__ == "__main__":
    main()
