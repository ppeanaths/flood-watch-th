# Flood Watch Thailand

A Python project that collects rainfall forecasts, recent modelled rainfall, river-flow forecasts and flood headlines for Thailand, then builds a single static web page: an AI-written national summary plus a per-province view for all 77 provinces (with quick links for Bangkok and the surrounding provinces).

Live site: https://ppeanaths.github.io/flood-watch-th/

> สรุปสถานการณ์ฝนและข่าวน้ำท่วมรายจังหวัด (77 จังหวัด) สร้างเป็นหน้าเว็บเดียวด้วย Python
> ระดับฝน (ฝนไม่หนัก / ฝนหนัก / ฝนหนักมาก) คำนวณเองจากปริมาณฝน ไม่ใช่ประกาศเตือนภัยอย่างเป็นทางการ และไม่ได้บอกว่าพื้นที่กำลังน้ำท่วมหรือไม่

## What it does

- Fetches, for every province, the rainfall forecast for the next 7 days plus the 3 previous days from [Open-Meteo](https://open-meteo.com/). The previous days are modelled values, not gauge readings.
- Fetches 7-day river-discharge forecasts (GloFAS model) for two Chao Phraya reference points.
- Collects recent flood headlines from Google News RSS (title and link only, no article text), nationally and per province. A province headline is kept only if it contains a flood-related word and names the province.
- Asks Gemini for a short national summary. The prompt limits it to the supplied data, requires damage figures to be attributed to a named outlet, and forbids totals computed across articles.
- Renders everything into `site/index.html`: a province dropdown, Bangkok-area shortcuts, chips for provinces that have flood headlines, a 10-day rain bar chart per province, a river chart and a news list.

## Rain levels

A province is classified from today's forecast rain or the 3-day accumulation (today plus the two previous days), whichever is higher:

| Level | Today's rain | 3-day accumulation |
|---|---|---|
| Heavy rain (ฝนหนัก) | 35.1 mm or more | 100 mm or more |
| Very heavy rain (ฝนหนักมาก) | 90 mm or more | 200 mm or more |

The daily thresholds follow the Thai Meteorological Department's daily rainfall classes. The accumulation thresholds are this project's own assumption. All four values are constants at the top of `build_site.py` (`WATCH_MM`, `ALERT_MM`, `ACC_WATCH_MM`, `ACC_ALERT_MM`).

These levels describe rainfall only. A province can be flooded while its level is low (water from earlier rain or from upstream), and the page says so. Use the headlines and official announcements alongside it.

## How it works

```
provinces.json ──► rain.py ─────────┐
                   discharge.py ────┤
                   news.py ─────────┼──► build_site.py ──► site/index.html
                   summarize.py ────┘     (template.html)
                   (Gemini prompt + retry)
```

A GitHub Actions workflow (`.github/workflows/deploy.yml`) builds the site twice a day and on every push to `main`, then publishes it with GitHub Pages. If a build fails, the previously published site stays up.

## Setup

Requires Python 3.12 or newer.

```bash
# macOS / Linux
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

```powershell
# Windows PowerShell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Create a `.env` file in the project root (it is git-ignored):

```
GEMINI_API_KEY=your-key-here
GEMINI_MODEL=gemini-flash-latest
```

The AI summary is optional. Without a key the page is still built, with a placeholder where the summary would be. In GitHub Actions the key is read from a repository secret named `GEMINI_API_KEY`.

## Usage

```bash
# Full build (rain + rivers + news for all provinces + AI summary)
python3 src/floodwatch/build_site.py

# Quick build for checking layout changes (no per-province news, no AI)
python3 src/floodwatch/build_site.py --skip-news --skip-ai
```

Then open `site/index.html` in a browser. A province can also be opened directly with a link such as `index.html#ชลบุรี`.

Other scripts:

```bash
python3 src/floodwatch/discharge.py                 # print a river-discharge forecast
python3 src/floodwatch/news.py                      # print latest flood headlines
python3 src/floodwatch/summarize.py                 # print the AI summary only
python3 src/floodwatch/find_point.py 15.70 100.12   # find the grid point with the highest discharge near a location
```

## Project structure

```
src/floodwatch/
  build_site.py    # collects data, classifies rain levels and renders the page
  template.html    # page layout, styles and interaction
  provinces.json   # 77 provinces with region and approximate centre coordinates
  rain.py          # rainfall forecast and past days (batched Open-Meteo requests, with retry)
  discharge.py     # river-discharge forecast (Open-Meteo Flood API)
  news.py          # Google News RSS headlines
  summarize.py     # Gemini prompt, retry, Thai date helpers and station list
  find_point.py    # helper for choosing river reference points
.github/workflows/deploy.yml   # scheduled build and GitHub Pages deployment
```

## Data sources and limits

- Rain and river data: [Open-Meteo](https://open-meteo.com/) (free for non-commercial use, attribution required).
- River discharge is a model estimate at a grid point near each city, not a gauge reading.
- Province coordinates are approximate city-centre points, which is enough for forecast grids but not for precise local conditions.
- News is shown as headline plus link to the original publisher. Per-province filtering relies on the province name appearing in the headline, so some relevant stories are missed. No headline does not mean no flooding.
- The AI summary is based on headlines and the numbers above, so it can be wrong or incomplete.
- For official information see the Department of Disaster Prevention and Mitigation, the Royal Irrigation Department and the Thai Meteorological Department.

## Roadmap

- [x] Scheduled builds with GitHub Actions and publishing to GitHub Pages
- [x] Accumulated rainfall and past days
- [ ] Tests for classification, news filtering and parsing
- [ ] Ranking of provinces by rainfall, filters by region and level
- [ ] Map view
- [ ] Optional English version of the page