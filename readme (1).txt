# Car-Market-Alert

Monitoriza anúncios de carros (OLX e Standvirtual) e envia **alertas em Telegram** quando:
- há **margem de lucro** (preço atual está **≥15% abaixo** da **referência** de mercado), e/ou
- existe **queda de preço** num anúncio **já visto** (≥ **5%** ou ≥ **€250** de redução).

O script corre **automaticamente a cada 15 minutos** via **GitHub Actions**, sem precisares de nenhuma máquina ligada.

---

## 🔎 O que o script faz

1. **Scraping** de páginas de listagem (OLX / Standvirtual) com **Playwright** (Chromium headless).
2. **Extração** de atributos: título, preço, km, ano, marca/modelo (heurística), região (Lisboa + margens).
3. **Filtros**: inclui **apenas** anúncios entre **€5.000 e €15.000** e com **≤ 200.000 km** (km desconhecido é aceite).
4. **Persistência** (CSV) do histórico para **30 dias** (por defeito), com **deduplicação** por `fonte+link`.
5. **Referência de preço**:
   - mediana por **marca+modelo** (nível 1),
   - fallback por **marca+modelo** (nível 2),
   - fallback **KNN rudimentar** por **ano/km** se faltar amostra.
6. **Deteção de margem**: alerta quando `preço / referência - 1 ≤ -15%`.
7. **Deteção de queda de preço**: alerta quando o preço atual desce **≥ 5%** ou **≥ €250** em relação ao último preço conhecido **para o mesmo anúncio**.
8. **Imagens no alerta**:
   - tenta usar **thumbnail** do cartão;
   - se não existir, abre a página do anúncio e procura **`og:image` / `twitter:image`** ou a **primeira `<img>`**;
   - caso exista, envia **`send_photo`** no Telegram.
9. **Ordenação de alertas**: por melhor desconto com **boost** nas regiões prioritárias (Lisboa e margens).
10. **Agendamento**: GitHub Actions corre o script **de 15 em 15 minutos** e publica os alertas.

---

## 🧱 Arquitetura do projeto

Car-Market-Alert/
├─ market_watch/
│  ├─ main.py                 # pipeline principal (scrape → processa → avalia → alerta)
│  ├─ requirements.txt        # dependências (Playwright, pandas, bs4, telegram-bot)
│  └─ data/
│     └─ market.csv           # histórico de anúncios (deduplicado), flags de alerta e imagem
├─ .github/
│  └─ workflows/
│     └─ schedule.yml         # workflow agendado (cron */15) para correr o script
├─ README.md                  # este documento
└─ LICENSE or MIT license

### Fluxo lógico (alto nível)

[GitHub Actions cron */15]
        ↓
  Setup Python + Playwright
        ↓
   Executa main.py
        ↓
  Scrape OLX + Standvirtual  ────────────────────────────────┐
        ↓                                                     │
  Parse cartões (preço/km/ano/marca/modelo/ região/ link/img) │
        ↓                                                     │
  Filtra (€5k–€15k, ≤200k km)                                 │
        ↓                                                     │
  Carrega + atualiza histórico (CSV, 30d, dedup)              │
        ↓                                                     │
  Referência (mediana / KNN)                                  │
        ↓                                                     │
  Avalia margem e queda de preço                              │
        ↓                                                     │
  Enriquecimento de imagem (og:image)                         │
        ↓                                                     │
  Prioriza e envia alertas (Telegram)                         │
        ↓                                                     │
  Grava histórico atualizado                                  │

---

## ⚙️ Pré‑requisitos

### Dependências (local ou Actions)
- **Python 3.11+**
- `playwright==1.48.0`
- `pandas`
- `numpy`
- `beautifulsoup4`
- `python-telegram-bot==13.15`

> Estão todas listadas em `market_watch/requirements.txt`.

### Segredos (Telegram)
Cria no GitHub (Repo → **Settings → Secrets and variables → Actions**):

- `TELEGRAM_TOKEN` → token do teu bot (BotFather).
- `TELEGRAM_CHAT_ID` → chat ou canal destino (ID numérico).

---

## 🚀 Instalação & Execução (local)

```bash
# 1) preparar ambiente
cd market_watch
python -m venv .venv
source .venv/bin/activate   # no Windows: .venv\Scriptsctivate
python -m pip install --upgrade pip
pip install -r requirements.txt
python -m playwright install --with-deps chromium

# 2) definir variáveis (exemplo bash)
export TELEGRAM_TOKEN=123456:ABCDEF
export TELEGRAM_CHAT_ID=987654321

# (opcionais)
export ROLLING_DAYS=30
export ALERT_MARGIN=0.15
export DROP_THRESHOLD_PCT=0.05
export DROP_THRESHOLD_ABS=250
export MIN_PRICE=5000
export MAX_PRICE=15000
export MAX_KM=200000

# 3) correr
python main.py
```

---

## ⏱️ Agendamento (GitHub Actions)

Cria o ficheiro `.github/workflows/schedule.yml` com:

```yaml
name: Car Market Alert - Scheduled

on:
  schedule:
    - cron: "*/15 * * * *"   # corre a cada 15 minutos (UTC)
  workflow_dispatch: {}       # permite corrida manual

jobs:
  run:
    runs-on: ubuntu-latest

    permissions:
      contents: write         # necessário se guardares histórico no repo

    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Setup Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install -r market_watch/requirements.txt
          python -m playwright install --with-deps chromium

      - name: Prepare data dir
        run: |
          mkdir -p market_watch/data

      - name: Run alert script
        working-directory: market_watch
        env:
          TELEGRAM_TOKEN: ${{ secrets.TELEGRAM_TOKEN }}
          TELEGRAM_CHAT_ID: ${{ secrets.TELEGRAM_CHAT_ID }}
          ROLLING_DAYS: "30"
          ALERT_MARGIN: "0.15"
          DROP_THRESHOLD_PCT: "0.05"
          DROP_THRESHOLD_ABS: "250"
          MIN_PRICE: "5000"
          MAX_PRICE: "15000"
          MAX_KM: "200000"
          RATE_LIMIT: "1.0"
        run: |
          python main.py

      # (Opcional) guardar histórico no repo
      - name: Commit updated market history (optional)
        if: always()
        run: |
          git config user.name "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"
          git add market_watch/data || true
          git commit -m "Update market history [skip ci]" || true
          git push || true
```

> **Nota:** o cron usa **UTC**; a periodicidade (15 min) é o que importa aqui.

---

## 🧠 Lógica de avaliação (detalhes)

- **Referência de preço (mercado)**  
  Mediana por **marca+modelo** (nível 1).  
  Se não houver amostra suficiente, tenta por **marca+modelo** (nível 2).  
  Fallback: **KNN rudimentar** por **ano/km** (20 vizinhos mais próximos).

- **Margem / “bom negócio”**  
  Um anúncio é marcado como **deal** se o preço estiver **≤ −15%** face à referência (`ALERT_MARGIN`, configurável).

- **Queda de preço (para anúncios já vistos)**  
  Compara o preço atual com o **último preço** no histórico para o mesmo `fonte+link`.  
  Alerta quando a queda é **≥ 5%** (`DROP_THRESHOLD_PCT`) **ou** **≥ €250** (`DROP_THRESHOLD_ABS`).  
  Evita duplicação com `last_drop_alert_price` e `last_margin_alert_price`.

- **Imagens nos alertas**  
  Primeiro tenta a **thumbnail** do cartão. Se não existir, abre a página e procura **`og:image`** / **`twitter:image`** / primeira `<img>`.  
  Se for encontrada, envia **`send_photo`** com legenda (inclui **link** do anúncio).  
  Caso contrário, envia **mensagem** com link (o Telegram pode fazer **preview** automático).

---

## 📦 Persistência

- Histórico em `market_watch/data/market.csv`:
  - colunas base (fonte, título, preço, km, ano, região, marca/modelo, link, data),
  - **image_url** (persistida e enriquecida),
  - **last_drop_alert_price** / **last_margin_alert_price** para evitar repetição de alertas.

- **Deduplicação** por `fonte+link` (o último registo vence).

> Se preferires, podes migrar para **Parquet** ou **SQLite** facilmente; pede e eu preparo.

---

## 🧪 Testes & observabilidade (sugestões)

- Adicionar _fixtures_ HTML para OLX/Standvirtual e testar parsing (BeautifulSoup).
- Logar contagem de cartões por fonte, tempo médio de carregamento, e número de alertas por execução.
- Alertas de erro (ex.: via Telegram) se uma fonte retornar 0 cards repetidamente (indicativo de seletor quebrado).

---

## 🔧 Troubleshooting

- **0 cartões numa fonte**: os seletores podem ter mudado (A/B). Ajusta `card_selector` e `maps` no `main.py`.  
- **Falha de Playwright no Actions**: garante `python -m playwright install --with-deps chromium`.  
- **Sem imagens no Telegram**: alguns anúncios não têm `og:image`; o enriquecimento tenta várias estratégias.  
- **Sem mensagens no Telegram**: confirma `TELEGRAM_TOKEN` e `TELEGRAM_CHAT_ID` nos **Secrets** e se o bot está autorizado no chat/canal.

---

## 🗺️ Roadmap sugerido

1. **SQLite** para histórico + índices por `fonte+link` (mais robusto que CSV).  
2. **Mais fontes**: Mobile.de, AutoScout, etc. (atenção a termos de uso).  
3. **Modelo de referência** mais rico (combustível, caixa, região) quando houver amostra suficiente.  
4. **Filtro opcional por marcas/modelos** via `.env`.  
5. **Exportar “deals do dia”** (CSV/Markdown) e anexar ao Telegram.  
6. **Dashboard simples** (Streamlit) para inspecionar histórico e métricas.

---

## 📄 Licença

MIT (ajusta conforme preferires).
