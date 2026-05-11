"""
Markets 수집: 주식 / 환율 / 원자재 / 암호화폐 / 공포탐욕지수
- yfinance       : 주식·환율·원자재  (API key 불필요)
- CoinGecko      : 암호화폐          (API key 불필요)
- alternative.me : Fear & Greed Index (API key 불필요)
"""

import os
import time
import pandas as pd
import yfinance as yf
import requests
from datetime import date

TODAY = date.today().isoformat()

# ── 종목 정의 ──────────────────────────────────────────────────────────────

STOCKS = {
    "KOSPI":    "^KS11",
    "KOSDAQ":   "^KQ11",
    "Samsung":  "005930.KS",
    "SK_Hynix": "000660.KS",
    "Kakao":    "035720.KS",
    "Naver":    "035420.KS",
    "Hyundai":  "005380.KS",
    "SP500":    "SPY",
    "NASDAQ":   "QQQ",
    "Dow":      "DIA",
    "VIX":      "^VIX",
}

FX = {
    "USD_KRW": "KRW=X",
    "EUR_KRW": "EURKRW=X",
    "JPY_KRW": "JPYKRW=X",
    "CNY_KRW": "CNYKRW=X",
    "GBP_KRW": "GBPKRW=X",
    "DXY":     "DX-Y.NYB",
}

COMMODITIES = {
    "WTI_Crude":   "CL=F",
    "Brent_Crude": "BZ=F",
    "Gold":        "GC=F",
    "Silver":      "SI=F",
    "Copper":      "HG=F",
    "Natural_Gas": "NG=F",
    "Wheat":       "ZW=F",
    "Corn":        "ZC=F",
}

CRYPTO_IDS = "bitcoin,ethereum,binancecoin,solana,ripple"


# ── 공통 유틸 ──────────────────────────────────────────────────────────────

def save(df: pd.DataFrame, filepath: str) -> None:
    """
    실제 date 컬럼 기준 중복 방지 저장.
    이미 존재하는 날짜는 건너뛰고 신규 날짜만 append.
    """
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    if os.path.exists(filepath):
        existing_dates = set(pd.read_csv(filepath)["date"].astype(str).unique())
        new_rows = df[~df["date"].astype(str).isin(existing_dates)]
        if new_rows.empty:
            print(f"  skip: {filepath} — 신규 날짜 없음")
            return
        new_rows.to_csv(filepath, mode="a", header=False, index=False, encoding="utf-8-sig")
        print(f"  saved {len(new_rows)}행 {sorted(new_rows['date'].unique())} -> {filepath}")
    else:
        df.to_csv(filepath, mode="w", header=True, index=False, encoding="utf-8-sig")
        print(f"  saved {len(df)}행 -> {filepath}")


def fetch_yfinance(ticker_map: dict, label: str) -> list[dict]:
    """
    period="5d": 주말·공휴일에도 마지막 거래일 데이터 확보.
    date = hist.index[-1].date() (실제 거래일) — TODAY 저장 시 주말 중복 방지.
    """
    rows = []
    for name, ticker in ticker_map.items():
        try:
            hist = yf.Ticker(ticker).history(period="5d")
            if hist.empty:
                continue
            r          = hist.iloc[-1]
            trade_date = hist.index[-1].date().isoformat()
            rows.append({
                "date":   trade_date,
                "name":   name,
                "ticker": ticker,
                "open":   round(float(r["Open"]), 4),
                "high":   round(float(r["High"]), 4),
                "low":    round(float(r["Low"]), 4),
                "close":  round(float(r["Close"]), 4),
                "volume": int(r["Volume"]),
            })
        except Exception as e:
            print(f"  [WARN] {label} {ticker}: {e}")
        time.sleep(0.3)
    return rows


# ── 수집 함수 ──────────────────────────────────────────────────────────────

def collect_stocks():
    rows = fetch_yfinance(STOCKS, "stocks")
    if rows:
        save(pd.DataFrame(rows), "data/markets/stocks.csv")


def collect_fx():
    rows = fetch_yfinance(FX, "fx")
    if rows:
        save(pd.DataFrame(rows), "data/markets/fx.csv")


def collect_commodities():
    rows = fetch_yfinance(COMMODITIES, "commodities")
    if rows:
        save(pd.DataFrame(rows), "data/markets/commodities.csv")


def collect_crypto():
    """CoinGecko free API — 24/7 운영이므로 TODAY 기준 저장"""
    try:
        resp = requests.get(
            "https://api.coingecko.com/api/v3/simple/price",
            params={
                "ids":                 CRYPTO_IDS,
                "vs_currencies":       "usd,krw",
                "include_24hr_change": "true",
                "include_market_cap":  "true",
                "include_24hr_vol":    "true",
            },
            headers={"accept": "application/json"},
            timeout=15,
        )
        data = resp.json()
        rows = []
        for coin_id, vals in data.items():
            rows.append({
                "date":           TODAY,
                "coin":           coin_id,
                "price_usd":      vals.get("usd"),
                "price_krw":      vals.get("krw"),
                "change_24h_pct": vals.get("usd_24h_change"),
                "market_cap_usd": vals.get("usd_market_cap"),
                "volume_24h_usd": vals.get("usd_24h_vol"),
            })
        if rows:
            save(pd.DataFrame(rows), "data/markets/crypto.csv")
    except Exception as e:
        print(f"  [WARN] crypto: {e}")


def collect_fear_greed():
    """
    CNN Fear & Greed Index (alternative.me 무료 API, key 불필요)
    - value      : 0(극단적 공포) ~ 100(극단적 탐욕)
    - 금융 감성 분석 프로젝트에서 뉴스 감성 점수와 교차 검증용
    - limit=2: 오늘 + 어제 동시 수집 (하루 누락 시 보완)
    """
    try:
        resp = requests.get(
            "https://api.alternative.me/fng/",
            params={"limit": 2, "format": "json"},
            timeout=10,
        )
        rows = []
        for item in resp.json().get("data", []):
            rows.append({
                "date":           TODAY,                          # 수집 날짜
                "index_date":     pd.Timestamp(int(item["timestamp"]), unit="s").date().isoformat(),
                "value":          int(item["value"]),
                "classification": item["value_classification"],  # Extreme Fear/Fear/Neutral/Greed/Extreme Greed
            })
        if rows:
            save(pd.DataFrame(rows), "data/markets/fear_greed.csv")
    except Exception as e:
        print(f"  [WARN] fear & greed: {e}")


# ── 진입점 ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print(f"=== Markets Collection: {TODAY} ===")
    collect_stocks()
    collect_fx()
    collect_commodities()
    collect_crypto()
    collect_fear_greed()
    print("Done.")
