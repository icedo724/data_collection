"""
Public Data 수집: 교통(지하철·버스) / 한국은행 거시경제 지표
- secrets: SEOUL_DATA_API_KEY  (data.seoul.go.kr)
           BOK_API_KEY         (ecos.bok.or.kr — 한국은행 경제통계시스템)
"""

import os
import pandas as pd
import requests
from datetime import date, timedelta

TODAY     = date.today().isoformat()
YESTERDAY = (date.today() - timedelta(days=1)).strftime("%Y%m%d")  # YYYYMMDD (서울 API 형식)


def save(df: pd.DataFrame, filepath: str, check_val: str = None) -> None:
    """
    check_val 날짜가 이미 존재하면 스킵, 없으면 append.
    subway/bus는 YYYYMMDD 형식 날짜를 check_val로 전달.
    """
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    key = check_val or TODAY
    if os.path.exists(filepath):
        if key in pd.read_csv(filepath)["date"].astype(str).values:
            print(f"  skip: {filepath} already has {key}")
            return
        df.to_csv(filepath, mode="a", header=False, index=False, encoding="utf-8-sig")
    else:
        df.to_csv(filepath, mode="w", header=True, index=False, encoding="utf-8-sig")
    print(f"  saved {len(df)}행 -> {filepath}")


# ── 서울 지하철 승하차 인원 ────────────────────────────────────────────────

def collect_subway():
    api_key = os.environ.get("SEOUL_DATA_API_KEY")
    if not api_key:
        print("  [SKIP] Subway: SEOUL_DATA_API_KEY missing")
        return

    try:
        url = f"http://openapi.seoul.go.kr:8088/{api_key}/json/CardSubwayStatsNew/1/1000/{YESTERDAY}"
        resp = requests.get(url, timeout=20)
        items = resp.json().get("CardSubwayStatsNew", {}).get("row", [])
        rows = [{
            "date":           YESTERDAY,
            "line":           it.get("LINE_NUM", ""),
            "station":        it.get("SUB_STA_NM", ""),
            "passengers_on":  it.get("RIDE_PASGR_NUM", 0),
            "passengers_off": it.get("ALIGHT_PASGR_NUM", 0),
        } for it in items]

        if rows:
            save(pd.DataFrame(rows), "data/public/subway.csv", check_val=YESTERDAY)
    except Exception as e:
        print(f"  [WARN] subway: {e}")


# ── 서울 버스 승하차 인원 ─────────────────────────────────────────────────

def collect_bus():
    api_key = os.environ.get("SEOUL_DATA_API_KEY")
    if not api_key:
        print("  [SKIP] Bus: SEOUL_DATA_API_KEY missing")
        return

    try:
        url = f"http://openapi.seoul.go.kr:8088/{api_key}/json/CardBusStatisticsServiceNew/1/1000/{YESTERDAY}"
        resp = requests.get(url, timeout=20)
        items = resp.json().get("CardBusStatisticsServiceNew", {}).get("row", [])
        rows = [{
            "date":           YESTERDAY,
            "route_id":       it.get("BUS_ROUTE_ID", ""),
            "route_name":     it.get("BUS_ROUTE_NM", ""),
            "route_type":     it.get("ROUTE_TYPE_NM", ""),
            "passengers_on":  it.get("RIDE_PASGR_NUM", 0),
            "passengers_off": it.get("ALIGHT_PASGR_NUM", 0),
        } for it in items]

        if rows:
            save(pd.DataFrame(rows), "data/public/bus.csv", check_val=YESTERDAY)
    except Exception as e:
        print(f"  [WARN] bus: {e}")


# ── 한국은행 ECOS 거시경제 지표 ───────────────────────────────────────────

def collect_bok_indicators():
    """
    한국은행 경제통계시스템 (ECOS) API
    발급: https://ecos.bok.or.kr/ → 로그인 → API 인증키 신청 (무료)

    수집 지표:
    - 기준금리       (일별) stat: 722Y001  item: 0101000
    - USD/KRW 시장평균(일별) stat: 731Y003  item: 0000001
    - 소비자물가(CPI) (월별) stat: 021Y126  item: 0
    - 실업률         (월별) stat: 901Y027  item: I62B
    - 수출           (월별) stat: 301Y013  item: X
    - 수입           (월별) stat: 301Y013  item: M
    """
    api_key = os.environ.get("BOK_API_KEY")
    if not api_key:
        print("  [SKIP] BOK: BOK_API_KEY missing")
        return

    base      = f"https://ecos.bok.or.kr/api/StatisticSearch/{api_key}/json/kr"
    today_fmt = date.today().strftime("%Y%m%d")
    m_start   = date.today().replace(day=1).strftime("%Y%m%d")
    m6_ago    = (date.today().replace(day=1) - timedelta(days=180)).strftime("%Y%m%d")

    stats = [
        ("722Y001", "DD", m_start, today_fmt, "0101000", "기준금리"),
        ("731Y003", "DD", m_start, today_fmt, "0000001", "USD_KRW"),
        ("021Y126", "MM", m6_ago,  today_fmt, "0",       "CPI"),
        ("901Y027", "MM", m6_ago,  today_fmt, "I62B",    "실업률"),
        ("301Y013", "MM", m6_ago,  today_fmt, "X",       "수출"),
        ("301Y013", "MM", m6_ago,  today_fmt, "M",       "수입"),
    ]

    rows = []
    for stat_code, cycle, start, end, item_code, label in stats:
        try:
            url = f"{base}/1/100/{stat_code}/{cycle}/{start}/{end}/{item_code}"
            resp = requests.get(url, timeout=15)
            for it in resp.json().get("StatisticSearch", {}).get("row", []):
                rows.append({
                    "date":      it.get("TIME", ""),
                    "indicator": label,
                    "value":     it.get("DATA_VALUE"),
                    "unit":      it.get("UNIT_NAME", ""),
                    "cycle":     cycle,
                })
        except Exception as e:
            print(f"  [WARN] BOK {label}: {e}")

    if rows:
        fp = "data/public/bok_indicators.csv"
        os.makedirs(os.path.dirname(fp), exist_ok=True)
        df_new = pd.DataFrame(rows)

        if os.path.exists(fp):
            existing = pd.read_csv(fp)
            # date + indicator 조합 기준 중복 제거: 신규 데이터만 append
            merged = pd.concat([existing, df_new]).drop_duplicates(
                subset=["date", "indicator"], keep="last"
            )
            merged.to_csv(fp, index=False, encoding="utf-8-sig")
            added = len(merged) - len(existing)
            print(f"  saved {added}행 신규 -> {fp} (전체 {len(merged)}행)")
        else:
            df_new.to_csv(fp, index=False, encoding="utf-8-sig")
            print(f"  saved {len(df_new)}행 -> {fp}")


# ── 진입점 ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print(f"=== Public Data Collection: {TODAY} (transport: {YESTERDAY}) ===")
    collect_subway()
    collect_bus()
    collect_bok_indicators()
    print("Done.")
