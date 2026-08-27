import argparse
import csv
import html
import time
from pathlib import Path

import folium
import pandas as pd
import requests
from folium.plugins import MarkerCluster


BASE_DIR = Path(__file__).resolve().parent
RESULTS_DIR = BASE_DIR / "results"
DEFAULT_INPUT = RESULTS_DIR / "top_500_2025.csv"
DEFAULT_CACHE = RESULTS_DIR / "top_500_geocoded.csv"
DEFAULT_MAP = RESULTS_DIR / "top_500_map.html"
PHOTON_URL = "https://photon.komoot.io/api/"


def parse_args():
    parser = argparse.ArgumentParser(description="Геокодирование и карта топ-500")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--cache", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--map", dest="map_path", type=Path, default=DEFAULT_MAP)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--delay", type=float, default=1.1)
    return parser.parse_args()


def read_completed(cache_path):
    if not cache_path.exists() or cache_path.stat().st_size == 0:
        return set()
    cached = pd.read_csv(cache_path, dtype={"inn": "string"})
    successful = cached[cached["geocode_status"].eq("success")]
    return set(successful["inn"].dropna().astype(str))


def append_row(path, row):
    frame = pd.DataFrame([row])
    frame.to_csv(
        path,
        mode="a",
        header=not path.exists() or path.stat().st_size == 0,
        index=False,
        quoting=csv.QUOTE_MINIMAL,
    )


def geocode(session, query):
    response = session.get(
        PHOTON_URL,
        params={"q": f"{query}, Россия", "limit": 1},
        timeout=(10, 40),
    )
    response.raise_for_status()
    features = response.json().get("features") or []
    if not features:
        return None
    result = features[0]
    coordinates = result["geometry"]["coordinates"]
    properties = result.get("properties") or {}
    return {
        "latitude": float(coordinates[1]),
        "longitude": float(coordinates[0]),
        "geocoded_name": ", ".join(
            str(properties[key])
            for key in ("name", "street", "housenumber", "city", "state", "country")
            if properties.get(key)
        ),
    }


def build_map(data, map_path):
    located = data.dropna(subset=["latitude", "longitude"]).copy()
    if located.empty:
        return False

    center = [located["latitude"].median(), located["longitude"].median()]
    result_map = folium.Map(location=center, zoom_start=4, tiles="CartoDB positron")
    cluster = MarkerCluster(name="Топ-500 компаний").add_to(result_map)

    for row in located.to_dict("records"):
        profit = row.get("net_profit")
        profit_text = "нет данных" if pd.isna(profit) else f"{profit / 1000:,.1f} млн руб."
        popup = (
            f"<b>{html.escape(str(row.get('short_name') or 'Без названия'))}</b><br>"
            f"ИНН: {html.escape(str(row.get('inn')))}<br>"
            f"Чистая прибыль 2025: {profit_text}<br>"
            f"{html.escape(str(row.get('address') or ''))}"
        )
        folium.CircleMarker(
            location=[row["latitude"], row["longitude"]],
            radius=5,
            color="#0F766E",
            fill=True,
            fill_opacity=0.72,
            weight=1,
            popup=folium.Popup(popup, max_width=420),
        ).add_to(cluster)

    folium.LayerControl().add_to(result_map)
    result_map.save(map_path)
    return True


def main():
    args = parse_args()
    source = pd.read_csv(args.input, dtype={"inn": "string"})
    source = source.sort_values("net_profit", ascending=False).head(500)
    completed = read_completed(args.cache)
    pending = source[~source["inn"].isin(completed)].copy()
    if args.limit > 0:
        pending = pending.head(args.limit)

    session = requests.Session()
    session.headers.update({
        "User-Agent": "construction-financial-analysis-student-project/1.0"
    })

    total = len(pending)
    for number, row in enumerate(pending.to_dict("records"), start=1):
        address = str(row.get("address") or "").strip()
        result = None
        status = "missing_address"
        error = None

        if address:
            try:
                result = geocode(session, address)
                precision = "address" if result else None
                if result is None:
                    fallback_parts = [
                        row.get("city"),
                        row.get("settlement"),
                        row.get("region"),
                    ]
                    fallback = ", ".join(
                        str(part).strip()
                        for part in fallback_parts
                        if pd.notna(part) and str(part).strip()
                    )
                    if fallback:
                        time.sleep(max(args.delay, 1.0))
                        result = geocode(session, fallback)
                        precision = "city_or_region" if result else None
                status = "success" if result else "not_found"
            except Exception as exc:
                status = "error"
                error = f"{type(exc).__name__}: {exc}"
                precision = None
        else:
            precision = None

        append_row(args.cache, {
            **row,
            "latitude": result["latitude"] if result else None,
            "longitude": result["longitude"] if result else None,
            "geocoded_name": result["geocoded_name"] if result else None,
            "geocode_precision": precision,
            "geocode_status": status,
            "geocode_error": error,
        })
        print(f"[{number}/{total}] {row['inn']}: {status}")
        time.sleep(max(args.delay, 1.0))

    geocoded = pd.read_csv(args.cache, dtype={"inn": "string"})
    current_top = set(source["inn"].astype(str))
    geocoded = geocoded[geocoded["inn"].isin(current_top)]
    geocoded = geocoded.drop_duplicates("inn", keep="last")
    map_created = build_map(geocoded, args.map_path)

    located = geocoded["latitude"].notna().sum()
    print(f"Координаты найдены: {located}/{len(geocoded)}")
    if map_created:
        print(f"Карта сохранена: {args.map_path}")
    else:
        print("Карта пока не создана: координаты не найдены")


if __name__ == "__main__":
    main()
