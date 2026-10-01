# Flood Watch Thailand

A Python project that collects rainfall forecasts, river-flow forecasts and flood news for Thailand, then builds a single static web page: an AI-written national summary plus a per-province view for all 77 provinces (with quick links for Bangkok and the surrounding provinces).

> สรุปสถานการณ์ฝนและข่าวน้ำท่วมรายจังหวัด (77 จังหวัด) สร้างเป็นหน้าเว็บเดียวด้วย Python
> ระดับ ปกติ / เฝ้าระวัง / เตือนภัย ในโปรเจกต์นี้คำนวณเองจากฝนพยากรณ์ ไม่ใช่ประกาศเตือนภัยอย่างเป็นทางการ

## What it does

- Fetches the 7-day rainfall forecast for every province from [Open-Meteo](https://open-meteo.com/).
- Fetches 7-day river-discharge forecasts (GloFAS model) for two Chao Phraya reference points.
- Collects recent flood headlines from Google News RSS (title and link only, no article text) for the whole country and for each province.
- Asks Gemini for a short national summary, using only the data it is given.
- Renders everything into `site/index.html`: a province dropdown, Bangkok-area shortcuts, a 7-day rain chart per province, a river chart and a news list.

## How it works

```
provinces.json ──► rain.py ─────────┐
                   discharge.py ────┤
                   news.py ─────────┼──► build_site.py ──► site/index.html
                   summarize.py ────┘     (template.html)
                   (Gemini prompt + retry)
```

Status levels come from today's forecast rainfall. The thresholds are constants at the top of `build_site.py` (`WATCH_MM`, `ALERT_MM`) and are this project's own rule of thumb, not an official warning system.

## Setup

Requires Python 3.12 or newer.

```powershell
# Windows PowerShell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

```bash
# macOS / Linux
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Create a `.env` file in the project root (it is git-ignored):

```
GEMINI_API_KEY=your-key-here
GEMINI_MODEL=gemini-flash-latest
```

The AI summary is optional. Without a key the page is still built, with a placeholder where the summary would be.

## Usage

```powershell
# Full build (rain + rivers + news for all provinces + AI summary)
python src\floodwatch\build_site.py

# Quick build for checking layout changes (no per-province news, no AI)
python src\floodwatch\build_site.py --skip-news --skip-ai
```

Then open `site/index.html` in a browser. A province can also be opened directly with a link such as `index.html#ชลบุรี`.

Other scripts:

```powershell
python src\floodwatch\discharge.py                 # print river-discharge forecast
python src\floodwatch\news.py                      # print latest flood headlines
python src\floodwatch\summarize.py                 # print the AI summary only
python src\floodwatch\find_point.py 15.70 100.12   # find the grid point with the highest discharge near a location
```

## Project structure

```
src/floodwatch/
  build_site.py    # collects data and renders the page
  template.html    # page layout, styles and interaction
  provinces.json   # 77 provinces with region and approximate centre coordinates
  rain.py          # rainfall forecast (batched Open-Meteo requests, with retry)
  discharge.py     # river-discharge forecast (Open-Meteo Flood API)
  news.py          # Google News RSS headlines
  summarize.py     # Gemini prompt, retry and station list
  find_point.py    # helper for choosing river reference points
```

## Data sources and limits

- Rain and river data: [Open-Meteo](https://open-meteo.com/) (free for non-commercial use, attribution required).
- River discharge is a model estimate at a grid point near each city, not a gauge reading.
- Province coordinates are approximate city-centre points, which is enough for forecast grids but not for precise local conditions.
- News is shown as headline plus link to the original publisher. The AI summary is based on headlines and the numbers above, so it can be wrong or incomplete.
- For official information see the Department of Disaster Prevention and Mitigation, the Royal Irrigation Department and the Thai Meteorological Department.

## Roadmap

- [ ] Scheduled builds with GitHub Actions and publishing to GitHub Pages
- [ ] Tests for classification and parsing
- [ ] Optional English version of the page
