import sys

from discharge import fetch_river_discharge


def scan(center_lat, center_lon, radius=0.15, step=0.05):
    """สแกนกริดรอบจุดที่กำหนด (ข้อมูลโมเดลละเอียดราว 0.05 องศา)"""
    steps = int(round(radius / step))
    results = {}
    for i in range(-steps, steps + 1):
        for j in range(-steps, steps + 1):
            lat = round(center_lat + i * step, 3)
            lon = round(center_lon + j * step, 3)
            try:
                rows = fetch_river_discharge(lat, lon, days=1)
                value = rows[0]["discharge_m3s"]
            except Exception:
                continue
            if value is not None:
                results[(lat, lon)] = value
    return sorted(results.items(), key=lambda kv: kv[1], reverse=True)


if __name__ == "__main__":
    center_lat = float(sys.argv[1])
    center_lon = float(sys.argv[2])
    for (lat, lon), value in scan(center_lat, center_lon)[:5]:
        print(f"{lat}, {lon} -> {value} m³/s")