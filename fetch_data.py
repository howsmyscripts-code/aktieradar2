import yfinance as yf
import json
import urllib.request
import math
import time
import os
import hashlib
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
    except Exception as e:
        print(f"fetch_sp500_futures: {e}")
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

def clean_finnhub_ticker(sym):
    """
    Normaliserar en ticker till Finnhub-format. Delas av alla funktioner
    som anropar Finnhub (nyheter, insider, fundamentals) för att undvika
    dubblerad logik.
    """
    ticker_clean = sym.replace(".ST", "").replace("-", ".").replace("=F", "")
    if "." in ticker_clean and not ticker_clean.endswith((".L", ".DE")):
        ticker_clean = ticker_clean.split(".")[0]
    return ticker_clean

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
        ticker = clean_finnhub_ticker(sym)
        today = datetime.now(timezone.utc).date()
        from_date = (today - timedelta(days=30)).isoformat()
        to_date = today.isoformat()
        url = f"https://finnhub.io/api/v1/company-news?symbol={ticker}&from={from_date}&to={to_date}&token={api_key}"
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

STOCKS = [
    "INVE-B.ST", "ATCO-B.ST", "SWED-A.ST", "SAAB-B.ST", "ERIC-B.ST",
    "VOLV-B.ST", "KINV-B.ST", "HM-B.ST", "SEB-A.ST", "TEL2-B.ST", "BEAMMW-B.ST", "NANEXA.ST", "FREEM.ST", "INDU-C.ST", "CLA-B.ST", "BOL.ST",
    "ASML", "SAP", "NVO", "LVMUY", "SHEL", "SIEGY", "NSRGY", "EADSY", "AZN", "RELX", "BAESY",
    "NVDA", "INTC", "AAPL", "MSFT", "AMZN", "GOOGL", "META", "TSLA", "JPM", "BRK-B", "LLY",
    "BYDDF", "TSM",
    "CL=F", "GC=F", "SI=F", "BTC-USD", "ETH-USD",
    "CSPX.L", "EQQQ.DE", "JEDI.DE", "XACT-OMXS30.ST", "XACTHDIV.ST", "SMH.DE", "DFNS.L", "VWRL.L", "IS3N.DE", "IQQH.DE", "IGLN.L", "QUTM.DE",
]

# Mappa Xetra/London ETF:er mot amerikanska tickers för nyheter
NEWS_TICKER_MAP = {
    "JEDI.DE": "ARKX",    # ARK Space Exploration ETF — samma tema, nyheter finns
    "SMH.DE":  "SMH",     # VanEck Semiconductor USA — identisk fond
    "IS3N.DE": "IEMG",    # iShares MSCI EM USA — identisk fond
    "QUTM.DE": "QTUM",    # Defiance Quantum ETF USA — liknande tema, bättre nyhetstäckning
    "JEDI.L":  "ARKX",
    "IGLN.L":  "IAU",     # iShares Gold Trust USA
    "DFNS.L":  "ITA",     # iShares Defense ETF USA
    "CSPX.L":  "IVV",     # iShares S&P 500 USA
    "VWRL.L":  "VT",      # Vanguard Total World USA
    "IQQH.DE": "ICLN",    # iShares Global Clean Energy USA
    "EQQQ.DE": "QQQ",     # Invesco Nasdaq-100 USA
}


# MFN.se bolagsnamn för svenska aktier (pressreleaser direkt från bolagen)
MFN_TICKER_MAP = {
    "INVE-B.ST": "investor",
    "ATCO-B.ST": "atlas-copco",
    "SWED-A.ST": "swedbank",
    "SAAB-B.ST": "saab",
    "ERIC-B.ST": "ericsson",
    "VOLV-B.ST": "volvo",
    "KINV-B.ST": "kinnevik",
    "HM-B.ST": "hm",
    "SEB-A.ST": "seb",
    "TEL2-B.ST": "tele2",
    "BEAMMW-B.ST": "beammwave",
    "NANEXA.ST": "nanexa",
    "FREEM.ST": "freemelt",
    "INDU-C.ST": "industrivarden",
    "CLA-B.ST": "cloetta",
    "BOL.ST": "boliden",
    "XACT-OMXS30.ST": None,
    "XACTHDIV.ST": None,
}

def fetch_mfn_news(sym):
    """Hämta pressreleaser från MFN.se för svenska börsbolag"""
    mfn_slug = MFN_TICKER_MAP.get(sym)
    if not mfn_slug:
        return []
    try:
        import xml.etree.ElementTree as ET
        url = f"https://mfn.se/all/a/{mfn_slug}/feed"
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/rss+xml, application/xml, text/xml, */*",
        })
        with urllib.request.urlopen(req, timeout=8) as r:
            data = r.read().decode("utf-8", errors="ignore")
        root = ET.fromstring(data)
        items = root.findall(".//item")
        headlines = []
        for item in items[:3]:
            title = item.find("title")
            desc = item.find("description")
            if title is not None and title.text:
                text = title.text.strip()
                if desc is not None and desc.text:
                    text += ". " + desc.text.strip()[:200]
                headlines.append(text)
        return headlines
    except Exception:
        return []

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
    if len(closes) < 2 or closes[-2] == 0:
        price_change = 0
    else:
        price_change = (closes[-1] - closes[-2]) / closes[-2]
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

def calc_momentum_buy(trend, w52_pos, news_score, change, ma50, ma200):
    """
    Identifierar kvalitetsbolag/momentum-case som RSI-baserad logik missar:
    starka, stadigt stigande aktier som aldrig blir 'tekniskt översålda'
    men har stark trend, är nära 52-veckorstopp och stöds av positiva nyheter.
    Exempel: Investor B, VanEck Semiconductor under stark uppgång.
    """
    if trend is None or w52_pos is None or ma50 is None or ma200 is None:
        return False
    strong_trend = trend >= 0.6
    near_high = w52_pos >= 0.9
    above_mas = ma50 > ma200  # uppåtgående trend bekräftad av glidande medelvärden
    not_negative_news = news_score is not None and news_score >= 0
    not_crashing = change is None or change > -3
    return strong_trend and near_high and above_mas and not_negative_news and not_crashing
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
    growth = ["NVDA", "AAPL", "MSFT", "AMZN", "GOOGL", "META", "EQQQ.DE", "SMH.DE", "QUTM.DE"]
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
        ticker_clean = clean_finnhub_ticker(sym)
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

def fetch_fundamentals(sym, finnhub_key):
    """
    Hämta fundamental data (P/E, P/S, marginaler) från Finnhub som komplement
    till teknisk analys. Gratis endpoint, samma API-nyckel som nyheter/insider.
    Svensk täckning (.ST) kan vara begränsad - faller tyst tillbaka på None.
    """
    if not finnhub_key:
        return {"pe_ratio": None, "ps_ratio": None, "net_margin": None}
    try:
        ticker_clean = clean_finnhub_ticker(sym)
        url = f"https://finnhub.io/api/v1/stock/metric?symbol={ticker_clean}&metric=all&token={finnhub_key}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=5) as r:
            data = json.loads(r.read().decode("utf-8"))
        metric = data.get("metric", {})
        if not metric:
            return {"pe_ratio": None, "ps_ratio": None, "net_margin": None}
        return {
            "pe_ratio": metric.get("peTTM") or metric.get("peBasicExclExtraTTM"),
            "ps_ratio": metric.get("psTTM"),
            "net_margin": metric.get("netProfitMarginTTM"),
        }
    except Exception:
        return {"pe_ratio": None, "ps_ratio": None, "net_margin": None}

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

    # Momentum-köp: kvalitetsbolag/starka trender som RSI missar
    # (t.ex. Investor B, VanEck Semiconductor i stark uppgång)
    momentum_buy = calc_momentum_buy(trend, w52_pos, news_score, change, ma50, ma200)
    if momentum_buy and signal != "KOP" and not is_volatile:
        signal = "KOP"
        score = max(score, 7)
        momentum = "MOMENTUM_KOP"

    return signal, score, momentum

results = {}

fg_value, fg_class = fetch_fear_greed()
fg_adj = fear_greed_signal(fg_value)
sp500_futures = fetch_sp500_futures()
time_weight = get_time_weight()
if sp500_futures is not None:
    print(f"S&P 500 futures: {sp500_futures:+.1f}%")
print(f"Tidsperiod: {time_weight}")

# ── Optimering #3: Kör Haiku-sentiment bara vid utvalda tider ────────────────
# Sentiment behöver inte uppdateras varje körning - nyheter ändras långsamt.
# Vi kör bara sentiment under morgon (9-10), lunch (12-13) och stängning (17-18, 22-23).
# Övriga körningar återanvänder föregående sentiment (priser/RSI uppdateras ändå).
_now_hour = datetime.now(ZoneInfo("Europe/Stockholm")).hour
SENTIMENT_HOURS = {9, 10, 12, 13, 17, 18, 22, 23}
run_sentiment = _now_hour in SENTIMENT_HOURS
print(f"Sentiment-analys denna körning: {'JA' if run_sentiment else 'NEJ (återanvänder cache)'} (kl {_now_hour})")

# ── Optimering #2: Ladda nyhets-cache för att hoppa över oförändrade rubriker ──
# Cachen sparar {sym: {"headlines_hash": ..., "sentiment": {...}}}
# Om rubrikerna är identiska med förra körningen slipper vi ett Haiku-anrop.
try:
    with open("news_cache.json", "r") as f:
        news_cache = json.load(f)
except:
    news_cache = {}

# Ladda även föregående sentiment från prev_signals så vi kan återanvända det
try:
    with open("prev_signals.json", "r") as f:
        _prev_sigs_all = json.load(f)
except:
    _prev_sigs_all = {}

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
        if hist is None or len(hist) < min_bars:
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
        fundamentals = fetch_fundamentals(sym, finnhub_key_tmp)
        short_data = fetch_short_interest(ticker)

        # RSI-divergens kräver RSI-historik
        rsi_history = []
        try:
            for i in range(max(0, len(closes)-30), len(closes)):
                rsi_history.append(calc_rsi(closes[:i+1]) or 50)
        except:
            rsi_history = []
        divergence = calc_rsi_divergence(closes, rsi_history) if len(rsi_history) >= 20 else None

        # Hämta prev news_score tidigt för compute_signal (återanvänder _prev_sigs_all)
        prev_news_score_early = _prev_sigs_all.get(sym, {}).get("news_score", 0) or 0

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
        if fg_value is not None and fg_value < 15 and signal == "KOP":
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

        finnhub_key = finnhub_key_tmp
        news_sym = NEWS_TICKER_MAP.get(sym, sym)
        finnhub_headlines = fetch_finnhub_news(news_sym, finnhub_key) if finnhub_key else []
        yfinance_headlines = fetch_yfinance_news(news_sym)
        mfn_headlines = fetch_mfn_news(sym)  # Svenska pressreleaser direkt från MFN.se
        all_headlines = list(dict.fromkeys(mfn_headlines + finnhub_headlines + yfinance_headlines))[:8]

        # Hämta föregående news_score för trendanalys (återanvänder _prev_sigs_all)
        prev_news_score = _prev_sigs_all.get(sym, {}).get("news_score", None)

        # ── Optimering #2 + #3: cache + tidsfönster för Haiku-anrop ──
        # Beräkna hash av dagens rubriker för att jämföra med cachen
        headlines_hash = hashlib.md5("|".join(all_headlines).encode("utf-8")).hexdigest() if all_headlines else ""
        cached = news_cache.get(sym, {})
        news_sentiment = None

        if all_headlines:
            if not run_sentiment:
                # Utanför sentiment-tidsfönster: återanvänd cachat sentiment (sparar anrop)
                news_sentiment = cached.get("sentiment")
            elif cached.get("headlines_hash") == headlines_hash and cached.get("sentiment"):
                # Rubrikerna oförändrade sedan förra analysen: återanvänd (sparar anrop)
                news_sentiment = cached.get("sentiment")
            else:
                # Nya rubriker OCH rätt tidsfönster: gör ett riktigt Haiku-anrop
                news_sentiment = analyze_sentiment_claude(
                    all_headlines, sym,
                    rsi=rsi, change=change,
                    prev_news_score=prev_news_score,
                    signal=signal
                )
                time.sleep(0.5)
                # Uppdatera cachen med det nya resultatet
                if news_sentiment:
                    news_cache[sym] = {"headlines_hash": headlines_hash, "sentiment": news_sentiment}
        news_headlines = all_headlines

        news_score = news_sentiment.get("score", 0) if news_sentiment else 0
        styrka = max(1, min(10, styrka + news_score))
        signal = "KOP" if styrka >= 7 else "SALJ" if styrka <= 4 else "HALL"

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
            "pe_ratio": fundamentals.get("pe_ratio"),
            "ps_ratio": fundamentals.get("ps_ratio"),
            "net_margin": fundamentals.get("net_margin"),
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

# ── Accuracy Tracking ────────────────────────────────────────────────────────
def market_close_hour(sym):
    """Ungefarlig stangningstid i svensk lokal tid per marknad.
    OBS: satt till 18, inte 17, aven om Stockholmsborsen stanger 17:30 -
    timschemat (0 7-21) ger en korning exakt kl 17:00 svensk tid, vilket
    ar 30 min FORE riktig stangning. Med gransen 18 blir forsta mojliga
    utvardering korningen kl 18:00, garanterat efter borsens stangning
    bade sommar- och vintertid.
    Kravs ocksa eftersom cron annars bara skulle na 09-18 svensk tid, medan
    US-marknaden stanger 22:00 sommartid - utan denna sparr utvarderas
    US-tickers mot ett lunchtidspris, aldrig den riktiga stangningen."""
    if sym.endswith((".ST", ".DE", ".L")):
        return 18
    return 22  # US-noterade (AAPL, MSFT, NVDA, etc), krypto, ravaror

def update_accuracy_tracking(results, fg_value):
    """Spara signaler och priser for accuracy-tracking. Returnerar hela accuracy-dicten.

    Robust mot tre kanda problem:
    1. Schemaglidning i GitHub Actions - varje symbol fangas individuellt forsta
       gangen den ar "ok" idag, inte bara pa en global "forsta korningen".
       Om NVDA misslyckas kl 09:00 (API-fel) men lyckas kl 09:05 fangas den anda,
       istallet for att tappa hela dagen for just den symbolen.
    2. For tidig utvardering - closing_price/correct satts forst efter respektive
       marknads stangningstid (market_close_hour), sa US-tickers (stanger 22:00
       svensk tid) inte domms mot ett pris fran mitten av handelsdagen bara for
       att cron sista korning ar 18:00.
    3. Robust felhantering vid las/skriv av accuracy.json."""
    now_sw = datetime.now(ZoneInfo("Europe/Stockholm"))
    today = now_sw.strftime("%Y-%m-%d")

    try:
        with open("accuracy.json", "r") as f:
            accuracy = json.load(f)
        if not isinstance(accuracy, dict):
            print("Accuracy: ogiltigt format i accuracy.json, aterstaller")
            accuracy = {}
    except FileNotFoundError:
        accuracy = {}
    except (json.JSONDecodeError, OSError) as e:
        print(f"Accuracy: kunde inte lasa accuracy.json ({e}), aterstaller")
        accuracy = {}

    created, evaluated = 0, 0
    for sym, d in results.items():
        if not d.get("ok"):
            continue
        key = f"{today}_{sym}"

        if key not in accuracy:
            # Forsta gangen vi ser DENNA symbol lyckas idag - spara morgonpris.
            accuracy[key] = {
                "date": today, "sym": sym,
                "signal": d["signal"], "styrka": d["styrka"],
                "morning_price": d["price"],
                "news_score": d.get("news_score", 0),
                "fg_value": fg_value,
                "closing_price": None, "correct": None
            }
            created += 1
            continue

        if accuracy[key]["closing_price"] is not None:
            continue  # redan avgjord for idag

        if now_sw.hour < market_close_hour(sym):
            continue  # marknaden inte stangd an - vanta med att domma

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
        evaluated += 1

    print(f"Accuracy: {created} nya morgonposter, {evaluated} utvarderade ({today})")

    try:
        with open("accuracy.json", "w") as f:
            json.dump(accuracy, f, indent=2)
    except OSError as e:
        print(f"Accuracy: kunde inte skriva accuracy.json: {e}")

    return accuracy

def compute_accuracy_summary(accuracy, symbols=None):
    """
    Sammanstaller traffsakerhet per aktie fran accuracy.json.
    Om symbols anges (lista), begransas summeringen till dessa tickers.
    Returnerar dict: {sym: {"total": N, "correct": N, "pending": N, "pct": N}}
    "pending" racknar dagens/olosta poster sa summeringen inte ser tom ut
    bara for att inget hunnit avgoras an.
    """
    per_symbol = {}
    for key, entry in accuracy.items():
        sym = entry.get("sym")
        if symbols is not None and sym not in symbols:
            continue
        stats = per_symbol.setdefault(sym, {"total": 0, "correct": 0, "pending": 0})
        if entry.get("correct") is None:
            stats["pending"] += 1
            continue
        stats["total"] += 1
        if entry["correct"]:
            stats["correct"] += 1

    summary = {}
    for sym, stats in per_symbol.items():
        pct = round(stats["correct"] / stats["total"] * 100, 1) if stats["total"] > 0 else None
        summary[sym] = {"total": stats["total"], "correct": stats["correct"], "pending": stats["pending"], "pct": pct}
    return summary

accuracy_data = {}  # fylls efter sektorvarning/marknadsfilter, se nedan

# Sammanstall traffsakerhet for dina innehav specifikt (utoka listan vid behov)
TRACKED_HOLDINGS = ["INVE-B.ST", "SAAB-B.ST", "BEAMMW-B.ST", "XACTHDIV.ST", "JEDI.DE"]

# ── Sektorkorrelation ────────────────────────────────────────────────────────
SECTOR_CORRELATIONS = {
    "SMH.DE":    ["NVDA", "TSM"],
    "QUTM.DE":   ["NVDA"],  # Nvidia driver kvantsimulering/AI-infrastruktur
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

# Dämpa KÖP-confidence: sänk styrkan 1 steg för instrument med aktiv sektorvarning.
# En flaggad drivare (t.ex. NVDA starkt negativt news) höjer nedsiderisken för ETF:en.
for _etf in sector_warnings:
    _d = results.get(_etf)
    if _d and _d.get("ok") and _d.get("signal") == "KOP":
        _d["styrka"] = max(1, _d["styrka"] - 1)
        _d["signal"] = "KOP" if _d["styrka"] >= 7 else "SALJ" if _d["styrka"] <= 4 else "HALL"

# ── Marknadsbredd + marknadsfilter ───────────────────────────────────────────
# Designat filter: vid Extreme Fear (F&G < 15) OCH majoritet negativt news_score
# nedviktas KÖP-signaler ett extra steg (utöver den per-aktie -2 som redan skett).
_ok_list = [d for d in results.values() if d.get("ok")]
_neg_news = sum(1 for d in _ok_list if (d.get("news_score") or 0) < 0)
market_breadth = {
    "total": len(_ok_list),
    "negative_news": _neg_news,
    "negative_pct": round(100 * _neg_news / len(_ok_list), 1) if _ok_list else 0.0,
    "filter_applied": False,
}
if fg_value is not None and fg_value < 15 and _ok_list and _neg_news > len(_ok_list) / 2:
    for _d in results.values():
        if _d.get("ok") and _d.get("signal") == "KOP":
            _d["styrka"] = max(1, _d["styrka"] - 1)
            _d["signal"] = "KOP" if _d["styrka"] >= 7 else "SALJ" if _d["styrka"] <= 4 else "HALL"
    market_breadth["filter_applied"] = True
    print(f"Marknadsfilter AKTIVT: F&G {fg_value} + {_neg_news}/{len(_ok_list)} negativt news → KÖP nedviktade")

# Kor accuracy-tracking HAR - efter sektorvarning + marknadsfilter - sa den
# registrerar den slutgiltiga, dampade signalen som faktiskt visas i appen,
# inte den odampade rasignalen fran compute_signal().
accuracy_data = update_accuracy_tracking(results, fg_value)
accuracy_summary = compute_accuracy_summary(accuracy_data, symbols=TRACKED_HOLDINGS)

output = {
    "updated": (datetime.now(ZoneInfo("Europe/Stockholm"))).strftime("%Y-%m-%d %H:%M svensk tid"),
    "stocks": results,
    "fear_greed": {"value": fg_value, "classification": fg_class} if fg_value is not None else None,
    "accuracy_summary": accuracy_summary,
    "market_breadth": market_breadth,
}
if sector_warnings:
    output["sector_warnings"] = sector_warnings

with open("data.json", "w") as f:
    json.dump(output, f, indent=2)

# Spara nyhets-cachen så nästa körning kan hoppa över oförändrade rubriker
with open("news_cache.json", "w") as f:
    json.dump(news_cache, f, indent=2)

# PUNKT 3: Spara prev_signals.json så news_score-historiken bevaras mellan körningar.
# compute_signal() läser detta nästa körning för trendanalys av nyhetssentiment.
prev_signals_out = {
    sym: {
        "signal": d["signal"],
        "styrka": d["styrka"],
        "news_score": d.get("news_score", 0),
    }
    for sym, d in results.items() if d.get("ok")
}
with open("prev_signals.json", "w") as f:
    json.dump(prev_signals_out, f, indent=2)

print(f"\nDone: {sum(1 for v in results.values() if v.get('ok'))} / {len(results)} succeeded")
