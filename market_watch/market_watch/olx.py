import requests
from bs4 import BeautifulSoup
import pandas as pd
import json
import re

def scrape_olx(cfg):
    url = f"https://www.olx.pt/carros-motos-e-barcos/carros/?search%5Bfilter_float_price%3Afrom%5D={cfg['MIN_PRICE']}&search%5Bfilter_float_price%3Ato%5D={cfg['MAX_PRICE']}"
    
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36"}
    
    try:
        response = requests.get(url, headers=headers, timeout=15)
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # O OLX guarda os dados num script JSON chamado __PRERENDERED_STATE__
        script_tag = soup.find("script", id="__PRERENDERED_STATE__")
        if not script_tag:
            return pd.DataFrame()

        data = json.loads(script_tag.string)
        ads_data = data['ad']['ads'] # Caminho comum no JSON do OLX
        
        results = []
        for ad in ads_data:
            # Extração de KM (fica nos parâmetros)
            km = 0
            for param in ad.get('params', []):
                if param['key'] == 'quilometros':
                    km = int(re.sub(r'\D', '', param['value']))

            results.append({
                "id": str(ad['id']),
                "source": "olx",
                "title": ad['title'],
                "price": float(ad['price']['value']),
                "km": km,
                "url": ad['url'],
                "ts": pd.Timestamp.now().isoformat()
            })
        
        return pd.DataFrame(results)
    except Exception as e:
        print(f"Erro OLX: {e}")
        return pd.DataFrame()
