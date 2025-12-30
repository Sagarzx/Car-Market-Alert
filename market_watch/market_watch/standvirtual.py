
# -*- coding: utf-8 -*-
import logging
import pandas as pd
from datetime import datetime, timezone

log = logging.getLogger("market_watch.standvirtual")

def scrape_standvirtual(cfg) -> pd.DataFrame:
    """
    Placeholder: devolve 1 registo fictício para testar o pipeline.
    Substituir pela lógica real com Playwright/requests.
    """
    log.info("Standvirtual placeholder ativo — a devolver 1 item de teste.")
    df = pd.DataFrame([{
        "id": "sv-demo-001",
        "source": "standvirtual",
        "title": "Demo SV — Carro de teste",
        "price": 10999,
        "km": 98765,
        "url": "https://www.standvirtual.com/",
        "ts": datetime.now(timezone.utc).isoformat(),
    }])
    return df
