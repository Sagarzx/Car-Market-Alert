import requests
from bs4 import BeautifulSoup
import pandas as pd
import json
import logging

log = logging.getLogger("market_watch.olx")

def scrape_olx(cfg):
    # URL focada em carros, filtrada pelo preço do teu config
    url = f"https://www.olx.pt/carros-motos-e-barcos/carros/?search%5Bfilter_float_price%3Afrom%5D={cfg['MIN_PRICE']}&search%5Bfilter_float_price%3Ato%5D={cfg['MAX_PRICE']}"
    
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/110.0.0.0 Safari/537.36"}
    
    try:
        response = requests.get(url, headers=headers, timeout=15)
        soup = BeautifulSoup(response.text, 'html.parser')
        script = soup.find("script", id="__PRERENDERED_STATE__")
        
        if not script:
            return pd.DataFrame()

        data = json.loads(script.string)
        # Caminho para a lista de anúncios no JSON do OLX
        ads = data.get('ad', {}).get('ads', [])
        
        results = []
        for ad in ads:
            params = {p['key']: p['value'] for p in ad.get('params', [])}
            
            # Extração inteligente de características
            make = params.get('model', '').split(' - ')[0] if 'model' in params else ''
            model = params.get('model', '').split(' - ')[-1] if 'model' in params else ''
            
            results.append({
                "id": str(ad.get('id')),
                "source": "olx",
                "title": ad.get('title'),
                "make": make,
                "model": model,
                "price": float(ad.get('price', {}).get('value', 0)),
                "km": int(params.get('quilometros', 0).replace(' ', '').replace('km', '')) if 'quilometros' in params else 0,
                "year": params.get('ano', ''),
                "url": ad.get('url'),
                "ts": pd.Timestamp.now().isoformat()
            })
        
        return pd.DataFrame(results)
    except Exception as e:
        log.error(f"Erro no scraping do OLX: {e}")
        return pd.DataFrame()
