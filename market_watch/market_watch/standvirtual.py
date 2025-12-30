import requests
from bs4 import BeautifulSoup
import pandas as pd
import json
import logging
import re

log = logging.getLogger("market_watch.standvirtual")

def scrape_standvirtual(cfg):
    url = f"https://www.standvirtual.com/carros?search%5Bfilter_float_price%3Afrom%5D={cfg['MIN_PRICE']}&search%5Bfilter_float_price%3Ato%5D={cfg['MAX_PRICE']}"
    
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/110.0.0.0 Safari/537.36"}
    
    try:
        response = requests.get(url, headers=headers, timeout=15)
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # O Standvirtual guarda os dados em scripts do tipo application/ld+json
        scripts = soup.find_all("script", type="application/ld+json")
        
        results = []
        for s in scripts:
            try:
                data = json.loads(s.string)
                # Procuramos o tipo 'Car' ou lista de ofertas
                if '@type' in data and data['@type'] == 'ItemList':
                    for item in data.get('itemListElement', []):
                        car = item.get('item', {})
                        if not car: continue
                        
                        # Extração de dados limpos
                        full_name = car.get('name', '')
                        brand = car.get('brand', {}).get('name', '')
                        model = full_name.replace(brand, '').strip()

                        results.append({
                            "id": car.get('url', '').split('-ID')[-1].replace('.html', ''),
                            "source": "standvirtual",
                            "title": full_name,
                            "make": brand,
                            "model": model,
                            "price": float(car.get('offers', {}).get('price', 0)),
                            "km": 0, # Exige um segundo parse ou regex no título se não estiver no JSON
                            "url": car.get('url'),
                            "ts": pd.Timestamp.now().isoformat()
                        })
            except:
                continue
        
        return pd.DataFrame(results)
    except Exception as e:
        log.error(f"Erro no Standvirtual: {e}")
        return pd.DataFrame()
