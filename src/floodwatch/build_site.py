"""สร้างหน้าเว็บ Flood Watch Thailand เป็นไฟล์ HTML เดียว (site/index.html)

วิธีใช้ (รันจากโฟลเดอร์หลักของโปรเจกต์):
    python src\\floodwatch\\build_site.py                # ครบทุกอย่าง
    python src\\floodwatch\\build_site.py --skip-news --skip-ai   # โหมดเร็ว ไว้ทดสอบหน้าตา
"""

import argparse
import html
import json
import os
import re
import time
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

from dotenv import load_dotenv
from google import genai

from discharge import fetch_river_discharge
from news import fetch_flood_news
from rain import fetch_rain_forecast
from summarize import STATIONS, build_prompt, generate_with_retry

BASE_DIR = Path(__file__).resolve().parent
ROOT_DIR = BASE_DIR.parents[1]
PROVINCES_FILE = BASE_DIR / "provinces.json"
TEMPLATE_FILE = BASE_DIR / "template.html"
OUTPUT_FILE = ROOT_DIR / "site" / "index.html"

TZ = timezone(timedelta(hours=7))  # เวลาไทย (ไม่ต้องพึ่ง tzdata บน Windows)
TH_MONTHS = ["ม.ค.", "ก.พ.", "มี.ค.", "เม.ย.", "พ.ค.", "มิ.ย.",
             "ก.ค.", "ส.ค.", "ก.ย.", "ต.ค.", "พ.ย.", "ธ.ค."]

# เกณฑ์ระดับสถานการณ์จากฝนพยากรณ์รายวัน (มม.) ปรับได้ที่นี่
WATCH_MM = 35.1
ALERT_MM = 90.0
TREND_DELTA_MM = 5.0

# ชื่อที่ใช้ค้นข่าว ถ้าต่างจากชื่อจังหวัดในเมนู
SEARCH_NAME = {"กรุงเทพมหานคร": "กรุงเทพ"}


# ---------- ตัวช่วยจัดรูปแบบ ----------

def thai_day(dt):
    return f"{dt.day} {TH_MONTHS[dt.month - 1]}"


def thai_day_from_iso(iso):
    return thai_day(datetime.strptime(iso, "%Y-%m-%d"))


def thai_updated(dt):
    return f"{dt.day} {TH_MONTHS[dt.month - 1]} {dt.year + 543} · {dt:%H:%M}"


def format_published(text):
    try:
        dt = parsedate_to_datetime(text).astimezone(TZ)
    except (TypeError, ValueError):
        return ""
    return f"{thai_day(dt)} {dt:%H:%M}"


def safe_link(url):
    return url if url.startswith(("https://", "http://")) else ""


def clean_article(article):
    title = article["title"]
    source = article["source"]
    suffix = f" - {source}"
    if source and title.endswith(suffix):
        title = title[: -len(suffix)]
    return {
        "title": title,
        "link": safe_link(article["link"]),
        "source": source,
        "published": format_published(article["published"]),
    }


def text_to_html(text):
    """แปลงข้อความ Markdown ง่าย ๆ จาก AI เป็น HTML ที่ปลอดภัย"""
    text = re.sub(r"(?m)^\s*[\*\-]\s+", "• ", text.strip())
    safe = html.escape(text)
    safe = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", safe)
    safe = re.sub(r"\*(.+?)\*", r"<em>\1</em>", safe)
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", safe) if p.strip()]
    return "".join("<p>" + p.replace("\n", "<br>") + "</p>" for p in paragraphs)


# ---------- คำนวณระดับสถานการณ์ ----------

def classify(rain_today):
    if rain_today >= ALERT_MM:
        return "alert"
    if rain_today >= WATCH_MM:
        return "watch"
    return "normal"


def trend_of(rain):
    if len(rain) < 6:
        return "ทรงตัว"
    first = sum(rain[:3]) / 3
    last = sum(rain[-3:]) / 3
    if last - first >= TREND_DELTA_MM:
        return "เพิ่มขึ้น"
    if first - last >= TREND_DELTA_MM:
        return "ลดลง"
    return "ทรงตัว"


# ---------- ดึงข้อมูล ----------

def build_province_records(provinces, forecasts):
    records = []
    for province, forecast in zip(provinces, forecasts):
        rain = [round(v or 0, 1) for v in forecast["rain"]]
        prob = [v or 0 for v in forecast["prob"]]
        records.append(
            {
                "name": province["name"],
                "region": province["region"],
                "rain": rain[0],
                "prob": prob[0],
                "trend": trend_of(rain),
                "level": classify(rain[0]),
                "rain7": rain,
                "news": [],
            }
        )
    return records


def fetch_rivers():
    discharge_by_station = {}
    for name, (lat, lon) in STATIONS.items():
        try:
            discharge_by_station[name] = fetch_river_discharge(lat, lon)
        except Exception as error:
            print(f"  ข้ามสถานี {name}: {type(error).__name__}")
    return discharge_by_station


def rivers_for_chart(discharge_by_station):
    if not discharge_by_station:
        return {"labels": [], "series": []}
    first = next(iter(discharge_by_station.values()))
    return {
        "labels": [thai_day_from_iso(r["date"]) for r in first],
        "series": [
            {"name": name, "values": [r["discharge_m3s"] for r in rows]}
            for name, rows in discharge_by_station.items()
        ],
    }


def fetch_province_news(records):
    for i, record in enumerate(records, start=1):
        keyword = f"น้ำท่วม {SEARCH_NAME.get(record['name'], record['name'])}"
        try:
            articles = fetch_flood_news(keyword=keyword, days=3, limit=3)
            record["news"] = [clean_article(a) for a in articles]
        except Exception as error:
            print(f"  ข้ามข่าว {record['name']}: {type(error).__name__}")
        if i % 10 == 0:
            print(f"  ดึงข่าวแล้ว {i}/{len(records)} จังหวัด")
        time.sleep(0.7)  # เว้นช่วงไม่ให้ยิงถี่เกินไป


def generate_summary(discharge_by_station, articles, records):
    load_dotenv()
    api_key = os.getenv("GEMINI_API_KEY")
    model = os.getenv("GEMINI_MODEL", "gemini-flash-latest")
    if not api_key:
        print("  ไม่พบ GEMINI_API_KEY ข้ามการสรุปด้วย AI")
        return None

    top = sorted(records, key=lambda r: r["rain"], reverse=True)[:5]
    prompt = build_prompt(discharge_by_station, articles)
    prompt += "\n\nจังหวัดที่ฝนพยากรณ์วันนี้สูงสุด (มม.): " + ", ".join(
        f"{r['name']} {r['rain']}" for r in top
    )
    client = genai.Client(api_key=api_key)
    try:
        return generate_with_retry(client, model, prompt)
    except Exception as error:
        print(f"  สรุปด้วย AI ไม่สำเร็จ: {type(error).__name__}")
        return None


# ---------- สร้างไฟล์ HTML ----------

def render(data, summary_html, updated):
    template = TEMPLATE_FILE.read_text(encoding="utf-8")
    data_json = json.dumps(data, ensure_ascii=False).replace("<", "\\u003c")
    values = {"UPDATED": html.escape(updated), "SUMMARY": summary_html, "DATA_JSON": data_json}
    return re.sub(
        r"\{\{(UPDATED|SUMMARY|DATA_JSON)\}\}",
        lambda m: values[m.group(1)],
        template,
    )


def main():
    parser = argparse.ArgumentParser(description="สร้างหน้าเว็บ Flood Watch Thailand")
    parser.add_argument("--skip-news", action="store_true", help="ไม่ดึงข่าวรายจังหวัด (เร็วขึ้น)")
    parser.add_argument("--skip-ai", action="store_true", help="ไม่เรียก Gemini")
    args = parser.parse_args()

    provinces = json.loads(PROVINCES_FILE.read_text(encoding="utf-8"))

    print(f"1/5 ดึงฝนพยากรณ์ {len(provinces)} จังหวัด...")
    forecasts = fetch_rain_forecast(provinces)
    records = build_province_records(provinces, forecasts)
    day_labels = [thai_day_from_iso(d) for d in forecasts[0]["dates"]]

    print("2/5 ดึงปริมาณน้ำในแม่น้ำ...")
    discharge_by_station = fetch_rivers()

    print("3/5 ดึงข่าวภาพรวม...")
    try:
        national_articles = fetch_flood_news(limit=10)
    except Exception as error:
        print(f"  ดึงข่าวภาพรวมไม่สำเร็จ: {type(error).__name__}")
        national_articles = []

    if args.skip_news:
        print("4/5 ข้ามข่าวรายจังหวัด")
    else:
        print("4/5 ดึงข่าวรายจังหวัด (ใช้เวลาประมาณ 1-2 นาที)...")
        fetch_province_news(records)

    summary = None
    if args.skip_ai:
        print("5/5 ข้ามการสรุปด้วย AI")
    else:
        print("5/5 สรุปภาพรวมด้วย Gemini...")
        summary = generate_summary(discharge_by_station, national_articles, records)
    summary_html = text_to_html(summary) if summary else (
        "<p>รอบนี้ยังไม่มีสรุปจาก AI ดูตัวเลขรายจังหวัดและข่าวด้านล่างได้ตามปกติ</p>"
    )

    now = datetime.now(TZ)
    data = {
        "dayLabels": day_labels,
        "thresholds": {"watch": WATCH_MM, "alert": ALERT_MM},
        "rivers": rivers_for_chart(discharge_by_station),
        "provinces": records,
        "news": [clean_article(a) for a in national_articles[:6]],
    }

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_FILE.write_text(render(data, summary_html, thai_updated(now)), encoding="utf-8")
    print(f"เสร็จแล้ว: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
