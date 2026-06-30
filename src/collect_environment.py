"""
Environment 수집 (API 키 불필요): 날씨 / 대기질 — 전부 Open-Meteo

- Open-Meteo Weather      : https://open-meteo.com/  (key 불필요, 10k req/day)
- Open-Meteo Air Quality  : https://open-meteo.com/en/docs/air-quality-api

날씨는 기존 weather.csv 스키마(°C·%·hPa·m/s·mm)와 호환되어 그대로 이어서 누적한다.
대기질은 기존 에어코리아(ppm·서울 4곳)와 가스 단위(µg/m³)가 달라 새 스키마로 누적한다.
"""

import os
import pandas as pd
import requests
from datetime import date

TODAY = date.today().isoformat()

# 기존 수집과 동일한 9개 도시 (위·경도)
CITIES = {
    "Seoul":   (37.5665, 126.9780),
    "Busan":   (35.1796, 129.0756),
    "Incheon": (37.4563, 126.7052),
    "Daegu":   (35.8714, 128.6014),
    "Daejeon": (36.3504, 127.3845),
    "Gwangju": (35.1595, 126.8526),
    "Ulsan":   (35.5384, 129.3114),
    "Suwon":   (37.2636, 127.0286),
    "Jeju":    (33.4996, 126.5312),
}


def save(df: pd.DataFrame, filepath: str) -> None:
    """date 컬럼 기준 중복 방지 저장 (당일 1회만 누적)."""
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    if os.path.exists(filepath):
        if TODAY in pd.read_csv(filepath)["date"].astype(str).values:
            print(f"  skip: {filepath} already has {TODAY}")
            return
        df.to_csv(filepath, mode="a", header=False, index=False, encoding="utf-8-sig")
    else:
        df.to_csv(filepath, mode="w", header=True, index=False, encoding="utf-8-sig")
    print(f"  saved {len(df)} rows -> {filepath}")


# ── 날씨 (Open-Meteo, 무키) ───────────────────────────────────────────────

# WMO weather code -> (main, description) — 기존 weather_main/desc와 유사하게 매핑
WMO = {
    0: ("Clear", "clear sky"),
    1: ("Clouds", "mainly clear"), 2: ("Clouds", "partly cloudy"), 3: ("Clouds", "overcast"),
    45: ("Fog", "fog"), 48: ("Fog", "depositing rime fog"),
    51: ("Drizzle", "light drizzle"), 53: ("Drizzle", "moderate drizzle"), 55: ("Drizzle", "dense drizzle"),
    56: ("Drizzle", "light freezing drizzle"), 57: ("Drizzle", "dense freezing drizzle"),
    61: ("Rain", "slight rain"), 63: ("Rain", "moderate rain"), 65: ("Rain", "heavy rain"),
    66: ("Rain", "light freezing rain"), 67: ("Rain", "heavy freezing rain"),
    71: ("Snow", "slight snow"), 73: ("Snow", "moderate snow"), 75: ("Snow", "heavy snow"),
    77: ("Snow", "snow grains"),
    80: ("Rain", "slight rain showers"), 81: ("Rain", "moderate rain showers"), 82: ("Rain", "violent rain showers"),
    85: ("Snow", "slight snow showers"), 86: ("Snow", "heavy snow showers"),
    95: ("Thunderstorm", "thunderstorm"),
    96: ("Thunderstorm", "thunderstorm with slight hail"), 99: ("Thunderstorm", "thunderstorm with heavy hail"),
}


def collect_weather():
    rows = []
    for city, (lat, lon) in CITIES.items():
        try:
            resp = requests.get(
                "https://api.open-meteo.com/v1/forecast",
                params={
                    "latitude":        lat,
                    "longitude":       lon,
                    "current":         "temperature_2m,relative_humidity_2m,apparent_temperature,"
                                       "precipitation,rain,snowfall,weather_code,cloud_cover,"
                                       "pressure_msl,wind_speed_10m,wind_direction_10m",
                    "daily":           "temperature_2m_max,temperature_2m_min",
                    "wind_speed_unit": "ms",
                    "timezone":        "Asia/Seoul",
                    "forecast_days":   1,
                },
                timeout=15,
            )
            d = resp.json()
            cur   = d.get("current", {})
            daily = d.get("daily", {})
            code  = cur.get("weather_code")
            main, desc = WMO.get(code, ("Unknown", f"code {code}"))
            rows.append({
                # 기존 weather.csv 스키마와 동일한 컬럼 순서 유지
                "date":         TODAY,
                "city":         city,
                "temp":         cur.get("temperature_2m"),
                "feels_like":   cur.get("apparent_temperature"),
                "temp_min":     (daily.get("temperature_2m_min") or [None])[0],
                "temp_max":     (daily.get("temperature_2m_max") or [None])[0],
                "humidity":     cur.get("relative_humidity_2m"),
                "pressure":     cur.get("pressure_msl"),
                "weather_main": main,
                "weather_desc": desc,
                "wind_speed":   cur.get("wind_speed_10m"),
                "wind_deg":     cur.get("wind_direction_10m"),
                "clouds_pct":   cur.get("cloud_cover"),
                "visibility_m": "",                              # Open-Meteo current 미제공
                "rain_1h_mm":   cur.get("rain", 0),
                "snow_1h_mm":   cur.get("snowfall", 0),
            })
        except Exception as e:
            print(f"  [WARN] weather {city}: {e}")

    if rows:
        save(pd.DataFrame(rows), "data/environment/weather.csv")


# ── 대기질 (Open-Meteo Air Quality, 무키) ─────────────────────────────────

def _pm_grade(value, bounds) -> str:
    """한국 환경부 등급 기준: 1=좋음 2=보통 3=나쁨 4=매우나쁨."""
    if value is None:
        return ""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return ""
    for grade, upper in enumerate(bounds, start=1):
        if v <= upper:
            return str(grade)
    return str(len(bounds) + 1)


def collect_air_quality():
    rows = []
    for city, (lat, lon) in CITIES.items():
        try:
            resp = requests.get(
                "https://air-quality-api.open-meteo.com/v1/air-quality",
                params={
                    "latitude":  lat,
                    "longitude": lon,
                    "current":   "pm10,pm2_5,ozone,nitrogen_dioxide,sulphur_dioxide,"
                                 "carbon_monoxide,european_aqi",
                    "timezone":  "Asia/Seoul",
                },
                timeout=15,
            )
            cur = resp.json().get("current", {})
            pm10 = cur.get("pm10")
            pm25 = cur.get("pm2_5")
            rows.append({
                # 가스 농도 단위는 µg/m³ (에어코리아 ppm과 다름)
                "date":       TODAY,
                "city":       city,
                "pm10":       pm10,
                "pm10_grade": _pm_grade(pm10, [30, 80, 150]),
                "pm25":       pm25,
                "pm25_grade": _pm_grade(pm25, [15, 35, 75]),
                "o3":         cur.get("ozone"),
                "no2":        cur.get("nitrogen_dioxide"),
                "so2":        cur.get("sulphur_dioxide"),
                "co":         cur.get("carbon_monoxide"),
                "eu_aqi":     cur.get("european_aqi"),
            })
        except Exception as e:
            print(f"  [WARN] air quality {city}: {e}")

    if rows:
        save(pd.DataFrame(rows), "data/environment/air_quality.csv")


# ── 진입점 ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print(f"=== Environment Collection (no-key): {TODAY} ===")
    collect_weather()
    collect_air_quality()
    print("Done.")
