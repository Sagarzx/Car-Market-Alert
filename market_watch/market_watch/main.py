
import os
import re
import csv
import asyncio
import logging
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urljoin

import pandas as pd
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright
from telegram import Bot

# ---------------- Configurações ----------------
# (podes ajustar via variáveis de ambiente ou deixar estes defaults)
UA = os.getenv("UA", "Mozilla/5.0 (compatible; MarketBot/1.1; +https://example.com/botinfo)")
ROLLING_DAYS = int(os.getenv("ROLLING_DAYS", "30"))           # janela móvel para referência
ALERT_MARGIN = float(os.getenv("ALERT_MARGIN", "0.15"))       # -15% vs referência
RATE_LIMIT = float(os.getenv("RATE_LIMIT", "1.0"))            # requests/segundo
MAX_PAGES = int(os.getenv("MAX_PAGES", "2"))                  # páginas por fonte (ajusta conforme)
MIN_SAMPLE = int(os.getenv("MIN_SAMPLE", "12"))               # amostra mínima p/ mediana

# Filtros pedidos
MIN_PRICE = int(os.getenv("MIN_PRICE", "5000"))               # €
MAX_PRICE = int(os.getenv("MAX_PRICE", "15000"))              # €
MAX_KM    = int(os.getenv("MAX_KM", "200000"))                # km

# Regiões com prioridade (Lisboa + margens)
PRIORITY_REGIONS = {
    "Lisboa","Setúbal","Almada","Oeiras","Cascais","Loures","Sintra",
    "Amadora","Odivelas","Seixal","Barreiro","Moita","Montijo","Mafra"
}

# Secrets (GitHub Actions → Secrets)
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# URLs base
OLX_BASE = "https://www.olx.pt"
OLX_URL  = f"{OLX_BASE}/carros-motos-e-barcos/carros/?page={{page}}"
SV_BASE  = "https://www.standvirtual.com"
SV_URL   = f"{SV_BASE}/carros/?page={{page}}"

# Dados persistentes
DATA_DIR = Path(__file__).resolve().parent / "data"
DATA_DIR.mkdir(exist_ok=True)
MARKET_PATH = DATA_DIR / "market.csv"

# Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)

# ---------------- Utilidades ----------------
BRANDS = {
    "Alfa","Audi","BMW","Chevrolet","Citroën","Cupra","Dacia","Daewoo","Daihatsu","Ferrari","Fiat",
    "Ford","Honda","Hyundai","Jaguar","Jeep","Kia","Land","Lexus","Mazda","Mercedes","Mini","Mitsubishi",
    "Nissan","Opel","Peugeot","Renault","Seat","Škoda","Skoda","Smart","Subaru","Suzuki","Tesla","Toyota",
    "Volkswagen","VW","Volvo","Porsche","Range","Rover","DS","BYD","GWM","MG"
}

def money(txt: str):
    """Extrai número em € do texto."""
    if not txt:
        return None
    m = re.search(r"([0-9\.\s]+)\s*€", txt.replace("\xa0", " "))
    return float(m.group(1).replace(".", "").replace(" ", "")) if m else None

def km_of(txt: str):
    """Extrai km do texto."""
    if not txt:
        return None
    m = re.search(r"([0-9\.\s]+)\s*km", txt.lower().replace("\xa0", " "))
    return float(m.group(1).replace(".", "").replace(" ", "")) if m else None

def year_of(txt: str):
    """Extrai ano do texto."""
    if not txt:
        return None
    m = re.search(r"(19|20)\d{2}", txt)
    return int(m.group(0)) if m else None

def brand_model(title: str):
    """Heurística mais robusta para marca/modelo a partir do título."""
    if not title:
        return None, None
    toks = title.strip().split()
    # Normaliza Range Rover e Land Rover
    if len(toks) >= 2 and f"{toks[0]} {toks[1]}".lower() in {"range rover", "land rover"}:
        brand = f"{toks[0]} {toks[1]}"
        model = toks[2] if len(toks) > 2 else None
        return brand, model
    # Encontra primeira token que seja marca
    for i in range(min(3, len(toks))):
        tok = toks[i].capitalize()
        if tok in BRANDS:
            brand = tok
            model = toks[i+1] if i+1 < len(toks) else None
            return brand, model
    # Fallback simples
    brand = toks[0]
    model = toks[1] if len(toks) > 1 else None
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

def score_priority(regiao: str, delta_pct: float):
    """Score para ordenar alertas (maior desconto e boost Lisboa + margens)."""
    base = -delta_pct  # maior desconto ⇒ maior score
    if regiao in PRIORITY_REGIONS:
        base *= 1.15
    return base

# ---------------- Persistência ----------------
def load_market() -> pd.DataFrame:
    if MARKET_PATH.exists():
        try:
            df = pd.read_csv(MARKET_PATH)
            # normaliza a coluna data para date
            if "data" in df.columns:
                df["data"] = pd.to_datetime(df["data"]).dt.date
            return df
        except Exception as e:
            logging.warning(f"Falha a ler {MARKET_PATH}: {e}")
    cols = ["fonte","titulo","preco","km","ano","combustivel","caixa","regiao",
            "marca","modelo","link","data"]
    return pd.DataFrame(columns=cols)

def save_market(df_new: pd.DataFrame) -> pd.DataFrame:
    df_all = pd.concat([load_market(), df_new], ignore_index=True)
    # manter apenas registos válidos
    df_all = df_all.dropna(subset=["preco", "link"])
    # dedup por fonte+link (último registo vence)
    df_all.sort_values("data", inplace=True)
    df_all.drop_duplicates(subset=["fonte", "link"], keep="last", inplace=True)
    try:
        df_all.to_csv(MARKET_PATH, index=False, quoting=csv.QUOTE_MINIMAL)
    except Exception as e:
        logging.error(f"Falha a escrever {MARKET_PATH}: {e}")
    return df_all

def recent_market(days: int) -> pd.DataFrame:
    df = load_market()
    if len(df) == 0:
        return df
    cutoff = datetime.utcnow().date() - timedelta(days=days)
    return df[df["data"] >= cutoff]

# ---------------- Referência de Preço ----------------
def compute_reference(df_market: pd.DataFrame, fonte: str, row: dict, rolling_days: int = 30):
    """
    Calcula preço de referência (mediana) por grupo:
    - Nível 1: marca+modelo (+combustível/caixa/região se disponíveis)
    - Nível 2: marca+modelo
    - Fallback: vizinhança por ano/km (KNN rudimentar)
    """
    sample = df_market[(df_market["fonte"] == fonte) & (df_market["preco"].notna())]
    sample = sample[sample["data"] >= (datetime.utcnow().date() - timedelta(days=rolling_days))]

    k1, k2 = group_keys(row)

    s1 = sample[(sample["marca"] == k1[0]) & (sample["modelo"] == k1[1])]
    if len(s1) >= MIN_SAMPLE:
        return float(s1["preco"].median())

    s2 = sample[(sample["marca"] == k2[0]) & (sample["modelo"] == k2[1])]
    if len(s2) >= MIN_SAMPLE:
        return float(s2["preco"].median())

    # Fallback: KNN por ano/km (mesmo site)
    s3 = sample.dropna(subset=["preco","ano","km"])
    if len(s3) >= MIN_SAMPLE:
        s3 = s3.copy()
        s3["dist"] = (abs(s3["ano"] - (row.get("ano") or s3["ano"].median()))/10.0) \
                   + (abs(s3["km"] - (row.get("km") or s3["km"].median()))/50000.0)
        neigh = s3.sort_values("dist").head(20)
        return float(neigh["preco"].median())
    return None

# ---------------- Scraping ----------------
async def fetch_list_page(page, url: str, source: str, card_selector: str, maps: dict, base_url: str):
    """
    Faz fetch da página de listagem e extrai rows básicas.
    Ajusta 'card_selector' e 'maps' se o HTML mudar.
    """
    await page.goto(url, timeout=60000)
    await asyncio.sleep(1.0 / max(RATE_LIMIT, 0.1))
    html = await page.content()

    soup = BeautifulSoup(html, "html.parser")
    cards = soup.select(card_selector)
    rows = []
    for c in cards:
        t = c.select_one(maps["title"])
        p = c.select_one(maps["price"])
        a = c.select_one(maps["link"])
        meta = c.select_one(maps.get("meta", "p"))

        title = t.get_text(" ", strip=True) if t else None
        price = money(p.get_text(" ", strip=True)) if p else None
        raw_link = a.get("href") if a else None
        link = urljoin(base_url, raw_link) if raw_link else None
        desc = meta.get_text(" ", strip=True) if meta else ""

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
    return rows

async def scrape_source(ctx, base_url: str, url_tpl: str, source: str, card_selector: str, maps: dict) -> list:
    """Paginação simples e scraping para uma fonte."""
    page = await ctx.new_page()
    out = []
    for page_num in range(1, MAX_PAGES + 1):
        url = url_tpl.format(page=page_num)
        try:
            rows = await fetch_list_page(page, url, source, card_selector, maps, base_url)
            logging.info(f"{source} página {page_num}: {len(rows)} cards")
            out.extend(rows)
        except Exception as e:
            logging.warning(f"Falha em {source} página {page_num}: {e}")
    await page.close()
    return out

# ---------------- Telegram ----------------
def send_telegram_alerts(alerts: list):
    """Envia alertas para Telegram via Secrets."""
    token = TELEGRAM_TOKEN
    chat  = TELEGRAM_CHAT_ID
    if not token or not chat:
        logging.warning("⚠️ Define TELEGRAM_TOKEN e TELEGRAM_CHAT_ID nos Secrets.")
        return
    bot = Bot(token=token)
    for a in alerts:
        try:
            msg = (f"[ALERTA {a['fonte']}] {a['titulo']}\n"
                   f"Preço: €{a['preco']:.0f} | Referência: €{a['ref']:.0f} | Δ: {a['delta_pct']}%\n"
                   f"Ano: {a.get('ano')} | Km: {a.get('km')} | Região: {a.get('regiao')}\n"
                   f"{a['link']}")
            bot.send_message(chat_id=chat, text=msg)
        except Exception as e:
            logging.error(f"Falha a enviar alerta: {e}")

# ---------------- Ciclo principal ----------------
async def run_cycle():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        ctx = await browser.new_context(user_agent=UA)

        # Scraping OLX
        olx_rows = await scrape_source(
            ctx, OLX_BASE, OLX_URL, "OLX",
            card_selector="div[data-cy='l-card']",
            maps={"title": "h6", "price": "[data-testid='ad-price']", "link": "a", "meta": "p"}
        )

        # Scraping Standvirtual
        sv_rows = await scrape_source(
            ctx, SV_BASE, SV_URL, "Standvirtual",
            card_selector="article",   # pode precisar de ajuste
            maps={"title": "h2", "price": ".price", "link": "a", "meta": "ul"}
        )

        await browser.close()

    # Consolida
    df_new = pd.DataFrame(olx_rows + sv_rows)

    # Limpeza básica + filtros pedidos
    df_new = df_new[df_new["preco"].notna()]
    df_new = df_new[(df_new["preco"] >= MIN_PRICE) & (df_new["preco"] <= MAX_PRICE)]
    df_new = df_new[(df_new["km"].isna()) | (df_new["km"] <= MAX_KM)]  # aceita km desconhecido, mas filtra > MAX_KM

    if df_new.empty:
        logging.info("Sem novos anúncios no intervalo de preço/km.")
        return

    # Persiste e usa histórico dos últimos ROLLING_DAYS
    df_all = save_market(df_new)
    df_market = recent_market(ROLLING_DAYS)

    alerts = []
    for _, row in df_new.iterrows():
        ref = compute_reference(df_market, row["fonte"], row, rolling_days=ROLLING_DAYS)
        if not ref:
            continue
        delta_pct = (row["preco"] / ref) - 1.0
        # Só alertar se houver boa margem (ex.: <= -15%)
        if delta_pct <= -ALERT_MARGIN:
            alerts.append({
                "fonte": row["fonte"], "titulo": row["titulo"],
                "preco": row["preco"], "ref": round(ref, 0),
                "delta_pct": round(delta_pct * 100, 1),
                "ano": row.get("ano"), "km": row.get("km"),
                "regiao": row.get("regiao"), "link": row["link"],
                "score": score_priority(row.get("regiao"), delta_pct)
            })

    # Ordena por melhor desconto e prioridade Lisboa+Margens
    alerts = sorted(alerts, key=lambda x: x["score"], reverse=True)

    logging.info(f"Total de alertas: {len(alerts)}")
    if alerts:
        send_telegram_alerts(alerts)

# Entry point correto
if __name__ == "__main__":
    try:
        asyncio.run(run_cycle())
    except Exception as e:
        logging.exception(f"Falha geral na execução: {e}")
