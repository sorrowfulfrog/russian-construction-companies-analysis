from pathlib import Path

import numpy as np
import pandas as pd


BASE_DIR = Path(__file__).resolve().parent
RESULTS_DIR = BASE_DIR / "results"
INPUT_PATH = BASE_DIR / "structured_financials_long.csv"
TOP_500_PATH = RESULTS_DIR / "top_500_2025.csv"
REGIONS_PATH = RESULTS_DIR / "region_segments.csv"


def safe_ratio(numerator, denominator):
    denominator = denominator.where(denominator.ne(0))
    return numerator / denominator * 100


def build_financials(data, growth):
    financials = data.merge(
        growth[["inn", "growth_pct"]], on="inn", how="left", validate="many_to_one"
    )
    financials["revenue_mln"] = financials["revenue"] / 1000
    financials["net_profit_mln"] = financials["net_profit"] / 1000
    financials["ebit_mln"] = financials["ebit"] / 1000
    financials["net_margin_pct"] = safe_ratio(
        financials["net_profit"], financials["revenue"]
    )
    financials["ebit_margin_pct"] = safe_ratio(
        financials["ebit"], financials["revenue"]
    )
    financials["profitable"] = np.where(
        financials["net_profit"].isna(), pd.NA, financials["net_profit"].gt(0)
    )
    financials["profit_rank_in_year"] = financials.groupby("year")[
        "net_profit"
    ].rank(method="first", ascending=False).astype("Int64")

    columns = {
        "inn": "ИНН",
        "short_name": "Компания",
        "region": "Регион",
        "registry_category": "Категория МСП",
        "year": "Год",
        "revenue_mln": "Выручка, млн руб.",
        "net_profit_mln": "Чистая прибыль, млн руб.",
        "ebit_mln": "EBIT, млн руб.",
        "net_margin_pct": "Рентабельность по чистой прибыли, %",
        "ebit_margin_pct": "Рентабельность EBIT, %",
        "growth_pct": "Рост чистой прибыли 2021–2025, %",
        "profit_rank_in_year": "Ранг по чистой прибыли в году",
        "profitable": "Прибыльная компания",
        "collection_status": "Статус сбора",
    }
    return financials[list(columns)].rename(columns=columns)


def build_map(top_500):
    result = top_500.copy()
    result = result.sort_values("net_profit", ascending=False).reset_index(drop=True)
    result["rank"] = np.arange(1, len(result) + 1)
    result["revenue_mln"] = result["revenue"] / 1000
    result["net_profit_mln"] = result["net_profit"] / 1000
    result["ebit_mln"] = result["ebit"] / 1000
    result["net_margin_pct"] = safe_ratio(result["net_profit"], result["revenue"])
    result["geopoint"] = (
        result["latitude"].round(6).astype("string")
        + ","
        + result["longitude"].round(6).astype("string")
    )
    columns = {
        "rank": "Место в рейтинге",
        "inn": "ИНН",
        "short_name": "Компания",
        "region": "Регион",
        "registry_category": "Категория МСП",
        "address": "Адрес",
        "revenue_mln": "Выручка, млн руб.",
        "net_profit_mln": "Чистая прибыль, млн руб.",
        "ebit_mln": "EBIT, млн руб.",
        "net_margin_pct": "Рентабельность по чистой прибыли, %",
        "latitude": "Широта",
        "longitude": "Долгота",
        "geopoint": "Геоточка",
        "geocode_precision": "Точность геокодирования",
    }
    return result[list(columns)].rename(columns=columns)


def build_regions(regions):
    result = regions.copy()
    result["profitable_share_pct"] = result["profitable_share_2025"] * 100
    columns = {
        "region": "Регион",
        "companies": "Компаний",
        "companies_with_growth": "Компаний с рассчитанным ростом",
        "median_growth_pct": "Медианный рост чистой прибыли, %",
        "median_net_profit_2025": "Медианная чистая прибыль 2025, тыс. руб.",
        "profitable_share_pct": "Доля прибыльных компаний 2025, %",
        "eligible_for_ranking": "Регион включён в рейтинг",
    }
    return result[list(columns)].rename(columns=columns)


def build_hypotheses(data, growth):
    latest = data[data["year"].eq(2025)].copy()
    latest = latest.merge(
        growth[["inn", "growth_pct"]], on="inn", how="left", validate="one_to_one"
    )
    category = latest.groupby("registry_category", dropna=False).agg(
        companies=("inn", "nunique"),
        median_profit=("net_profit", "median"),
        median_growth=("growth_pct", "median"),
        profitable_share=("net_profit", lambda values: values.gt(0).mean()),
    )
    corr_profit = latest[["revenue", "net_profit"]].dropna().corr(method="spearman").iloc[0, 1]
    corr_margin = latest[["ebit", "net_profit"]].dropna().corr(method="spearman").iloc[0, 1]
    positive_margin = latest[safe_ratio(latest["ebit"], latest["revenue"]).gt(0)]
    negative_margin = latest[safe_ratio(latest["ebit"], latest["revenue"]).le(0)]

    rows = [
        {
            "Гипотеза": "Средние предприятия показывают более высокую типичную прибыль, чем малые",
            "Метрика": "Медианная чистая прибыль за 2025 год",
            "Результат": "Средние: {:.1f} млн руб.; малые: {:.1f} млн руб.".format(
                category.loc["Среднее предприятие", "median_profit"] / 1000,
                category.loc["Малое предприятие", "median_profit"] / 1000,
            ),
            "Предварительный вывод": "Поддерживается" if category.loc["Среднее предприятие", "median_profit"] > category.loc["Малое предприятие", "median_profit"] else "Не поддерживается",
        },
        {
            "Гипотеза": "Более высокая выручка связана с более высокой чистой прибылью",
            "Метрика": "Ранговая корреляция Спирмена, 2025",
            "Результат": f"ρ = {corr_profit:.3f}",
            "Предварительный вывод": "Поддерживается" if corr_profit > 0.3 else "Связь слабая",
        },
        {
            "Гипотеза": "Положительный EBIT связан с большей вероятностью чистой прибыли",
            "Метрика": "Доля прибыльных компаний за 2025 год",
            "Результат": "При EBIT > 0: {:.1f}%; при EBIT ≤ 0: {:.1f}%".format(
                positive_margin["net_profit"].gt(0).mean() * 100,
                negative_margin["net_profit"].gt(0).mean() * 100,
            ),
            "Предварительный вывод": "Поддерживается",
        },
        {
            "Гипотеза": "EBIT и чистая прибыль движутся в одном направлении",
            "Метрика": "Ранговая корреляция Спирмена, 2025",
            "Результат": f"ρ = {corr_margin:.3f}",
            "Предварительный вывод": "Поддерживается" if corr_margin > 0.5 else "Связь умеренная",
        },
    ]
    return pd.DataFrame(rows)


def main():
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    data = pd.read_csv(INPUT_PATH, dtype={"inn": "string"})
    data = data.drop_duplicates(["inn", "year"], keep="last")
    growth = pd.read_csv(
        RESULTS_DIR / "profit_growth_2021_2025.csv", dtype={"inn": "string"}
    )
    top_500 = pd.read_csv(TOP_500_PATH, dtype={"inn": "string"})
    regions = pd.read_csv(REGIONS_PATH)

    financials = build_financials(data, growth)
    top_20 = financials[
        financials["Год"].eq(2025)
        & financials["Ранг по чистой прибыли в году"].le(20)
    ].copy()
    map_data = build_map(top_500)
    region_data = build_regions(regions)
    region_top_15 = region_data[
        region_data["Регион включён в рейтинг"].eq(True)
    ].head(15).copy()
    hypotheses = build_hypotheses(data, growth)

    outputs = {
        "datalens_financials.csv": financials,
        "datalens_top20_2025.csv": top_20,
        "datalens_top500_map.csv": map_data,
        "datalens_regions.csv": region_data,
        "datalens_regions_top15.csv": region_top_15,
        "hypotheses.csv": hypotheses,
    }
    for filename, frame in outputs.items():
        frame.to_csv(RESULTS_DIR / filename, index=False, encoding="utf-8")

    with pd.ExcelWriter(RESULTS_DIR / "datalens_sources.xlsx", engine="openpyxl") as writer:
        financials.to_excel(writer, sheet_name="Финансы", index=False)
        top_20.to_excel(writer, sheet_name="Топ-20 2025", index=False)
        map_data.to_excel(writer, sheet_name="Карта топ-500", index=False)
        region_data.to_excel(writer, sheet_name="Регионы", index=False)
        region_top_15.to_excel(writer, sheet_name="Топ-15 регионов", index=False)
        hypotheses.to_excel(writer, sheet_name="Гипотезы", index=False)

    print(f"Финансы: {len(financials):,} строк")
    print(f"Карта: {len(map_data):,} строк; координаты: {map_data['Широта'].notna().sum():,}")
    print(f"Регионы: {len(region_data):,} строк")
    print(hypotheses.to_string(index=False))


if __name__ == "__main__":
    main()
