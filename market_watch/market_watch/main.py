
# market_watch/market_watch/main.py
# -*- coding: utf-8 -*-
"""
Car Market Watch - main
- Consolida scraping (OLX, Standvirtual, etc.)
- Mantém histórico em CSV
- Evita FutureWarning do pandas na concatenação com DataFrames vazios/all-NA
- Suporta envio de alertas (se houver módulo/funcão send_alerts no projeto)

Estrutura de pastas esperada:
  market_watch/
    ├─ data/                    # histórico gravado aqui (market.csv)
    └─ market_watch/
        ├─ main.py              # ESTE ficheiro
        ├─ olx.py               # (opcional) contém scrape_olx()
        ├─ standvirtual.py      # (opcional) contém scrape_standvirtual()
        └─ alerts.py            # (opcional) contém send_alerts(df_new, df_all, cfg)

Se algum destes módulos não existir, o programa continua e grava apenas o histórico.
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
PACKAGE_DIR = Path(__file__).resolve().parent              # market_watch/market_watch
REPO_ROOT   = PACKAGE_DIR.parent                           # market_watch/
DATA_DIR    = REPO_ROOT / "data"                           # market_watch/data
DATA_DIR.mkdir(parents=True, exist_ok=True)

CSV_PATH    = DATA_DIR / "market.csv"

# Ajusta esta lista às tuas colunas reais!
EXPECTED_COLS: List[str] = [
    "id",         # identificador único por anúncio (obrigatório para dedup)
    "source",     # 'olx' | 'standvirtual' | ...
    "title",      # título do anúncio
    "price",      # preço (numérico)
    "km",         # quilometragem (numérico ou NaN)
    "url",        # link do anúncio
    "ts",         # timestamp (ISO ou epoch)
    # Adiciona aqui quaisquer outras colunas que uses (ex.: 'year', 'location', 'images', ...)
]


# ---------------------------------------------------------------------------
# Helpers de ambiente/validação
# ---------------------------------------------------------------------------
def _get_env_float(name: str, default: float) -> float:
    val = os.environ.get(name, str(default))
    try:
        return float(val)
    except Exception:
        log.warning("Env %s inválido (%r). A usar default=%s", name, val, default)
        return default


def _get_env_int(name: str, default: int) -> int:
    val = os.environ.get(name, str(default))
    try:
        return int(float(val))
    except Exception:
        log.warning("Env %s inválido (%r). A usar default=%s", name, val, default)
        return default


def load_config_from_env() -> Dict[str, object]:
    """Lê variáveis de ambiente definidas no workflow."""
    cfg = {
        "ROLLING_DAYS":         _get_env_int("ROLLING_DAYS", 30),
        "ALERT_MARGIN":         _get_env_float("ALERT_MARGIN", 0.15),
        "DROP_THRESHOLD_PCT":   _get_env_float("DROP_THRESHOLD_PCT", 0.05),
        "DROP_THRESHOLD_ABS":   _get_env_float("DROP_THRESHOLD_ABS", 250.0),
        "MIN_PRICE":            _get_env_int("MIN_PRICE", 5000),
        "MAX_PRICE":            _get_env_int("MAX_PRICE", 15000),
        "MAX_KM":               _get_env_int("MAX_KM", 200000),
        "RATE_LIMIT":           _get_env_float("RATE_LIMIT", 1.0),  # chamadas/s
        "UA":                   os.environ.get("UA", "Mozilla/5.0 (compatible; MarketBot/1.3; +https://example.com/botinfo)"),
        "TELEGRAM_TOKEN":       os.environ.get("TELEGRAM_TOKEN"),
        "TELEGRAM_CHAT_ID":     os.environ.get("TELEGRAM_CHAT_ID"),
    }
    return cfg


# ---------------------------------------------------------------------------
# Correção do FutureWarning: concat “segura”
# ---------------------------------------------------------------------------
def safe_concat(dfs: Iterable[pd.DataFrame], expected_columns: Optional[Iterable[str]] = None) -> pd.DataFrame:
    """
    Concatena DataFrames ignorando entradas vazias/all-NA para evitar FutureWarning do pandas,
    preservando o comportamento atual.

    - dfs: iterável de pd.DataFrame
    - expected_columns: colunas esperadas (para devolver vazio com esquema correto se necessário)
    """
    cleaned: List[pd.DataFrame] = []
    for d in dfs:
        if d is None:
            continue
        if not isinstance(d, pd.DataFrame):
            log.warning("safe_concat ignorou item não-DataFrame: %r", type(d))
            continue
        if d.empty or d.dropna(how="all").empty:
            # vazio ou todas as linhas NA → ignora
            continue
        cleaned.append(d)

    if not cleaned:
        if expected_columns is not None:
            return pd.DataFrame(columns=list(expected_columns))
        return pd.DataFrame()

    return pd.concat(cleaned, ignore_index=True)


# ---------------------------------------------------------------------------
# I/O do histórico (CSV)
# ---------------------------------------------------------------------------
def load_market() -> pd.DataFrame:
    """
    Lê o histórico (CSV) e garante as colunas esperadas mesmo se vazio.
    """
    if not CSV_PATH.exists():
        log.info("Histórico não existe ainda: %s", CSV_PATH)
        return pd.DataFrame(columns=EXPECTED_COLS)

    try:
        df = pd.read_csv(CSV_PATH)
    except Exception as e:
        log.error("Falha ao ler CSV %s: %s", CSV_PATH, e)
        return pd.DataFrame(columns=EXPECTED_COLS)

    # Garante colunas esperadas
    for c in EXPECTED_COLS:
        if c not in df.columns:
            df[c] = pd.Series([None] * len(df))
    # Reordena
    df = df[EXPECTED_COLS]

    return df


def save_market(df: pd.DataFrame) -> None:
    """
    Grava o histórico consolidado em CSV.
    """
    try:
        df.to_csv(CSV_PATH, index=False)
        log.info("Histórico gravado: %s (linhas=%d)", CSV_PATH, len(df))
    except Exception as e:
        log.error("Falha ao gravar CSV %s: %s", CSV_PATH, e)


# ---------------------------------------------------------------------------
# Scraping: tentativa de importar funções existentes no projeto
# ---------------------------------------------------------------------------
SCRAPERS = []

# Tenta importar scrape_olx()
try:
    from .olx import scrape_olx  # type: ignore
    SCRAPERS.append(("olx", scrape_olx))
except Exception as e:
    log.info("scrape_olx não encontrado (%s) — continuar sem OLX.", e)

# Tenta importar scrape_standvirtual()
try:
    from .standvirtual import scrape_standvirtual  # type: ignore
    SCRAPERS.append(("standvirtual", scrape_standvirtual))
except Exception as e:
    log.info("scrape_standvirtual não encontrado (%s) — continuar sem Standvirtual.", e)


def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    """
    Ajusta colunas do DataFrame para bater com EXPECTED_COLS.
    Preenche colunas em falta com None e reordena.
    Converte price/km para numérico quando possível.
    """
    if df is None or df.empty:
        return pd.DataFrame(columns=EXPECTED_COLS)

    # Garante todas as colunas
    for c in EXPECTED_COLS:
        if c not in df.columns:
            df[c] = pd.Series([None] * len(df))

    # Converte tipos base
    df["price"] = pd.to_numeric(df["price"], errors="coerce")
    df["km"]    = pd.to_numeric(df["km"], errors="coerce")

    # Timestamp: se faltar, coloca agora (UTC ISO)
    if "ts" in df.columns:
        mask_missing = df["ts"].isna()
        if mask_missing.any():
            df.loc[mask_missing, "ts"] = datetime.now(timezone.utc).isoformat()
    else:
        df["ts"] = datetime.now(timezone.utc).isoformat()

    # Reordena
    return df[EXPECTED_COLS]


def get_new_listings(cfg: Dict[str, object]) -> pd.DataFrame:
    """
    Executa todos os scrapers disponíveis e consolida num único DataFrame normalizado.
    Respeita RATE_LIMIT (chamadas/s) entre scrapers.
    """
    rate_limit = float(cfg.get("RATE_LIMIT", 1.0))
    per_call_delay = 1.0 / max(rate_limit, 0.001)

    dfs = []
    for name, fn in SCRAPERS:
        t0 = time.time()
        log.info("A iniciar scraping: %s", name)
        try:
            df = fn(cfg)  # cada scraper deve aceitar cfg opcional
            if df is None:
                df = pd.DataFrame(columns=EXPECTED_COLS)
            df = normalize_columns(df)
            log.info("Scraper %s devolveu %d linhas", name, len(df))
            dfs.append(df)
        except Exception as e:
            log.error("Erro no scraper %s: %s", name, e)

        # Rate limit
        elapsed = time.time() - t0
        if elapsed < per_call_delay:
            time.sleep(per_call_delay - elapsed)

    # Concat segura
    df_new = safe_concat(dfs, expected_columns=EXPECTED_COLS)
    return df_new


# ---------------------------------------------------------------------------
# Regras básicas/filters antes de alertar/gravar
# ---------------------------------------------------------------------------
def apply_basic_filters(df: pd.DataFrame, cfg: Dict[str, object]) -> pd.DataFrame:
    """
    Filtra por preço e km conforme limites do ambiente.
    (Mantém lógica simples; regras mais avançadas podem existir noutro módulo.)
    """
    if df is None or df.empty:
        return df

    min_price = int(cfg.get("MIN_PRICE", 0))
    max_price = int(cfg.get("MAX_PRICE", 10**9))
    max_km    = int(cfg.get("MAX_KM", 10**9))

    mask_price = df["price"].fillna(10**12).between(min_price, max_price)
    mask_km    = df["km"].fillna(0).le(max_km)

    out = df[mask_price & mask_km].copy()
    return out


# ---------------------------------------------------------------------------
# Alertas (se existir módulo dedicado no projeto)
# ---------------------------------------------------------------------------
def maybe_send_alerts(df_new: pd.DataFrame, df_all: pd.DataFrame, cfg: Dict[str, object]) -> None:
    """
    Se existir um módulo/funcão send_alerts, usa-o. Caso contrário, não envia nada.
    """
    try:
        from .alerts import send_alerts  # type: ignore
    except Exception:
        log.info("Módulo de alertas não encontrado — a correr sem envio de Telegram.")
        return

    # Chama com o DataFrame filtrado (podes mudar para df_new sem filtros se preferires)
    df_filtered = apply_basic_filters(df_new, cfg)
    try:
        send_alerts(df_filtered, df_all, cfg)
        log.info("Alertas enviados (se houver regras).")
    except Exception as e:
        log.error("Falha no envio de alertas: %s", e)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    log.info("Car Market Watch iniciado.")
    cfg = load_config_from_env()

    # 1) Carregar histórico existente
    df_hist = load_market()
    log.info("Histórico atual: %d linhas", len(df_hist))

    # 2) Obter novos anúncios via scrapers disponíveis
    df_new = get_new_listings(cfg)
    log.info("Novos anúncios obtidos: %d", len(df_new))

    # 3) Concat segura: histórico + novos
    df_all = safe_concat([df_hist, df_new], expected_columns=EXPECTED_COLS)

    # 4) Deduplicação (por id) mantendo o mais recente
    if "id" in df_all.columns:
        before = len(df_all)
        df_all = (
            df_all.sort_values(by="ts", ascending=True)
                  .drop_duplicates(subset=["id"], keep="last")
                  .reset_index(drop=True)
        )
        after = len(df_all)
        log.info("Deduplicação por id: %d → %d", before, after)
    else:
        log.warning("Coluna 'id' não encontrada — deduplicação não aplicada.")

    # 5) Gravar histórico
    save_market(df_all)

    # 6) Enviar alertas (se módulo existir)
    maybe_send_alerts(df_new, df_all, cfg)

    log.info("Concluído.")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log.error("Erro fatal no main: %s", e)
        sys.exit(1)
