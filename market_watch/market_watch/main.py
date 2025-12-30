
import os, asyncio, re, statistics, time
import pandas as pd
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
from playwright.async_api import async_playwright
from telegram import Bot

# ---------------- Configurações ----------------
UA = "Mozilla/5.0 (compatible; MarketBot/1.0; +https://example.com/botinfo)"
ROLLING_DAYS = int(os.getenv("ROLLING_DAYS", "30"))   # janela móvel
ALERT_MARGIN = float(os.getenv("ALERT_MARGIN", "0.15"))  # -15%
MIN_SAMPLE = 12
RATE_LIMIT = 1.0  # requests/segundo (respeito ao site)

# Regiões com prioridade (Lisboa + margens)
PRIORITY_REGIONS = {
    "Lisboa","Setúbal","Almada","Oeiras","Cascais","Loures","Sintra",
    "Amadora","Odivelas","Seixal","Barreiro","Moita","Montijo","Mafra"
}

# Secrets (GitHub Actions → Secrets)
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# URLs de listagem geral (sem filtros específicos)
OLX_URL = "https://www.olx.pt/carros-motos-e-barcos/carros/"
SV_URL  = "https://www.standvirtual.com/carros/"

# ---------------- Utilidades ----------------
def money(txt: str):
    """Extrai número em € do texto."""
    m = re.search(r"([0-9\.\s]+)\s*€", (txt or "").replace("\xa0"," "))
    return float(m.group(1).replace(".","").replace(" ","")) if m else None

def km_of(txt: str):
    """Extrai km do texto."""
    m = re.search(r"([0-9\.\s]+)\s*km", (txt or "").lower().replace("\xa0"," "))
    return float(m.group(1).replace(".","").replace(" ","")) if m else None

def year_of(txt: str):
    """Extrai ano do texto."""
    m = re.search(r"(19|20)\d{2}", txt or "")
    return int(m.group(0)) if m else None

def brand_model(title: str):
    """Heurística simples para marca/modelo a partir do título."""
    toks = (title or "").strip().split()
    brand = toks[0] if toks else None
    model = toks[1] if len(toks)>1 else None
    return brand, model

def region_guess(card_text: str):
    """Marca a região se contiver uma das regiões prioritárias."""
    low = (card_text or "").lower()
    for r in PRIORITY_REGIONS:
        if r.lower() in low:
            return r
    return None

def group_keys(row: dict):
    """Chaves de agrupamento: nível 1 e fallback nível 2."""
    k1 = (row.get("marca"), row.get("modelo"), row.get("combustivel"),
          row.get("caixa"), row.get("regiao"))
    k2 = (row.get("marca"), row.get("modelo"))
    return k1, k2

def compute_reference(df_market: pd.DataFrame, fonte: str, row: dict, rolling_days: int = 30):
    """
    Calcula preço de referência (mediana) por grupo:
    - Nível 1: marca+modelo (+combustível/caixa/região se disponíveis)
    - Nível 2: marca+modelo
    - Fallback: vizinhança por ano/km (KNN rudimentar)
    """
    sample = df_market[(df_market["fonte"]==fonte) & (df_market["preco"].notna())]
    sample = sample[sample["data"] >= (datetime.utcnow().date() - timedelta(days=rolling_days))]

    k1, k2 = group_keys(row)

    s1 = sample[(sample["marca"]==k1[0]) & (sample["modelo"]==k1[1])]
    if len(s1) >= MIN_SAMPLE:
        return float(statistics.median(s1["preco"]))

    s2 = sample[(sample["marca"]==k2[0]) & (sample["modelo"]==k2[1])]
    if len(s2) >= MIN_SAMPLE:
        return float(statistics.median(s2["preco"]))

    # Fallback: KNN por ano/km (mesmo site)
    s3 = sample.dropna(subset=["preco","ano","km"])
    if len(s3) >= MIN_SAMPLE:
        s3 = s3.copy()
        s3["dist"] = (abs(s3["ano"] - (row.get("ano") or s3["ano"].median()))/10.0) \
                   + (abs(s3["km"] - (row.get("km") or s3["km"].median()))/50000.0)
        neigh = s3.sort_values("dist").head(20)
        return float(statistics.median(neigh["preco"]))
    return None

def score_priority(regiao: str, delta_pct: float):
    """Score para ordenar alertas (maior desconto e boost Lisboa + margens)."""
    base = -delta_pct  # maior desconto ⇒ maior score
    if regiao in PRIORITY_REGIONS:
        base *= 1.15
    return base

# ---------------- Scraping genérico ----------------
async def fetch_list_page(pw, url: str, source: str, card_selector: str, maps: dict):
    """
    Faz fetch da página de listagem e extrai rows básicas.
    Ajusta 'card_selector' e 'maps' se o HTML mudar.
    """
    browser = await pw.chromium.launch(headless=True)
    ctx = await browser.new_context(user_agent=UA)
    page = await ctx.new_page()
    await page.goto(url, timeout=60000)
    await page.wait_for_timeout(2000)
    html = await page.content()
    await browser.close()

    soup = BeautifulSoup(html, "html.parser")
    cards = soup.select(card_selector)
    rows = []
    for c in cards:
        t = c.select_one(maps["title"])
        p = c.select_one(maps["price"])
        a = c.select_one(maps["link"])
        meta = c.select_one(maps.get("meta","p"))

        title = t.get_text(" ", strip=True) if t else None
        price = money(p.get_text(" ", strip=True)) if p else None
        link  = a.get("href") if a else None
        desc  = meta.get_text(" ", strip=True) if meta else ""

        km    = km_of(f"{title} {desc}")
        ano   = year_of(f"{title} {desc}")
        marca, modelo = brand_model(title)
        regiao = region_guess(desc + " " + (title or ""))

        rows.append({
            "fonte": source, "titulo": title, "preco": price, "km": km, "ano": ano,
            "combustivel": None, "caixa": None, "regiao": regiao,
            "marca": marca, "modelo": modelo,
            "link": link, "data": datetime.utcnow().date()
        })
    time.sleep(1.0/RATE_LIMIT)  # rate-limit simples
    return rows

# ---------------- Telegram ----------------
def send_telegram_alerts(alerts: list):
    """Envia alertas para Telegram via Secrets."""
    token = TELEGRAM_TOKEN
    chat  = TELEGRAM_CHAT_ID
    if not token or not chat:
        print("⚠️ Define TELEGRAM_TOKEN e TELEGRAM_CHAT_ID nos Secrets.")
        return
    bot = Bot(token=token)
    for a in alerts:
        msg = (f"[ALERTA {a['fonte']}] {a['titulo']}\n"
               f"Preço: €{a['preco']:.0f} | Referência: €{a['ref']:.0f} | Δ: {a['delta_pct']}%\n"
               f"Ano: {a.get('ano')} | Km: {a.get('km')} | Região: {a.get('regiao')}\n"
               f"{a['link']}")
        bot.send_message(chat_id=chat, text=msg)

# ---------------- Ciclo principal ----------------
async def run_cycle():
    async with async_playwright() as pw:
        # OLX
        olx_rows = await fetch_list_page(
            pw, OLX_URL, "OLX",
            card_selector="div[data-cy='l-card']",
            maps={"title":"h6","price":"[data-testid='ad-price']","link":"a","meta":"p"}
        )
        # Standvirtual
        sv_rows = await fetch_list_page(
            pw, SV_URL, "Standvirtual",
            card_selector="article",   # ajusta se necessário
            maps={"title":"h2","price":".price","link":"a","meta":"ul"}
        )

        df_new = pd.DataFrame(olx_rows + sv_rows)
        # Limpeza básica
        df_new = df_new[(df_new["preco"].notna()) & (df_new["preco"]>1000)]

        # Em produção: usar histórico persistente (SQLite/Blob) + backfill 30d.
        # Para arranque simples, usamos o próprio df_new como "mercado".
        df_market = df_new.copy()

        alerts = []
        for _, row in df_new.iterrows():
            ref = compute_reference(df_market, row["fonte"], row, rolling_days=ROLLING_DAYS)
            if not ref:
                continue
            delta_pct = (row["preco"]/ref - 1)
            if delta_pct <= -ALERT_MARGIN:
                alerts.append({
                    "fonte": row["fonte"], "titulo": row["titulo"],
                    "preco": row["preco"], "ref": round(ref,0),
                    "delta_pct": round(delta_pct*100,1),
                    "ano": row.get("ano"), "km": row.get("km"),
                    "regiao": row.get("regiao"), "link": row["link"],
                    "score": score_priority(row.get("regiao"), delta_pct)
                })

        # Ordena por melhor desconto e prioridade Lisboa+Margens
        alerts = sorted(alerts, key=lambda x: x["score"], reverse=True)
        if alerts:
            send_telegram_alerts(alerts)

if __name__ == "__main__":
    asyncio.run(run_cycle())
