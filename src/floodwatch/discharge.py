import requests

BASE_URL = "https://flood-api.open-meteo.com/v1/flood"


def fetch_river_discharge(lat, lon, days=7):
    params = {
        "latitude": lat,
        "longitude": lon,
        "daily": "river_discharge",
        "forecast_days": days,
    }

    response = requests.get(BASE_URL, params=params, timeout=10)
    response.raise_for_status()
    data = response.json()

    dates = data["daily"]["time"]
    values = data["daily"]["river_discharge"]

    return [
        {"date": date, "discharge_m3s": value}
        for date, value in zip(dates, values)
    ]


if __name__ == "__main__":
    rows = fetch_river_discharge(15.70, 100.12)
    for row in rows:
        print(row)