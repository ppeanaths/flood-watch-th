"""สร้างหน้าเว็บ Flood Watch Thailand เป็นไฟล์ HTML เดียว (site/index.html)

วิธีใช้ (รันจากโฟลเดอร์หลักของโปรเจกต์):
    python3 src/floodwatch/build_site.py                          # ครบทุกอย่าง
    python3 src/floodwatch/build_site.py --skip-news --skip-ai    # โหมดเร็ว ไว้ทดสอบหน้าตา
"""

import argparse
import html
import json
import os
import re
import time
from datetime import datetime
from email.utils import parsedate_to_datetime
from pathlib import Path

from dotenv import load_dotenv
from google import genai

from discharge import fetch_river_discharge
from news import fetch_flood_news
from rain import PAST_DAYS, fetch_rain_forecast
from summarize import TH_MONTHS, TZ, STATIONS, build_prompt, generate_with_retry

BASE_DIR = Path(__file__).resolve().parent
ROOT_DIR = BASE_DIR.parents[1]
PROVINCES_FILE = BASE_DIR / "provinces.json"
TEMPLATE_FILE = BASE_DIR / "template.html"
OUTPUT_FILE = ROOT_DIR / "site" / "index.html"

# ---------- เกณฑ์ระดับฝน (ปรับได้ที่นี่) ----------
# ฝนวันนี้ (มม./วัน) อิงการแบ่งระดับฝนรายวันของกรมอุตุนิยมวิทยา: ฝนหนัก 35.1-90, ฝนหนักมาก มากกว่า 90
WATCH_MM = 35.1
ALERT_MM = 90.0
# ฝนสะสม 3 วัน (วันนี้ + ย้อนหลัง 2 วัน) เป็นเกณฑ์ของโปรเจกต์นี้เอง ไม่ใช่เกณฑ์ทางการ
ACC_WATCH_MM = 100.0
ACC_ALERT_MM = 200.0
TREND_DELTA_MM = 5.0

# ---------- ข่าวรายจังหวัด ----------
NEWS_CANDIDATES = 10  # ดึงมากี่ข่าวก่อนกรอง
NEWS_PER_PROVINCE = 3  # เก็บไว้แสดงกี่ข่าวหลังกรอง
SEARCH_NAME = {"กรุงเทพมหานคร": "กรุงเทพ"}  # ชื่อที่ใช้ค้นข่าว ถ้าต่างจากชื่อในเมนู
ALIASES = {  # ชื่อเรียกอื่นที่พบในหัวข้อข่าว
    "กรุงเทพมหานคร": ["กรุงเทพ", "กทม"],
    "พระนครศรีอยุธยา": ["อยุธยา"],
    "นครราชสีมา": ["โคราช"],
    "อุบลราชธานี": ["อุบล"],
    "สุราษฎร์ธานี": ["สุราษฎร์"],
    "ประจวบคีรีขันธ์": ["ประจวบ"],
    "นครศรีธรรมราช": ["นครศรี"],
}
AMBIGUOUS = {"เลย", "ตาก"}  # ชื่อจังหวัดที่เป็นคำสามัญ ต้องมี จ./จังหวัด/เมือง นำหน้า
FLOOD_WORDS = ("ท่วม", "น้ำป่า", "น้ำหลาก", "อุทกภัย", "ดินโคลน", "ดินสไลด์", "น้ำเอ่อ", "น้ำล้น")


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


# ---------- คำนวณระดับฝน ----------

def classify(rain_today, acc3):
    if rain_today >= ALERT_MM or acc3 >= ACC_ALERT_MM:
        return "alert"
    if rain_today >= WATCH_MM or acc3 >= ACC_WATCH_MM:
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


def locate_today(dates):
    """หาตำแหน่งของวันนี้ (เวลาไทย) ในลิสต์วันที่ ถ้าไม่เจอใช้ตำแหน่งตามจำนวนวันย้อนหลัง"""
    today = datetime.now(TZ).strftime("%Y-%m-%d")
    if today in dates:
        return dates.index(today)
    return min(PAST_DAYS, len(dates) - 1)


def build_days(dates, start, idx):
    days = []
    for i in range(start, len(dates)):
        d = datetime.strptime(dates[i], "%Y-%m-%d")
        kind = "past" if i < idx else ("today" if i == idx else "future")
        days.append({"day": str(d.day), "month": TH_MONTHS[d.month - 1], "kind": kind})
    return days


def build_province_records(provinces, forecasts, start, idx):
    past_n = idx - start
    records = []
    for province, forecast in zip(provinces, forecasts):
        series = [round(v or 0, 1) for v in forecast["rain"][start:]]
        today_rain = series[past_n]
        acc3 = round(sum(series[max(0, past_n - 2): past_n + 1]), 1)
        prob = forecast["prob"][idx] or 0
        records.append(
            {
                "name": province["name"],
                "region": province["region"],
                "rain": today_rain,
                "acc3": acc3,
                "prob": prob,
                "trend": trend_of(series[past_n:]),
                "level": classify(today_rain, acc3),
                "series": series,
                "news": [],
            }
        )
    return records


# ---------- ดึงข้อมูล ----------

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


def is_relevant(title, name):
    """หัวข้อข่าวต้องมีคำเกี่ยวกับน้ำท่วม และระบุชื่อจังหวัดนั้นจริง"""
    if not any(word in title for word in FLOOD_WORDS):
        return False
    if name in AMBIGUOUS:
        return any(prefix + name in title for prefix in ("จ.", "จังหวัด", "เมือง"))
    return any(n in title for n in [name] + ALIASES.get(name, []))


def fetch_province_news(records):
    for i, record in enumerate(records, start=1):
        name = record["name"]
        keyword = f"น้ำท่วม {SEARCH_NAME.get(name, name)}"
        try:
            articles = fetch_flood_news(keyword=keyword, days=3, limit=NEWS_CANDIDATES)
            cleaned = [clean_article(a) for a in articles]
            relevant = [a for a in cleaned if is_relevant(a["title"], name)]
            record["news"] = relevant[:NEWS_PER_PROVINCE]
        except Exception as error:
            print(f"  ข้ามข่าว {name}: {type(error).__name__}")
        if i % 10 == 0:
            print(f"  ดึงข่าวแล้ว {i}/{len(records)} จังหวัด")
        time.sleep(0.7)  # เว้นช่วงไม่ให้ยิงถี่เกินไป


def prompt_extras(records, news_fetched):
    def top(key):
        ranked = sorted(records, key=lambda r: r[key], reverse=True)[:5]
        return ", ".join(f"{r['name']} {r[key]}" for r in ranked)

    levels = {lv: sum(1 for r in records if r["level"] == lv) for lv in ("alert", "watch", "normal")}
    lines = [
        "ฝนพยากรณ์วันนี้ (มม.) 5 จังหวัดสูงสุด: " + top("rain"),
        "ฝนสะสม 3 วัน (วันนี้ + ย้อนหลัง 2 วัน, ค่าจากโมเดล, มม.) 5 จังหวัดสูงสุด: " + top("acc3"),
        f"จำนวนจังหวัดตามระดับฝน: ฝนหนักมาก {levels['alert']}, ฝนหนัก {levels['watch']}, ฝนไม่หนัก {levels['normal']} "
        "(ระดับนี้วัดจากปริมาณฝนเท่านั้น ไม่ได้บอกว่าจังหวัดนั้นกำลังน้ำท่วม)",
    ]
    if news_fetched:
        with_news = [r["name"] for r in records if r["news"]]
        if with_news:
            lines.append(
                f"จังหวัดที่พบหัวข้อข่าวน้ำท่วมซึ่งระบุชื่อจังหวัดใน 3 วันล่าสุด: {len(with_news)} จังหวัด "
                f"({', '.join(with_news)}) นับจากหัวข้อข่าวเท่านั้น ไม่ใช่จำนวนจังหวัดที่ถูกน้ำท่วมจริง"
            )
        else:
            lines.append("ไม่พบหัวข้อข่าวน้ำท่วมที่ระบุชื่อจังหวัดใน 3 วันล่าสุด")
    return lines


def generate_summary(discharge_by_station, articles, records, news_fetched):
    load_dotenv()
    api_key = os.getenv("GEMINI_API_KEY")
    model = os.getenv("GEMINI_MODEL", "gemini-flash-latest")
    if not api_key:
        print("  ไม่พบ GEMINI_API_KEY ข้ามการสรุปด้วย AI")
        return None

    prompt = build_prompt(discharge_by_station, articles, prompt_extras(records, news_fetched))
    client = genai.Client(api_key=api_key)
    try:
        return generate_with_retry(client, model, prompt)
    except Exception as error:
        code = getattr(error, "code", "")
        status = getattr(error, "status", "")
        print(f"  สรุปด้วย AI ไม่สำเร็จ: {type(error).__name__} {code} {status}")
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

    print(f"1/5 ดึงฝนพยากรณ์และฝนย้อนหลัง {len(provinces)} จังหวัด...")
    forecasts = fetch_rain_forecast(provinces)
    dates = forecasts[0]["dates"]
    idx = locate_today(dates)
    start = max(0, idx - PAST_DAYS)
    records = build_province_records(provinces, forecasts, start, idx)
    days = build_days(dates, start, idx)

    print("2/5 ดึงปริมาณน้ำในแม่น้ำ...")
    discharge_by_station = fetch_rivers()

    print("3/5 ดึงข่าวภาพรวม...")
    try:
        national_articles = fetch_flood_news(limit=10)
    except Exception as error:
        print(f"  ดึงข่าวภาพรวมไม่สำเร็จ: {type(error).__name__}")
        national_articles = []

    news_fetched = not args.skip_news
    if news_fetched:
        print("4/5 ดึงข่าวรายจังหวัด (ใช้เวลาประมาณ 1-2 นาที)...")
        fetch_province_news(records)
        print(f"  พบข่าวที่ระบุชื่อจังหวัด {sum(1 for r in records if r['news'])} จังหวัด")
    else:
        print("4/5 ข้ามข่าวรายจังหวัด")

    summary = None
    if args.skip_ai:
        print("5/5 ข้ามการสรุปด้วย AI")
    else:
        print("5/5 สรุปภาพรวมด้วย Gemini...")
        summary = generate_summary(discharge_by_station, national_articles, records, news_fetched)
    summary_html = text_to_html(summary) if summary else (
        "<p>รอบนี้ยังไม่มีสรุปจาก AI ดูตัวเลขรายจังหวัดและข่าวด้านล่างได้ตามปกติ</p>"
    )

    now = datetime.now(TZ)
    data = {
        "days": days,
        "thresholds": {
            "watch": WATCH_MM,
            "alert": ALERT_MM,
            "accWatch": ACC_WATCH_MM,
            "accAlert": ACC_ALERT_MM,
        },
        "newsFetched": news_fetched,
        "rivers": rivers_for_chart(discharge_by_station),
        "provinces": records,
        "news": [clean_article(a) for a in national_articles[:6]],
    }

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_FILE.write_text(render(data, summary_html, thai_updated(now)), encoding="utf-8")
    print(f"เสร็จแล้ว: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()