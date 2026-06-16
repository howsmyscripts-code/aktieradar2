import yfinance as yf
import json
import urllib.request
import urllib.error
import math
import time
import os
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

def fetch_fear_greed():
    try:
        req = urllib.request.Request(
            "https://api.alternative.me/fng/?limit=1",
            headers={"User-Agent": "Mozilla/5.0"}
        )
        with urllib.request.urlopen(req, timeout=8) as r:
            data = json.loads(r.read().decode())
        value = int(data["data"][0]["value"])
        classification = data["data"][0]["value_classification"]
        print(f"Fear & Greed Index: {value} ({classification})")
        return value, classification
    except Exception as e:
        print(f"Fear & Greed fetch failed: {e}")
        return None, None

def fear_greed_signal(value):
    if value is None: return 0
    if value <= 25:   return 2
    elif value <= 40: return 1
    elif value <= 60: return 0
    elif value <= 75: return -1
    else:             return -2

def fetch_sp500_futures():
    """Hämta S&P 500 futures för att förutsäga marknadsöppning"""
    try:
        futures = yf.Ticker("ES=F")
        hist = futures.history(period="2d")
        if len(hist) >= 2:
            change = ((hist["Close"].iloc[-1] - hist["Close"].iloc[-2]) / hist["Close"].iloc[-2]) * 100
            return round(change, 2)
        return None
    except:
        return None

def get_time_weight():
    """Returnera viktning baserat på tid på dagen"""
    hour = datetime.now(ZoneInfo("Europe/Stockholm")).hour
    if 9 <= hour <= 10:
        return "morning"   # Nyheter väger tyngre
    elif 17 <= hour <= 18:
        return "close_se"  # Tekniska indikatorer väger tyngre
    elif hour >= 22:
        return "close_us"  # Nasdaq-stängning, tekniska viktigast
    return "intraday"

# ── Trump RSS & News Analysis ────────────────────────────────

def fetch_trump_posts():
    """Fetch latest Trump-related news from Finnhub"""
    try:
        api_key = os.environ.get("FINNHUB_API_KEY", "")
        if not api_key:
            return []
        url = f"https://finnhub.io/api/v1/news?category=general&token={api_key}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read().decode("utf-8"))
        # Filter for Trump-related news
        trump_news = []
        for item in data[:50]:
            headline = item.get("headline", "")
            summary = item.get("summary", "")
            text = headline + " " + summary
            if "trump" in text.lower():
                trump_news.append({
                    "text": text,
                    "date": item.get("datetime", ""),
                    "headline": headline
                })
        print(f"Trump news found via Finnhub: {len(trump_news)}")
        for n in trump_news[:10]:
            print(f"  - {n['headline'][:80]}")
        return trump_news[:10]
    except Exception as e:
        print(f"Trump Finnhub error: {e}")
        return []



def fetch_article_text(url, max_chars=1500):
    """Try to fetch and extract text from a news article URL"""
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate",
            "Connection": "keep-alive",
        })
        with urllib.request.urlopen(req, timeout=5) as r:
            raw = r.read()
            import gzip as gz
            try:
                html = gz.decompress(raw).decode("utf-8", errors="ignore")
            except Exception:
                html = raw.decode("utf-8", errors="ignore")
        import re
        html = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL)
        html = re.sub(r"<style[^>]*>.*?</style>", "", html, flags=re.DOTALL)
        html = re.sub(r"<nav[^>]*>.*?</nav>", "", html, flags=re.DOTALL)
        html = re.sub(r"<footer[^>]*>.*?</footer>", "", html, flags=re.DOTALL)
        html = re.sub(r"<header[^>]*>.*?</header>", "", html, flags=re.DOTALL)
        html = re.sub(r"<[^>]+>", " ", html)
        html = re.sub(r"\s+", " ", html).strip()
        return html[:max_chars] if len(html) > 100 else None
    except Exception:
        return None

def fetch_yfinance_news(sym):
    """Fetch latest news for a stock via yfinance, including article text"""
    skip_scrape = sym.endswith(".ST")
    try:
        ticker = yf.Ticker(sym)
        news = ticker.news or []
        articles = []
        for item in news[:2]:  # Max 2 artiklar per aktie
            content = item.get("content", {})
            title = content.get("title", "") if isinstance(content, dict) else ""
            if not title:
                title = item.get("title", "")
            url = content.get("canonicalUrl", {}).get("url", "") if isinstance(content, dict) else ""
            if not url:
                url = item.get("link", "")
            if title:
                text = None
                if not skip_scrape and url and "yahoo" in url.lower():
                    text = fetch_article_text(url)
                if text:
                    articles.append(f"{title}. {text[:500]}")
                else:
                    articles.append(title)
        return articles
    except Exception as e:
        return []

def fetch_finnhub_news(sym, api_key):
    """Fetch latest news for a stock from Finnhub, including article text"""
    try:
        ticker = sym.replace(".ST", "").replace("-", ".").replace("=F", "")
        if "." in ticker and not ticker.endswith(".L") and not ticker.endswith(".DE"):
            ticker = ticker.split(".")[0]
        url = f"https://finnhub.io/api/v1/company-news?symbol={ticker}&from=2026-05-26&to=2026-12-31&token={api_key}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=8) as r:
            data = json.loads(r.read().decode("utf-8"))
        articles = []
        for item in data[:2]:  # Max 2 artiklar per aktie
            headline = item.get("headline", "")
            article_url = item.get("url", "")
            summary = item.get("summary", "")
            if not headline:
                continue
            text = None
            if article_url:
                text = fetch_article_text(article_url)
            if text:
                articles.append(f"{headline}. {text[:500]}")
            elif summary:
                articles.append(f"{headline}. {summary[:300]}")
            else:
                articles.append(headline)
        return articles
    except Exception as e:
        return []

def analyze_sentiment_claude(texts, context="", rsi=None, change=None, prev_news_score=None, signal=None):
    """Use Claude Haiku to analyze sentiment of news texts"""
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key or not texts:
        return None
    try:
        combined = "\n".join(texts[:8])
        payload = json.dumps({
            "model": "claude-haiku-4-5-20251001",
            "max_tokens": 150,
            "messages": [{
                "role": "user",
                "content": f"""You are a stock market analyst. Analyze these news headlines about {context} and assess the SHORT-TERM (1-5 day) price impact.

Focus on:
- Earnings beats/misses, revenue surprises
- Major contracts, partnerships, or customer wins/losses
- Regulatory approvals or rejections
- Executive changes (positive or negative)
- Analyst upgrades/downgrades with price targets
- Macroeconomic factors directly affecting this stock
- Sector-wide selloffs vs company-specific news

SECTOR-SPECIFIC MACRO RULES (apply these when relevant news is present):

GEOPOLITICS:
- Peace deal / geopolitical de-escalation → NEGATIVE for defense stocks (SAAB, BAE Systems, defense ETFs), POSITIVE for airlines and transport
- Military conflict / escalation → POSITIVE for defense stocks, NEGATIVE for airlines
- China sanctions / export restrictions → NEGATIVE for semiconductors (TSM, SMH), POSITIVE for US alternatives

OIL & ENERGY:
- Oil price falling → NEGATIVE for Shell and oil companies, POSITIVE for airlines and transport
- Oil price rising → POSITIVE for Shell, NEGATIVE for airlines
- Gold price rising → POSITIVE for gold ETFs (IGLN)
- High inflation data → NEGATIVE for growth/tech stocks, POSITIVE for banks and commodities

INTEREST RATES:
- Fed raises rates → NEGATIVE for tech/growth stocks, POSITIVE for banks (JPMorgan, SEB)
- Fed cuts rates → POSITIVE for tech, real estate, growth stocks

AI & TECH:
- New major AI model launch → POSITIVE for Nvidia (chips demand), NEGATIVE for AI software competitors
- Chip export restrictions → NEGATIVE for TSM and semiconductor ETFs
- Major datacenter investment announced → POSITIVE for Nvidia, Amazon, Microsoft

HEALTHCARE:
- FDA approval → POSITIVE for that company, score +2
- Competitor drug approved → NEGATIVE for competing companies (e.g. Lilly approval hurts Novo Nordisk)
- Medicare/Medicaid policy change → affects entire pharma sector

CRYPTO:
- Risk-on market sentiment → POSITIVE for BTC and ETH
- SEC crypto regulation tightening → NEGATIVE for crypto
- Institutional crypto buying → POSITIVE for BTC

CURRENCY:
- Strong USD → NEGATIVE for European exporters (SAAB, Volvo, Ericsson)
- Weak USD → POSITIVE for European exporters

IGNORE: generic market commentary, unrelated sector news, vague mentions.

Reply with ONLY a JSON object in Swedish:
{{"sentiment": "positive"|"negative"|"neutral", "score": -2 to 2, "summary": "max 12 ord pa svenska", "catalyst": "huvudsaklig prisdrivare eller none"}}

Score guide: 2=strong buy catalyst, 1=mild positive, 0=neutral/noise, -1=mild negative, -2=strong sell catalyst

Headlines:
{combined}"""
            }]
        }).encode("utf-8")
        req = urllib.request.Request(
            "https://api.anthropic.com/v1/messages",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01"
            }
        )
        with urllib.request.urlopen(req, timeout=15) as r:
            resp = json.loads(r.read().decode("utf-8"))
        text = resp["content"][0]["text"].strip()
        # Parse JSON response
        if "{" in text:
            text = text[text.find("{"):text.rfind("}")+1]
        return json.loads(text)
    except Exception as e:
        print(f"Claude API error: {e}")
        return None

def analyze_trump_posts(posts):
    """Use Claude to identify companies and sentiment in Trump posts"""
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key or not posts:
        return []
    try:
        texts = "\n---\n".join([p["text"] for p in posts[:10]])
        payload = json.dumps({
            "model": "claude-haiku-4-5-20251001",
            "max_tokens": 500,
            "messages": [{
                "role": "user",
                "content": f"""Analyze these Trump Truth Social posts. Find any company/stock mentions.
Reply with ONLY a JSON array (empty [] if no companies found):
[{{"company": "Company Name", "ticker": "TICKER or null", "sentiment": "positive|negative|neutral", "quote": "relevant quote max 100 chars", "date": "date string"}}]

Posts:
{texts}"""
            }]
        }).encode("utf-8")
        req = urllib.request.Request(
            "https://api.anthropic.com/v1/messages",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01"
            }
        )
        with urllib.request.urlopen(req, timeout=20) as r:
            resp = json.loads(r.read().decode("utf-8"))
        text = resp["content"][0]["text"].strip()
        if "[" in text:
            text = text[text.find("["):text.rfind("]")+1]
        return json.loads(text)
    except Exception as e:
        print(f"Trump analysis error: {e}")
        return []


STOCKS = [
    "INVE-B.ST", "ATCO-B.ST", "SWED-A.ST", "SAAB-B.ST", "ERIC-B.ST",
    "VOLV-B.ST", "KINV-B.ST", "HM-B.ST", "SEB-A.ST", "TEL2-B.ST", "BEAMMW-B.ST", "NANEXA.ST", "INDU-C.ST",
    "ASML", "SAP", "NVO", "LVMUY", "SHEL", "SIEGY", "NSRGY", "EADSY", "AZN", "RELX", "BAESY",
    "NVDA", "AAPL", "MSFT", "AMZN", "GOOGL", "META", "TSLA", "JPM", "BRK-B", "LLY",
    "BYDDF", "TSM",
    "CL=F", "GC=F", "SI=F", "BTC-USD", "ETH-USD",
    "CSPX.L", "EQQQ.DE", "JEDI.DE", "XACT-OMXS30.ST", "XACTHDIV.ST", "SMH.DE", "DFNS.L", "VWRL.L", "IS3N.DE", "IQQH.DE", "IGLN.L",
]

# Mappa Xetra/London ETF:er mot amerikanska tickers för nyheter
NEWS_TICKER_MAP = {
    "JEDI.DE": "ARKX",    # ARK Space Exploration ETF — samma tema, nyheter finns
    "SMH.DE":  "SMH",     # VanEck Semiconductor USA — identisk fond
    "IS3N.DE": "IEMG",    # iShares MSCI EM USA — identisk fond
    "JEDI.L":  "ARKX",
    "IGLN.L":  "IAU",     # iShares Gold Trust USA
    "DFNS.L":  "ITA",     # iShares Defense ETF USA
    "CSPX.L":  "IVV",     # iShares S&P 500 USA
    "VWRL.L":  "VT",      # Vanguard Total World USA
    "IQQH.DE": "ICLN",    # iShares Global Clean Energy USA
    "EQQQ.DE": "QQQ",     # Invesco Nasdaq-100 USA
}

def calc_rsi(closes, period=14):
    if len(closes) < period + 1: return None
    gains, losses = 0, 0
    for i in range(len(closes) - period, len(closes)):
        d = closes[i] - closes[i-1]
        if d > 0: gains += d
        else: losses -= d
    ag, al = gains/period, losses/period
    return round(100 - 100/(1 + ag/al), 1) if al != 0 else 100

def calc_ma(closes, period):
    if len(closes) < period: return None
    return round(sum(closes[-period:]) / period, 2)

def calc_macd(closes):
    if len(closes) < 26: return None, None
    closes = [c for c in closes if c and not math.isnan(float(c))]
    if len(closes) < 26: return None, None
    def ema(data, period):
        k = 2 / (period + 1)
        result = [data[0]]
        for p in data[1:]:
            val = p * k + result[-1] * (1 - k)
            result.append(val if not math.isnan(val) else result[-1])
        return result
    ema12 = ema(closes, 12)
    ema26 = ema(closes, 26)
    macd_line = [e12 - e26 for e12, e26 in zip(ema12, ema26)]
    signal_line = ema(macd_line, 9)
    v1, v2 = macd_line[-1], signal_line[-1]
    if math.isnan(v1) or math.isnan(v2): return None, None
    return v1, v2

def calc_bollinger(closes, period=20):
    if len(closes) < period: return None
    recent = closes[-period:]
    mean = sum(recent) / period
    std = (sum((x - mean)**2 for x in recent) / period) ** 0.5
    if std == 0: return 0.5
    upper = mean + 2 * std
    lower = mean - 2 * std
    pos = (closes[-1] - lower) / (upper - lower)
    return round(max(0, min(1, pos)), 2)

def calc_52w_position(closes):
    if len(closes) < 2: return None
    high = max(closes[-252:]) if len(closes) >= 252 else max(closes)
    low = min(closes[-252:]) if len(closes) >= 252 else min(closes)
    if high == low: return 0.5
    return round((closes[-1] - low) / (high - low), 2)

def calc_trend_strength(closes, period=20):
    if len(closes) < period + 1: return None
    ups = sum(1 for i in range(-period, 0) if closes[i] > closes[i-1])
    return round(ups / period, 2)

def calc_volume_signal(volumes, closes):
    if not volumes or len(volumes) < 20: return 0
    avg_vol = sum(volumes[-20:]) / 20
    latest_vol = volumes[-1]
    vol_ratio = latest_vol / avg_vol if avg_vol > 0 else 1
    price_change = (closes[-1] - closes[-2]) / closes[-2] if closes[-2] != 0 else 0 if len(closes) > 1 else 0
    if vol_ratio > 1.5 and price_change > 0: return 1
    elif vol_ratio > 1.5 and price_change < 0: return -1
    return 0

def calc_momentum_override(rsi, trend, w52_pos, bollinger):
    """Detect strong momentum that should override oversold/overbought signals"""
    if (trend is not None and trend >= 0.65 and
        w52_pos is not None and w52_pos >= 0.85 and
        bollinger is not None and bollinger >= 0.85):
        return "MOMENTUM_UP"
    return None
def calc_rsi_divergence(closes, rsi_values, period=14):
    """Detektera RSI-divergens mot pris"""
    if len(closes) < period * 2 or len(rsi_values) < period * 2:
        return None
    # Jämför senaste 10 dagar
    recent_prices = closes[-10:]
    recent_rsi = rsi_values[-10:]
    price_trend = recent_prices[-1] - recent_prices[0]
    rsi_trend = recent_rsi[-1] - recent_rsi[0]
    if price_trend < 0 and rsi_trend > 2:
        return "POSITIV_DIVERGENS"  # Pris faller men RSI stiger - köpsignal
    elif price_trend > 0 and rsi_trend < -2:
        return "NEGATIV_DIVERGENS"  # Pris stiger men RSI faller - säljsignal
    return None

def calc_support_resistance(closes, ma50, ma200):
    """Beräkna om pris är nära stöd/motstånd"""
    price = closes[-1]
    signals = []
    if ma200 and abs(price - ma200) / ma200 < 0.02:
        if price > ma200:
            signals.append("STOD_MA200")  # Stöd vid MA200
        else:
            signals.append("MOTSTAND_MA200")  # Motstånd vid MA200
    if ma50 and abs(price - ma50) / ma50 < 0.015:
        if price > ma50:
            signals.append("STOD_MA50")
        else:
            signals.append("MOTSTAND_MA50")
    return signals if signals else None

def calc_volatility_filter(closes, period=5):
    """Filtrera ut dagar med extrem volatilitet"""
    if len(closes) < period + 1: return False
    recent_changes = [abs((closes[i] - closes[i-1]) / closes[i-1] * 100)
                      for i in range(-period, 0)]
    return max(recent_changes) > 10  # Sant om något rörde sig mer än 10%

def calc_seasonal_factor(sym):
    """Enkel säsongskorrigering baserat på månad"""
    month = datetime.now(ZoneInfo("Europe/Stockholm")).month
    # Defensiva aktier starka jan-mars och sept-nov
    defensive = ["XACTHDIV.ST", "NSRGY", "SHEL", "JPM", "BRK-B"]
    # Tech/growth starka april-aug
    growth = ["NVDA", "AAPL", "MSFT", "AMZN", "GOOGL", "META", "EQQQ.DE", "SMH.DE"]
    if sym in defensive and month in [9, 10, 11, 1, 2, 3]:
        return 0.5
    elif sym in growth and month in [4, 5, 6, 7, 8]:
        return 0.5
    elif sym in ["CL=F"] and month in [6, 7, 8]:
        return -0.5  # Olja svagare sommar
    return 0

def fetch_insider_transactions(sym, finnhub_key):
    """Hämta insidertransaktioner från Finnhub"""
    if not finnhub_key: return 0
    try:
        ticker_clean = sym.replace(".ST", "").replace("-", ".").replace("=F", "")
        if "." in ticker_clean and not ticker_clean.endswith((".L", ".DE")):
            ticker_clean = ticker_clean.split(".")[0]
        url = f"https://finnhub.io/api/v1/stock/insider-transactions?symbol={ticker_clean}&token={finnhub_key}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=5) as r:
            data = json.loads(r.read().decode("utf-8"))
        transactions = data.get("data", [])[:10]
        if not transactions: return 0
        # Summera köp vs sälj senaste 3 månader
        buys = sum(t.get("share", 0) for t in transactions if t.get("transactionCode", "") in ["P", "A"])
        sells = sum(t.get("share", 0) for t in transactions if t.get("transactionCode", "") in ["S", "D"])
        if buys > sells * 2: return 1   # Starkt insiderköp
        elif sells > buys * 2: return -1  # Starkt insidersälj
        return 0
    except:
        return 0

def fetch_short_interest(ticker_obj):
    """Hämta short interest från yfinance"""
    try:
        info = ticker_obj.info
        short_ratio = info.get("shortRatio", None)
        short_pct = info.get("shortPercentOfFloat", None)
        if short_pct and short_pct > 0.2:
            return {"high": True, "pct": round(short_pct * 100, 1)}
        return {"high": False, "pct": round(short_pct * 100, 1) if short_pct else None}
    except:
        return {"high": False, "pct": None}



def compute_signal(rsi, ma50, ma200, change, macd=None, macd_signal=None,
                   bollinger=None, w52_pos=None, trend=None, vol_signal=0,
                   divergence=None, support_resistance=None, seasonal=0,
                   insider=0, news_score=0, is_volatile=False):
    score = 5.0

    # Volatilitetsfilter - ignorera signal vid extrem volatilitet
    if is_volatile:
        return "HALL", 5, None

    momentum = calc_momentum_override(rsi, trend, w52_pos, bollinger)

    if rsi is not None:
        if momentum == "MOMENTUM_UP":
            if rsi < 35: score += 2
            elif rsi < 45: score += 1
            elif rsi > 85: score -= 1
            elif rsi > 70: score -= 0.5
        else:
            if rsi < 25: score += 3
            elif rsi < 35: score += 2
            elif rsi < 45: score += 1
            elif rsi > 80: score -= 3
            elif rsi > 70: score -= 2
            elif rsi > 60: score -= 1

    if ma50 and ma200:
        gap = ((ma50 - ma200) / ma200) * 100
        if gap > 5: score += 2
        elif gap > 0: score += 1
        elif gap < -5: score -= 2
        else: score -= 1

    if macd is not None and macd_signal is not None:
        if macd > macd_signal and macd > 0: score += 1.5
        elif macd > macd_signal: score += 0.5
        elif macd < macd_signal and macd < 0: score -= 1.5
        elif macd < macd_signal: score -= 0.5

    if bollinger is not None:
        if bollinger < 0.2: score += 1.5
        elif bollinger < 0.35: score += 0.5
        elif bollinger > 0.8: score -= 1.5
        elif bollinger > 0.65: score -= 0.5

    if w52_pos is not None:
        if w52_pos < 0.15: score += 1.5
        elif w52_pos < 0.3: score += 0.5
        elif w52_pos > 0.85: score -= 1
        elif w52_pos > 0.7: score -= 0.5

    if trend is not None:
        if trend > 0.7: score += 1
        elif trend > 0.6: score += 0.5
        elif trend < 0.3: score -= 1
        elif trend < 0.4: score -= 0.5

    score += vol_signal * 0.5

    if change:
        if change > 4: score += 0.5
        elif change < -4: score -= 0.5

    # RSI-divergens
    if divergence == "POSITIV_DIVERGENS":
        score += 1.5
    elif divergence == "NEGATIV_DIVERGENS":
        score -= 1.5

    # Stöd/motstånd
    if support_resistance:
        if "STOD_MA200" in support_resistance: score += 1
        if "STOD_MA50" in support_resistance: score += 0.5
        if "MOTSTAND_MA200" in support_resistance: score -= 1
        if "MOTSTAND_MA50" in support_resistance: score -= 0.5

    # Säsongskorrigering
    score += seasonal

    # Insidertransaktioner
    score += insider * 1.5

    # Kombinerad teknisk + nyhetsfilter (förbättring #1)
    # KÖP-signal med negativt news ignoreras
    # SÄLJ-signal med positivt news ignoreras
    if news_score < -1 and score >= 7:
        score = min(score, 6)  # Nedgradera från KÖP till HÅLL
    elif news_score > 1 and score <= 4:
        score = max(score, 5)  # Uppgradera från SÄLJ till HÅLL

    score = max(1, min(10, round(score)))
    signal = "KOP" if score >= 7 else "SALJ" if score <= 4 else "HALL"
    return signal, score, momentum

results = {}

fg_value, fg_class = fetch_fear_greed()
fg_adj = fear_greed_signal(fg_value)
sp500_futures = fetch_sp500_futures()
time_weight = get_time_weight()
if sp500_futures is not None:
    print(f"S&P 500 futures: {sp500_futures:+.1f}%")
print(f"Tidsperiod: {time_weight}")

for sym in STOCKS:
    try:
        ticker = yf.Ticker(sym)
        hist = None
        for attempt in range(3):
            try:
                hist = ticker.history(period="1y")
                if hist is not None and len(hist) > 0:
                    break
            except Exception:
                time.sleep(2)
        min_bars = 2 if sym.startswith("VALOUR-") else 20
        if len(hist) < min_bars:
            raise ValueError("Too little data")

        closes = [c for c in hist["Close"].tolist() if c and not math.isnan(float(c))]
        volumes = [v for v in hist["Volume"].tolist() if v and not math.isnan(float(v))] if "Volume" in hist.columns else []
        price = round(closes[-1], 2)
        change = round(((closes[-1] - closes[-2]) / closes[-2]) * 100, 2) if len(closes) > 1 else 0
        rsi = calc_rsi(closes)
        ma50 = calc_ma(closes, 50)
        ma200 = calc_ma(closes, 200)
        macd, macd_sig = calc_macd(closes)
        bollinger = calc_bollinger(closes)
        w52_pos = calc_52w_position(closes)
        trend = calc_trend_strength(closes)
        vol_signal = calc_volume_signal(volumes, closes)

        # Nya beräkningar
        is_volatile = calc_volatility_filter(closes)
        support_resistance = calc_support_resistance(closes, ma50, ma200)
        seasonal = calc_seasonal_factor(sym)
        finnhub_key_tmp = os.environ.get("FINNHUB_API_KEY", "")
        insider = fetch_insider_transactions(sym, finnhub_key_tmp)
        short_data = fetch_short_interest(ticker)

        # RSI-divergens kräver RSI-historik
        rsi_history = []
        try:
            for i in range(max(0, len(closes)-30), len(closes)):
                rsi_history.append(calc_rsi(closes[:i+1]) or 50)
        except:
            rsi_history = []
        divergence = calc_rsi_divergence(closes, rsi_history) if len(rsi_history) >= 20 else None

        # Hämta prev news_score tidigt för compute_signal
        prev_news_score_early = None
        try:
            with open("prev_signals.json", "r") as f:
                prev_sigs_early = json.load(f)
                prev_news_score_early = prev_sigs_early.get(sym, {}).get("news_score", 0) or 0
        except:
            prev_news_score_early = 0

        signal, styrka, momentum = compute_signal(
            rsi, ma50, ma200, change,
            macd=macd, macd_signal=macd_sig,
            bollinger=bollinger, w52_pos=w52_pos,
            trend=trend, vol_signal=vol_signal,
            divergence=divergence,
            support_resistance=support_resistance,
            seasonal=seasonal,
            insider=insider,
            news_score=prev_news_score_early,
            is_volatile=is_volatile
        )

        if sym in ["BTC-USD", "ETH-USD"] and fg_adj != 0:
            styrka = max(1, min(10, styrka + fg_adj))
            signal = "KOP" if styrka >= 7 else "SALJ" if styrka <= 4 else "HALL"

        # Marknadsfilter: nedgradera KÖP-signaler vid Extreme Fear (F&G < 15)
        fear_greed_warning = None
        if fg_value and fg_value < 15 and signal == "KOP":
            styrka = max(1, styrka - 2)
            signal = "KOP" if styrka >= 7 else "SALJ" if styrka <= 4 else "HALL"
            fear_greed_warning = "Extreme Fear - KOP-signal nedgraderad"

        # Futures-justering: nedgradera om S&P 500 futures är starkt negativa
        futures_warning = None
        if sp500_futures is not None and sp500_futures < -1.5 and signal == "KOP":
            styrka = max(1, styrka - 1)
            signal = "KOP" if styrka >= 7 else "SALJ" if styrka <= 4 else "HALL"
            futures_warning = f"S&P 500 futures {sp500_futures:+.1f}% - KOP nedgraderad"
        elif sp500_futures is not None and sp500_futures > 1.5 and signal == "SALJ":
            styrka = min(10, styrka + 1)
            signal = "KOP" if styrka >= 7 else "SALJ" if styrka <= 4 else "HALL"
            futures_warning = f"S&P 500 futures {sp500_futures:+.1f}% - SALJ uppgraderad"

        # Hämta nästa earnings-datum
        earnings_date = None
        try:
            cal = ticker.calendar
            if cal is not None and not cal.empty:
                dates = cal.loc["Earnings Date"] if "Earnings Date" in cal.index else None
                if dates is not None:
                    ed = dates.iloc[0] if hasattr(dates, 'iloc') else dates
                    if hasattr(ed, 'strftime'):
                        earnings_date = ed.strftime("%Y-%m-%d")
        except Exception:
            earnings_date = None

        def safe(v): return None if v is None or (isinstance(v, float) and math.isnan(v)) else v

        ath = None
        if sym in ["CL=F", "GC=F", "SI=F", "BTC-USD", "ETH-USD"]:
            try:
                hist_max = ticker.history(period="max")
                if len(hist_max) > 0 and "High" in hist_max.columns:
                    all_highs = [h for h in hist_max["High"].tolist() if h and not math.isnan(float(h))]
                    ath = round(max(all_highs), 2) if all_highs else None
            except:
                ath = None

        finnhub_key = os.environ.get("FINNHUB_API_KEY", "")
        news_sym = NEWS_TICKER_MAP.get(sym, sym)
        finnhub_headlines = fetch_finnhub_news(news_sym, finnhub_key) if finnhub_key else []
        yfinance_headlines = fetch_yfinance_news(news_sym)
        all_headlines = list(dict.fromkeys(finnhub_headlines + yfinance_headlines))[:8]

        # Hämta föregående news_score för trendanalys
        prev_news_score = None
        try:
            with open("prev_signals.json", "r") as f:
                prev_sigs = json.load(f)
                prev_news_score = prev_sigs.get(sym, {}).get("news_score", None)
        except:
            pass

        news_sentiment = None
        if all_headlines:
            news_sentiment = analyze_sentiment_claude(
                all_headlines, sym,
                rsi=rsi, change=change,
                prev_news_score=prev_news_score,
                signal=signal
            )
            time.sleep(0.5)
        news_headlines = all_headlines

        news_score = news_sentiment.get("score", 0) if news_sentiment else 0
        adjusted_styrka = max(1, min(10, styrka + news_score))

        results[sym] = {
            "price": price, "change": change,
            "rsi": safe(rsi), "ma50": safe(ma50), "ma200": safe(ma200),
            "macd": round(macd, 3) if macd is not None and not math.isnan(macd) else None,
            "bollinger": safe(bollinger),
            "w52": safe(w52_pos),
            "trend": safe(trend),
            "signal": signal, "styrka": styrka, "ok": True,
            "ath": ath,
            "momentum": momentum,
            "earnings_date": earnings_date,
            "news_sentiment": news_sentiment.get("sentiment") if news_sentiment else None,
            "news_summary": news_sentiment.get("summary") if news_sentiment else None,
            "news_score": news_score,
            "news_confidence": news_sentiment.get("confidence") if news_sentiment else None,
            "news_time_horizon": news_sentiment.get("time_horizon") if news_sentiment else None,
            "fear_greed_warning": fear_greed_warning if 'fear_greed_warning' in dir() else None,
            "volume_signal": vol_signal,
            "divergence": divergence,
            "support_resistance": support_resistance,
            "insider_signal": insider,
            "short_interest": short_data.get("pct"),
            "short_interest_high": short_data.get("high"),
            "is_volatile": is_volatile,
            "seasonal_factor": seasonal,
            "futures_warning": futures_warning if 'futures_warning' in dir() else None,
            "time_weight": time_weight,
        }
        print(f"OK {sym}: {price} {signal} (RSI:{rsi} Vol:{vol_signal} Momentum:{momentum})")
    except Exception as e:
        results[sym] = {"ok": False, "error": str(e)}
        print(f"FAIL {sym}: {e}")

print("Fetching Trump posts...")
trump_posts_raw = fetch_trump_posts()
trump_mentions = analyze_trump_posts(trump_posts_raw) if trump_posts_raw else []
print(f"Trump mentions found: {len(trump_mentions)}")

output = {
    "updated": (datetime.now(ZoneInfo("Europe/Stockholm"))).strftime("%Y-%m-%d %H:%M svensk tid"),
    "stocks": results,
    "fear_greed": {"value": fg_value, "classification": fg_class} if fg_value else None,
    "trump_mentions": trump_mentions
}

with open("data.json", "w") as f:
    json.dump(output, f, indent=2)

print(f"\nDone: {sum(1 for v in results.values() if v.get('ok'))} / {len(results)} succeeded")

# ── Accuracy Tracking ────────────────────────────────────────────────────────
def update_accuracy_tracking(results, fg_value):
    """Spara signaler och priser for accuracy-tracking"""
    now_sw = datetime.now(ZoneInfo("Europe/Stockholm"))
    now_hour = now_sw.hour
    today = now_sw.strftime("%Y-%m-%d")

    try:
        with open("accuracy.json", "r") as f:
            accuracy = json.load(f)
    except:
        accuracy = {}

    if 9 <= now_hour <= 10:
        for sym, d in results.items():
            if not d.get("ok"): continue
            accuracy[f"{today}_{sym}"] = {
                "date": today, "sym": sym,
                "signal": d["signal"], "styrka": d["styrka"],
                "morning_price": d["price"],
                "news_score": d.get("news_score", 0),
                "fg_value": fg_value,
                "closing_price": None, "correct": None
            }
        print(f"Accuracy: sparade {len(results)} morgonsignaler")

    elif (17 <= now_hour <= 18) or now_hour >= 22:
        updated = 0
        for sym, d in results.items():
            if not d.get("ok"): continue
            key = f"{today}_{sym}"
            if key in accuracy and accuracy[key]["closing_price"] is None:
                morning_price = accuracy[key]["morning_price"]
                closing_price = d["price"]
                signal = accuracy[key]["signal"]
                pct_change = ((closing_price - morning_price) / morning_price * 100) if morning_price else 0
                if signal == "KOP":
                    correct = pct_change > 0.5
                elif signal == "SALJ":
                    correct = pct_change < -0.5
                else:
                    correct = abs(pct_change) < 1.0
                accuracy[key]["closing_price"] = closing_price
                accuracy[key]["pct_change"] = round(pct_change, 2)
                accuracy[key]["correct"] = correct
                updated += 1
        print(f"Accuracy: uppdaterade {updated} stangningspriser")

    with open("accuracy.json", "w") as f:
        json.dump(accuracy, f, indent=2)

update_accuracy_tracking(results, fg_value)

# ── Sektorkorrelation ────────────────────────────────────────────────────────
SECTOR_CORRELATIONS = {
    "SMH.DE":    ["NVDA", "TSM"],
    "JEDI.DE":   [],
    "IS3N.DE":   ["BYDDF"],
    "IQQH.DE":   ["CL=F"],
    "INVE-B.ST": ["ATCO-B.ST", "ERIC-B.ST"],
    "SAAB-B.ST": ["BAESY", "DFNS.L"],
}

def check_sector_warnings(results):
    warnings = {}
    for etf, drivers in SECTOR_CORRELATIONS.items():
        if not drivers: continue
        neg_drivers = [
            d for d in drivers
            if d in results and results[d].get("ok")
            and results[d].get("news_score", 0) < -1
        ]
        if neg_drivers and etf in results:
            warnings[etf] = f"Varning: {', '.join(neg_drivers)} har starkt negativt news"
    return warnings

sector_warnings = check_sector_warnings(results)
if sector_warnings:
    print("Sektorvarningar:")
    for sym, warning in sector_warnings.items():
        print(f"  {sym}: {warning}")
    output["sector_warnings"] = sector_warnings
    with open("data.json", "w") as f:
        json.dump(output, f, indent=2)

# ── Discord Notifikationer ────────────────────────────────────────────────────

DISPLAY_NAMES = {
    "INVE-B.ST": "Investor B", "ATCO-B.ST": "Atlas Copco B", "SWED-A.ST": "Swedbank A",
    "SAAB-B.ST": "Saab B", "ERIC-B.ST": "Ericsson B", "VOLV-B.ST": "Volvo B",
    "KINV-B.ST": "Kinnevik B", "HM-B.ST": "H&M B", "SEB-A.ST": "SEB A",
    "TEL2-B.ST": "Tele2 B", "BEAMMW-B.ST": "BeammWave B", "NANEXA.ST": "Nanexa",
    "INDU-C.ST": "Industrivarden C", "ASML": "ASML", "SAP": "SAP", "NVO": "Novo Nordisk",
    "LVMUY": "LVMH", "SHEL": "Shell", "SIEGY": "Siemens", "NSRGY": "Nestle",
    "EADSY": "Airbus", "AZN": "AstraZeneca", "RELX": "RELX", "BAESY": "BAE Systems",
    "NVDA": "Nvidia", "AAPL": "Apple", "MSFT": "Microsoft", "AMZN": "Amazon",
    "GOOGL": "Alphabet", "META": "Meta", "TSLA": "Tesla", "JPM": "JPMorgan",
    "BRK-B": "Berkshire B", "LLY": "Eli Lilly", "BYDDF": "BYD", "TSM": "TSMC",
    "CL=F": "Olja (WTI)", "GC=F": "Guld", "SI=F": "Silver",
    "BTC-USD": "Bitcoin", "ETH-USD": "Ethereum",
    "CSPX.L": "iShares Core S&P 500", "EQQQ.DE": "Invesco Nasdaq-100",
    "JEDI.DE": "VanEck Space Innovators", "XACT-OMXS30.ST": "XACT OMXS30",
    "XACTHDIV.ST": "XACT Nordic High Dividend", "SMH.DE": "VanEck Semiconductor",
    "DFNS.L": "HANetf Future of Defence", "VWRL.L": "Vanguard FTSE All-World",
    "IS3N.DE": "iShares Core MSCI EM IMI", "IQQH.DE": "iShares Global Clean Energy",
    "IGLN.L": "iShares Physical Gold",
}

INNEHAV = {
    "JEDI.DE":     {"antal": 3,  "kurs": 88.74,  "valuta": "EUR"},
    "XACTHDIV.ST": {"antal": 18, "kurs": 163.14, "valuta": "SEK"},
    "SAAB-B.ST":   {"antal": 4,  "kurs": 541.0,  "valuta": "SEK"},
    "INVE-B.ST":   {"antal": 28, "kurs": 366.0,  "valuta": "SEK"},
    "BEAMMW-B.ST": {"antal": 53, "kurs": 18.57,  "valuta": "SEK"},
}

BEVAKADE_ETFER = ["JEDI.DE", "SMH.DE", "IS3N.DE"]

def send_discord(webhook_url, embeds):
    try:
        payload = json.dumps({"embeds": embeds}).encode("utf-8")
        req = urllib.request.Request(
            webhook_url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            print(f"Discord: skickat OK ({r.status})")
    except Exception as e:
        print(f"Discord fel: {e}")

def format_signal(signal, styrka):
    if signal == "KOP":  return f"KOP {styrka}/10"
    if signal == "SALJ": return f"SALJ {styrka}/10"
    return f"HALL {styrka}/10"

def signal_color(signal):
    if signal == "KOP":  return 0x23a559
    if signal == "SALJ": return 0xf23f43
    return 0xf0b132

def build_discord_report(results, fg_value, fg_class, updated):
    webhook_url = os.environ.get("DISCORD_WEBHOOK", "")
    if not webhook_url:
        print("Discord: ingen webhook URL konfigurerad")
        return

    now_sw = datetime.now(ZoneInfo("Europe/Stockholm"))
    now_hour = now_sw.hour
    now_minute = now_sw.minute
    is_morning = 9 <= now_hour <= 10
    is_close_sweden = now_hour == 17 and 15 <= now_minute <= 35
    is_evening = now_hour >= 22
    is_full_report = is_morning or is_close_sweden or is_evening

    prev_signals = {}
    try:
        with open("prev_signals.json", "r") as f:
            prev_signals = json.load(f)
    except:
        pass

    changes = []
    for sym, d in results.items():
        if not d.get("ok"): continue
        prev = prev_signals.get(sym, {})
        if prev.get("signal") and prev["signal"] != d["signal"]:
            changes.append({
                "sym": sym, "namn": DISPLAY_NAMES.get(sym, sym),
                "from_sig": prev["signal"], "to_sig": d["signal"],
                "styrka": d["styrka"], "rsi": d["rsi"], "price": d["price"],
            })

    new_signals = {sym: {"signal": d["signal"], "styrka": d["styrka"]}
                   for sym, d in results.items() if d.get("ok")}
    with open("prev_signals.json", "w") as f:
        json.dump(new_signals, f)

    embeds = []

    if is_full_report:
        report_type = "Morgonrapport" if is_morning else "Svensk borsstangning" if is_close_sweden else "Kvallsrapport"
        embeds.append({
            "title": f"{report_type} - {updated}",
            "color": 0x5865f2,
            "fields": [
                {"name": "Fear & Greed", "value": f"{fg_value} - {fg_class}", "inline": True},
                {"name": "Aktier OK", "value": f"{sum(1 for v in results.values() if v.get('ok'))}/{len(results)}", "inline": True},
            ],
            "footer": {"text": "AktieRadar - Ej finansiell radgivning"}
        })

        innehav_fields = []
        for sym, h in INNEHAV.items():
            d = results.get(sym, {})
            if not d.get("ok"): continue
            pris = d["price"]
            pl = (pris - h["kurs"]) * h["antal"]
            pl_pct = ((pris - h["kurs"]) / h["kurs"]) * 100
            pl_str = f"+{pl:.0f}" if pl >= 0 else f"{pl:.0f}"
            pct_str = f"+{pl_pct:.1f}%" if pl_pct >= 0 else f"{pl_pct:.1f}%"
            innehav_fields.append({
                "name": DISPLAY_NAMES.get(sym, sym),
                "value": f"{format_signal(d['signal'], d['styrka'])}\n{pris:.2f} {h['valuta']} | {pl_str} ({pct_str})",
                "inline": True
            })

        if innehav_fields:
            embeds.append({
                "title": "Dina innehav",
                "color": 0x23a559,
                "fields": innehav_fields,
                "footer": {"text": "P/L baserat pa inkopspris"}
            })

        etf_fields = []
        for sym in BEVAKADE_ETFER:
            d = results.get(sym, {})
            if not d.get("ok"): continue
            etf_fields.append({
                "name": DISPLAY_NAMES.get(sym, sym),
                "value": f"{format_signal(d['signal'], d['styrka'])}\nRSI: {d['rsi']} | {d['price']:.2f} EUR",
                "inline": True
            })

        if etf_fields:
            embeds.append({
                "title": "Bevakade ETF:er",
                "color": 0x5865f2,
                "fields": etf_fields,
                "footer": {"text": "KOP vid RSI < 38 och styrka >= 7"}
            })

        kop_list = [(sym, d) for sym, d in results.items()
                    if d.get("ok") and d["signal"] == "KOP" and sym not in INNEHAV]
        kop_list.sort(key=lambda x: -x[1]["styrka"])
        if kop_list:
            kop_lines = [f"{DISPLAY_NAMES.get(s,s)[:18]:<18} RSI {d['rsi']:.0f}  {d['styrka']}/10"
                         for s, d in kop_list[:12]]
            embeds.append({
                "title": f"KOP-signaler ({len(kop_list)} st)",
                "color": 0x23a559,
                "description": "```\n" + "\n".join(kop_lines) + "\n```",
                "footer": {"text": "Extreme Fear - lagre traffsakerhet" if fg_value and fg_value < 15 else "AktieRadar"}
            })

        salj_list = [(sym, d) for sym, d in results.items()
                     if d.get("ok") and d["signal"] == "SALJ" and sym not in INNEHAV]
        salj_list.sort(key=lambda x: x[1]["styrka"])
        if salj_list:
            salj_lines = [f"{DISPLAY_NAMES.get(s,s)[:18]:<18} RSI {d['rsi']:.0f}  {d['styrka']}/10"
                          for s, d in salj_list[:12]]
            embeds.append({
                "title": f"SALJ-signaler ({len(salj_list)} st)",
                "color": 0xf23f43,
                "description": "```\n" + "\n".join(salj_lines) + "\n```",
                "footer": {"text": "AktieRadar - Ej finansiell radgivning"}
            })

    for change in changes:
        col = signal_color(change["to_sig"])
        labels = {"KOP": "KOP", "SALJ": "SALJ", "HALL": "HALL"}
        is_important = change["sym"] in INNEHAV or change["sym"] in BEVAKADE_ETFER
        title = f"SIGNAL-ALERT: {change['namn']}" if is_important else f"Signalbyte: {change['namn']}"
        embeds.append({
            "title": title,
            "color": col,
            "fields": [
                {"name": "Fran", "value": labels.get(change["from_sig"], change["from_sig"]), "inline": True},
                {"name": "Till", "value": labels.get(change["to_sig"], change["to_sig"]), "inline": True},
                {"name": "RSI", "value": str(change["rsi"]), "inline": True},
                {"name": "Styrka", "value": f"{change['styrka']}/10", "inline": True},
                {"name": "Pris", "value": f"{change['price']:.2f}", "inline": True},
            ],
            "footer": {"text": f"AktieRadar - {updated}"}
        })

    if not embeds:
        print("Discord: inga meddelanden att skicka denna korning")
        return

    for i in range(0, len(embeds), 10):
        send_discord(webhook_url, embeds[i:i+10])
        time.sleep(0.5)

build_discord_report(results, fg_value, fg_class, output["updated"])
