
# -*- coding: utf-8 -*-
import logging
import pandas as pd
from datetime import datetime, timezone

log = logging.getLogger("market_watch.olx")

def scrape_olx(cfg) -> pd.DataFrame:
    """
    Placeholder: devolve 1 registo fictício para testar o pipeline.
    Substituir pela lógica real com Playwright/requests.
    """
    log.info("OLX placeholder ativo — a devolver 1 item de teste.")
    df = pd.DataFrame([{
        "id": "olx-demo-001",
        "source": "olx",
        "title": "Demo OLX — Carro de teste",
        "price": 9999,
        "km": 123456,
        "url": "https://www.olx.pt/",
        "ts": datetime.now(timezone.utc).isoformat(),
    }])
    return df
