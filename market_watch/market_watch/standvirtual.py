import requests
from bs4 import BeautifulSoup
import pandas as pd
import re

def scrape_standvirtual(cfg):
    # Exemplo simples de URL (pode ser refinado com filtros de marca)
    url = f"https://www.standvirtual.com/carros?search%5Bfilter_float_price%3Afrom%5D={cfg['MIN_PRICE']}&search%5Bfilter_float_price%3Ato%5D={cfg['MAX_PRICE']}"
    
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36"}
    
    try:
        response = requests.get(url, headers=headers, timeout=15)
        soup = BeautifulSoup(response.text, 'html.parser')
        articles = soup.find_all('article', data_testid='listing-ad')
        
        results = []
        for art in articles:
            try:
                # Extrair ID e URL
                link_tag = art.find('a', href=True)
                url_ad = link_tag['href']
                ad_id = art.get('id', url_ad.split('-ID')[-1].replace('.html', ''))

                # Preço
                price_text = art.find('span', {'class': re.compile(r'.*price.*')}).text
                price = float(re.sub(r'\D', '', price_text))

                # KM (Normalmente está num item de lista)
                km_text = art.find(text=re.compile(r'km'))
                km = int(re.sub(r'\D', '', km_text)) if km_text else 0

                results.append({
                    "id": ad_id,
                    "source": "standvirtual",
                    "title": art.find('h2').text.strip(),
                    "price": price,
                    "km": km,
                    "url": url_ad,
                    "ts": pd.Timestamp.now().isoformat()
                })
            except:
                continue
                
        return pd.DataFrame(results)
    except Exception as e:
        print(f"Erro Standvirtual: {e}")
        return pd.DataFrame()
