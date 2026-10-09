import time

import requests

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
BATCH_SIZE = 25
PAST_DAYS = 3  # จำนวนวันย้อนหลังที่ขอจาก API (ค่าจากโมเดล ไม่ใช่ฝนที่วัดจริง)


def _get_json(url, params, attempts=3):
    """GET แบบลองใหม่อัตโนมัติเมื่อเครือข่ายหรือเซิร์ฟเวอร์มีปัญหาชั่วคราว"""
    for attempt in range(1, attempts + 1):
        try:
            response = requests.get(url, params=params, timeout=30)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as error:
            if attempt == attempts:
                raise
            wait = 3 * attempt
            print(f"  เรียก API ไม่สำเร็จ ({type(error).__name__}) รอ {wait} วินาทีแล้วลองใหม่...")
            time.sleep(wait)


def fetch_rain_forecast(provinces, days=7, past_days=PAST_DAYS):
    """ดึงฝนรายวัน (ย้อนหลัง past_days วัน + พยากรณ์ days วัน) ของทุกจังหวัด

    คืน list เรียงตามลำดับเดียวกับ provinces
    แต่ละรายการ: {"dates": [...], "rain": [มม./วัน], "prob": [% สูงสุดของวัน]}
    ลำดับวันที่เริ่มจากวันย้อนหลังไกลสุด ไปจนถึงวันพยากรณ์สุดท้าย
    """
    results = []
    for start in range(0, len(provinces), BATCH_SIZE):
        batch = provinces[start : start + BATCH_SIZE]
        params = {
            "latitude": ",".join(str(p["lat"]) for p in batch),
            "longitude": ",".join(str(p["lon"]) for p in batch),
            "daily": "precipitation_sum,precipitation_probability_max",
            "timezone": "Asia/Bangkok",
            "forecast_days": days,
            "past_days": past_days,
        }
        data = _get_json(FORECAST_URL, params)
        if isinstance(data, dict):  # ถ้าส่งพิกัดเดียว API จะคืน dict ไม่ใช่ list
            data = [data]
        if len(data) != len(batch):
            raise ValueError(f"คาดว่าจะได้ {len(batch)} จุด แต่ได้ {len(data)}")
        for item in data:
            daily = item["daily"]
            results.append(
                {
                    "dates": daily["time"],
                    "rain": daily["precipitation_sum"],
                    "prob": daily["precipitation_probability_max"],
                }
            )
        time.sleep(1)
    return results


if __name__ == "__main__":
    sample = [{"name": "กรุงเทพมหานคร", "lat": 13.76, "lon": 100.50}]
    print(fetch_rain_forecast(sample))