import yfinance as yf
import json
import urllib.request
import math
from datetime import datetime, timezone, timedelta

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

STOCKS = [
    "INVE-B.ST", "ATCO-B.ST", "SWED-A.ST", "SAAB-B.ST", "ERIC-B.ST",
    "VOLV-B.ST", "KINV-B.ST", "HM-B.ST", "SEB-A.ST", "TEL2-B.ST", "BEAMMW-B.ST", "NANEXA.ST",
    "ASML", "SAP", "NVO", "LVMUY", "SHEL", "SIEGY", "NSRGY", "EADSY", "AZN", "RELX", "BAESY",
    "NVDA", "AAPL", "MSFT", "AMZN", "GOOGL", "META", "TSLA", "JPM", "BRK-B", "LLY",
    "BABA", "TCEHY", "PDD", "BYDDF", "JD",
    "TSM", "CAMT",
    "TM", "SONY", "NTDOY", "FANUY", "MUFG",
    "005930.KS", "005380.KS", "000660.KS",
    "CL=F", "GC=F", "SI=F", "BTC-USD", "ETH-USD",
    "CSPX.L", "EQQQ.DE", "XACT-OMXS30.ST", "XACTHDIV.ST", "SMH", "DFNS.L", "VWRL.L", "IEMG", "IQQH.DE", "IGLN.L",
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
    price_change = (closes[-1] - closes[-2]) / closes[-2] if len(closes) > 1 else 0
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
        hist = ticker.history(period="1y")
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

        results[sym] = {
            "price": price, "change": change,
            "rsi": safe(rsi), "ma50": safe(ma50), "ma200": safe(ma200),
            "macd": round(macd, 3) if macd and not math.isnan(macd) else None,
            "bollinger": safe(bollinger),
            "w52": safe(w52_pos),
            "trend": safe(trend),
            "signal": signal, "styrka": styrka, "ok": True,
            "ath": ath,
            "momentum": momentum,
            "earnings_date": earnings_date,
        }
        print(f"OK {sym}: {price} {signal} (RSI:{rsi} Momentum:{momentum} Earnings:{earnings_date})")
    except Exception as e:
        results[sym] = {"ok": False, "error": str(e)}
        print(f"FAIL {sym}: {e}")

output = {
    "updated": (datetime.now(timezone.utc) + timedelta(hours=2)).strftime("%Y-%m-%d %H:%M svensk tid"),
    "stocks": results,
    "fear_greed": {"value": fg_value, "classification": fg_class} if fg_value else None
}

with open("data.json", "w") as f:
    json.dump(output, f)

print(f"\nDone: {sum(1 for v in results.values() if v.get('ok'))} / {len(results)} succeeded")
