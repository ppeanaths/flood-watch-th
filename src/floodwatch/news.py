import feedparser
import requests

NEWS_URL = "https://news.google.com/rss/search"

def fetch_flood_news(keyword="น้ำท่วม", days = 2, limit = 10):
    params = {
        "q": f"{keyword} when:{days}d",
        "hl": "th",
        "gl": "TH",
        "ceid": "TH:th"
    }

    response = requests.get(NEWS_URL, params=params, timeout=10)
    response.raise_for_status()

    feed = feedparser.parse(response.content)

    articles = []
    for entry in feed.entries:
        source = entry.get("source", {}).get("title", "")
        if "facebook" in source.lower():
            continue
        articles.append(
            {
                "title": entry.get("title", ""),
                "link": entry.get("link", ""),
                "published": entry.get("published", ""),
                "source": source,
            }
        )
        if len(articles) >= limit:
            break
    return articles


if __name__ == "__main__":
    for article in fetch_flood_news():
        print(article["published"], "|", article["source"])
        print("  ", article["title"])
        print("  ", article["link"])    