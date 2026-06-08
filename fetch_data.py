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
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "en-US,en;q=0.9",
        })
        with urllib.request.urlopen(req, timeout=8) as r:
            html = r.read().decode("utf-8", errors="ignore")
        # Remove scripts, styles, tags
        import re
        html = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL)
        html = re.sub(r"<style[^>]*>.*?</style>", "", html, flags=re.DOTALL)
        html = re.sub(r"<[^>]+>", " ", html)
        html = re.sub(r"\s+", " ", html).strip()
        # Return first meaningful chunk
        return html[:max_chars] if len(html) > 100 else None
    except Exception:
        return None

def fetch_yfinance_news(sym):
    """Fetch latest news for a stock via yfinance, including article text"""
    try:
        ticker = yf.Ticker(sym)
        news = ticker.news or []
        articles = []
        for item in news[:5]:
            content = item.get("content", {})
            title = content.get("title", "") if isinstance(content, dict) else ""
            if not title:
                title = item.get("title", "")
            url = content.get("canonicalUrl", {}).get("url", "") if isinstance(content, dict) else ""
            if not url:
                url = item.get("link", "")
            if title:
                # Try to fetch article text
                text = None
                if url and "yahoo" in url.lower():
                    text = fetch_article_text(url)
                # Use full text if available, else just title
                if text:
                    articles.append(f"{title}. {text[:500]}")
                else:
                    articles.append(title)
        return articles
    except Exception as e:
        return []

def fetch_finnhub_news(sym, api_key):
    """Fetch latest news for a stock from Finnhub"""
    try:
        # Convert Yahoo Finance ticker to Finnhub format
        ticker = sym.replace(".ST", "").replace("-", ".").replace("=F", "")
        if "." in ticker and not ticker.endswith(".L") and not ticker.endswith(".DE"):
            ticker = ticker.split(".")[0]
        url = f"https://finnhub.io/api/v1/company-news?symbol={ticker}&from=2026-05-26&to=2026-12-31&token={api_key}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=8) as r:
            data = json.loads(r.read().decode("utf-8"))
        headlines = [item.get("headline", "") for item in data[:5] if item.get("headline")]
        return headlines
    except Exception as e:
        return []

def analyze_sentiment_claude(texts, context=""):
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

IGNORE: generic market commentary, unrelated sector news, vague mentions.

Reply with ONLY a JSON object:
{{"sentiment": "positive"|"negative"|"neutral", "score": -2 to 2, "summary": "max 12 words", "catalyst": "main price driver or none"}}

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
    "BABA", "TCEHY", "PDD", "BYDDF", "JD",
    "TSM", "CAMT",
    "TM", "SONY", "NTDOY", "FANUY", "MUFG",
    "005930.KS", "005380.KS", "000660.KS",
    "CL=F", "GC=F", "SI=F", "BTC-USD", "ETH-USD",
    "CSPX.L", "EQQQ.DE", "JEDI.L", "XACT-OMXS30.ST", "XACTHDIV.ST", "SMH", "DFNS.L", "VWRL.L", "IEMG", "IQQH.DE", "IGLN.L",
]

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
    # Strong upward momentum: high trend + high 52w + high bollinger
    if (trend is not None and trend >= 0.65 and
        w52_pos is not None and w52_pos >= 0.85 and
        bollinger is not None and bollinger >= 0.85):
        return "MOMENTUM_UP"  # Like ERIC B — ignore overbought RSI
    return None

def compute_signal(rsi, ma50, ma200, change, macd=None, macd_signal=None,
                   bollinger=None, w52_pos=None, trend=None, vol_signal=0):
    score = 5.0

    # Check for momentum override
    momentum = calc_momentum_override(rsi, trend, w52_pos, bollinger)

    # 1. RSI — but soften if strong momentum
    if rsi is not None:
        if momentum == "MOMENTUM_UP":
            # In strong uptrend, RSI overbought is less bearish
            if rsi < 35: score += 2
            elif rsi < 45: score += 1
            elif rsi > 85: score -= 1   # Reduced penalty
            elif rsi > 70: score -= 0.5 # Reduced penalty
        else:
            if rsi < 25: score += 3
            elif rsi < 35: score += 2
            elif rsi < 45: score += 1
            elif rsi > 80: score -= 3
            elif rsi > 70: score -= 2
            elif rsi > 60: score -= 1

    # 2. MA50 vs MA200
    if ma50 and ma200:
        gap = ((ma50 - ma200) / ma200) * 100
        if gap > 5: score += 2
        elif gap > 0: score += 1
        elif gap < -5: score -= 2
        else: score -= 1

    # 3. MACD
    if macd is not None and macd_signal is not None:
        if macd > macd_signal and macd > 0: score += 1.5
        elif macd > macd_signal: score += 0.5
        elif macd < macd_signal and macd < 0: score -= 1.5
        elif macd < macd_signal: score -= 0.5

    # 4. Bollinger Bands
    if bollinger is not None:
        if bollinger < 0.2: score += 1.5
        elif bollinger < 0.35: score += 0.5
        elif bollinger > 0.8: score -= 1.5
        elif bollinger > 0.65: score -= 0.5

    # 5. 52-week position
    if w52_pos is not None:
        if w52_pos < 0.15: score += 1.5
        elif w52_pos < 0.3: score += 0.5
        elif w52_pos > 0.85: score -= 1
        elif w52_pos > 0.7: score -= 0.5

    # 6. Trend strength
    if trend is not None:
        if trend > 0.7: score += 1
        elif trend > 0.6: score += 0.5
        elif trend < 0.3: score -= 1
        elif trend < 0.4: score -= 0.5

    # 7. Volume signal
    score += vol_signal * 0.5

    # 8. Daily change
    if change:
        if change > 4: score += 0.5
        elif change < -4: score -= 0.5

    score = max(1, min(10, round(score)))
    signal = "KOP" if score >= 7 else "SALJ" if score <= 4 else "HALL"
    return signal, score, momentum

results = {}

# Fetch Fear & Greed Index once
fg_value, fg_class = fetch_fear_greed()
fg_adj = fear_greed_signal(fg_value)

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

        signal, styrka, momentum = compute_signal(
            rsi, ma50, ma200, change,
            macd=macd, macd_signal=macd_sig,
            bollinger=bollinger, w52_pos=w52_pos,
            trend=trend, vol_signal=vol_signal
        )

        # Apply Fear & Greed for crypto
        if sym in ["BTC-USD", "ETH-USD"] and fg_adj != 0:
            styrka = max(1, min(10, styrka + fg_adj))
            signal = "KOP" if styrka >= 7 else "SALJ" if styrka <= 4 else "HALL"

        earnings_date = None

        def safe(v): return None if v is None or (isinstance(v, float) and math.isnan(v)) else v

        # ATH for commodities/crypto
        ath = None
        if sym in ["CL=F", "GC=F", "SI=F", "BTC-USD", "ETH-USD"]:
            try:
                hist_max = ticker.history(period="max")
                if len(hist_max) > 0 and "High" in hist_max.columns:
                    all_highs = [h for h in hist_max["High"].tolist() if h and not math.isnan(float(h))]
                    ath = round(max(all_highs), 2) if all_highs else None
            except:
                ath = None

        # Fetch news from multiple sources and combine
        finnhub_key = os.environ.get("FINNHUB_API_KEY", "")
        finnhub_headlines = fetch_finnhub_news(sym, finnhub_key) if finnhub_key else []
        yfinance_headlines = fetch_yfinance_news(sym)
        # Combine and deduplicate
        all_headlines = list(dict.fromkeys(finnhub_headlines + yfinance_headlines))[:8]
        news_sentiment = None
        if all_headlines:
            news_sentiment = analyze_sentiment_claude(all_headlines, sym)
            time.sleep(0.5)  # Rate limit
        news_headlines = all_headlines

        # Adjust signal strength based on news sentiment
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
        }
        print(f"OK {sym}: {price} {signal} (RSI:{rsi} Momentum:{momentum} Earnings:{earnings_date})")
    except Exception as e:
        results[sym] = {"ok": False, "error": str(e)}
        print(f"FAIL {sym}: {e}")

# Fetch and analyze Trump posts
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
