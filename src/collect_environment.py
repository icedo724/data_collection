"""
Environment 수집: 날씨 / 대기질 / 유가(오피넷) / 전력수요
- secrets: OPENWEATHER_API_KEY
           PUBLIC_DATA_API_KEY   (data.go.kr — 에어코리아, 오피넷 공용)
           OPINET_API_KEY        (오피넷 전용 키. data.go.kr 키와 다를 수 있음)
"""

import os
import pandas as pd
import requests
from datetime import date

TODAY = date.today().isoformat()


def save(df: pd.DataFrame, filepath: str) -> None:
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    if os.path.exists(filepath):
        if TODAY in pd.read_csv(filepath)["date"].astype(str).values:
            print(f"  skip: {filepath} already has {TODAY}")
            return
        df.to_csv(filepath, mode="a", header=False, index=False, encoding="utf-8-sig")
    else:
        df.to_csv(filepath, mode="w", header=True, index=False, encoding="utf-8-sig")
    print(f"  saved {len(df)} rows -> {filepath}")


# ── 날씨 (OpenWeatherMap) ─────────────────────────────────────────────────

CITIES = {
    "Seoul":    (37.5665, 126.9780),
    "Busan":    (35.1796, 129.0756),
    "Incheon":  (37.4563, 126.7052),
    "Daegu":    (35.8714, 128.6014),
    "Daejeon":  (36.3504, 127.3845),
    "Gwangju":  (35.1595, 126.8526),
    "Ulsan":    (35.5384, 129.3114),
    "Suwon":    (37.2636, 127.0286),
    "Jeju":     (33.4996, 126.5312),
}


def collect_weather():
    api_key = os.environ.get("OPENWEATHER_API_KEY")
    if not api_key:
        print("  [SKIP] Weather: OPENWEATHER_API_KEY missing")
        return

    rows = []
    for city, (lat, lon) in CITIES.items():
        try:
            resp = requests.get(
                "https://api.openweathermap.org/data/2.5/weather",
                params={"lat": lat, "lon": lon, "appid": api_key, "units": "metric"},
                timeout=10,
            )
            d = resp.json()
            rows.append({
                "date":         TODAY,
                "city":         city,
                "temp":         d["main"]["temp"],
                "feels_like":   d["main"]["feels_like"],
                "temp_min":     d["main"]["temp_min"],
                "temp_max":     d["main"]["temp_max"],
                "humidity":     d["main"]["humidity"],
                "pressure":     d["main"]["pressure"],
                "weather_main": d["weather"][0]["main"],
                "weather_desc": d["weather"][0]["description"],
                "wind_speed":   d["wind"]["speed"],
                "wind_deg":     d["wind"].get("deg"),
                "clouds_pct":   d["clouds"]["all"],
                "visibility_m": d.get("visibility"),
                "rain_1h_mm":   d.get("rain", {}).get("1h", 0),
                "snow_1h_mm":   d.get("snow", {}).get("1h", 0),
            })
        except Exception as e:
            print(f"  [WARN] weather {city}: {e}")

    if rows:
        save(pd.DataFrame(rows), "data/environment/weather.csv")


# ── 대기질 (에어코리아 / data.go.kr) ─────────────────────────────────────

AIR_STATIONS = [
    "종로구", "중구",   "강남구", "강서구",  # 서울
    "부산진구", "해운대구",                  # 부산
    "서구",                                  # 인천
    "유성구",                                # 대전
    "북구",                                  # 대구·광주 공용 (서버에서 지역 구분)
    "제주시",                                # 제주
]


def collect_air_quality():
    api_key = os.environ.get("PUBLIC_DATA_API_KEY")
    if not api_key:
        print("  [SKIP] Air quality: PUBLIC_DATA_API_KEY missing")
        return

    rows = []
    for station in AIR_STATIONS:
        try:
            resp = requests.get(
                "http://apis.data.go.kr/B552584/ArpltnInforInqireSvc/getMsrstnAcctoRltmMesureDnsty",
                params={
                    "serviceKey":  api_key,
                    "returnType":  "json",
                    "numOfRows":   "1",
                    "pageNo":      "1",
                    "stationName": station,
                    "dataTerm":    "DAILY",
                    "ver":         "1.3",
                },
                timeout=10,
            )
            items = resp.json().get("response", {}).get("body", {}).get("items", [])
            if not items:
                continue
            it = items[0]
            rows.append({
                "date":       TODAY,
                "station":    station,
                "pm10":       it.get("pm10Value"),
                "pm10_grade": it.get("pm10Grade"),
                "pm25":       it.get("pm25Value"),
                "pm25_grade": it.get("pm25Grade"),
                "o3":         it.get("o3Value"),
                "o3_grade":   it.get("o3Grade"),
                "no2":        it.get("no2Value"),
                "so2":        it.get("so2Value"),
                "co":         it.get("coValue"),
                "khai":       it.get("khaiValue"),     # 통합대기환경지수
                "khai_grade": it.get("khaiGrade"),
                "data_time":  it.get("dataTime"),
            })
        except Exception as e:
            print(f"  [WARN] air quality {station}: {e}")

    if rows:
        save(pd.DataFrame(rows), "data/environment/air_quality.csv")


# ── 유가 (오피넷 / 한국석유공사) ─────────────────────────────────────────

def collect_oil_price():
    """
    오피넷 전국 평균 유가 API
    발급: https://www.opinet.co.kr/user/main/mainView.do → 오픈API → 이용신청
    (data.go.kr 키와 별도로 오피넷 전용 API 키 필요)
    """
    api_key = os.environ.get("OPINET_API_KEY")
    if not api_key:
        print("  [SKIP] Oil price: OPINET_API_KEY missing")
        return

    # 전국 평균가 (휘발유·경유·등유·LPG)
    prod_map = {
        "B027": "휘발유",
        "D047": "경유",
        "C004": "등유",
        "K015": "LPG",
    }
    rows = []

    for prod_cd, prod_name in prod_map.items():
        try:
            resp = requests.get(
                "https://www.opinet.co.kr/api/avgAllPrice.do",
                params={"code": api_key, "out": "json", "prodcd": prod_cd},
                timeout=10,
            )
            items = resp.json().get("RESULT", {}).get("OIL", [])
            for it in items:
                rows.append({
                    "date":      TODAY,
                    "fuel_type": prod_name,
                    "price_krw": it.get("PRICE"),
                    "diff":      it.get("DIFF"),    # 전일 대비 변동
                    "area":      it.get("AREA_NM", "전국"),
                })
        except Exception as e:
            print(f"  [WARN] oil price {prod_name}: {e}")

    if rows:
        save(pd.DataFrame(rows), "data/environment/oil_price.csv")


# ── 진입점 ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print(f"=== Environment Collection: {TODAY} ===")
    collect_weather()
    collect_air_quality()
    collect_oil_price()
    print("Done.")
