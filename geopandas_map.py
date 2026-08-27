from pathlib import Path

import geopandas as gpd
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import requests


BASE_DIR = Path(__file__).resolve().parent
RESULTS_DIR = BASE_DIR / "results"
SOURCE_PATH = RESULTS_DIR / "top_500_2025.csv"
BOUNDARY_PATH = RESULTS_DIR / "ne_110m_admin_0_countries.zip"
BOUNDARY_URL = (
    "https://naturalearth.s3.amazonaws.com/110m_cultural/"
    "ne_110m_admin_0_countries.zip"
)


def download_boundary():
    if BOUNDARY_PATH.exists():
        return
    response = requests.get(BOUNDARY_URL, timeout=60)
    response.raise_for_status()
    BOUNDARY_PATH.write_bytes(response.content)


def main():
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    download_boundary()

    data = pd.read_csv(SOURCE_PATH, dtype={"inn": "string"})
    data = data.dropna(subset=["latitude", "longitude"]).copy()
    points = gpd.GeoDataFrame(
        data,
        geometry=gpd.points_from_xy(data["longitude"], data["latitude"]),
        crs="EPSG:4326",
    )

    countries = gpd.read_file(f"zip://{BOUNDARY_PATH}")
    name_column = "ADMIN" if "ADMIN" in countries.columns else "NAME"
    russia = countries[countries[name_column].eq("Russia")]

    fig, ax = plt.subplots(figsize=(15, 8.5))
    russia.plot(ax=ax, color="#E8EEF5", edgecolor="#64748B", linewidth=0.7)

    profit = points["net_profit"].clip(lower=0)
    sizes = 18 + 230 * np.sqrt(profit / profit.max())
    colors = points["registry_category"].map(
        {"Малое предприятие": "#2563EB", "Среднее предприятие": "#F97316"}
    ).fillna("#64748B")
    points.plot(
        ax=ax,
        color=colors,
        markersize=sizes,
        alpha=0.62,
        edgecolor="white",
        linewidth=0.35,
    )

    ax.set_xlim(19, 181)
    ax.set_ylim(40, 82)
    ax.set_axis_off()
    fig.suptitle(
        "Топ-500 строительных компаний России по чистой прибыли",
        x=0.07,
        y=0.98,
        ha="left",
        fontsize=18,
        fontweight="bold",
    )
    fig.text(
        0.07,
        0.935,
        "2025 год · размер точки — чистая прибыль · синий — малое предприятие · оранжевый — среднее",
        fontsize=10.5,
        color="#475569",
    )
    fig.text(
        0.07,
        0.035,
        f"Отображено компаний: {len(points)} из 500. Финансовые показатели БФО, координаты геокодированы по адресу/региону.",
        fontsize=9.5,
        color="#64748B",
    )
    fig.tight_layout(rect=[0.02, 0.06, 0.99, 0.92])
    fig.savefig(RESULTS_DIR / "top_500_geopandas.png", dpi=200, bbox_inches="tight")
    plt.close(fig)

    export_columns = [
        "inn", "short_name", "region", "registry_category", "address",
        "revenue", "net_profit", "ebit", "latitude", "longitude", "geometry",
    ]
    points[export_columns].to_file(
        RESULTS_DIR / "top_500_geopandas.geojson", driver="GeoJSON"
    )
    print(f"Карта сохранена: {RESULTS_DIR / 'top_500_geopandas.png'}")
    print(f"GeoJSON сохранён: {RESULTS_DIR / 'top_500_geopandas.geojson'}")


if __name__ == "__main__":
    main()
