import argparse
from copy import copy
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.ticker import FuncFormatter


BASE_DIR = Path(__file__).resolve().parent
DEFAULT_INPUT = BASE_DIR / "structured_financials_long.csv"
DEFAULT_OUTPUT_DIR = BASE_DIR / "results"
DEFAULT_EBITDA = DEFAULT_OUTPUT_DIR / "ebitda_top500_2025.csv"
DEFAULT_ERRORS = BASE_DIR / "structured_financials_errors.csv"
DEFAULT_GEOCODED = DEFAULT_OUTPUT_DIR / "top_500_geocoded.csv"
START_YEAR = 2021
END_YEAR = 2025


def parse_args():
    parser = argparse.ArgumentParser(description="Анализ финансовых результатов")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args()


def prepare_growth(data):
    profit = data.pivot_table(
        index=["inn", "short_name", "region", "address"],
        columns="year",
        values="net_profit",
        aggfunc="first",
    ).reset_index()

    for year in (START_YEAR, END_YEAR):
        if year not in profit.columns:
            profit[year] = np.nan

    profit = profit.rename(
        columns={START_YEAR: "net_profit_2021", END_YEAR: "net_profit_2025"}
    )
    valid = (
        profit["net_profit_2021"].notna()
        & profit["net_profit_2025"].notna()
        & profit["net_profit_2021"].ne(0)
    )
    profit["growth_pct"] = np.nan
    profit.loc[valid, "growth_pct"] = (
        (
            profit.loc[valid, "net_profit_2025"]
            - profit.loc[valid, "net_profit_2021"]
        )
        / profit.loc[valid, "net_profit_2021"].abs()
        * 100
    )
    return profit


def plot_growth_histogram(growth, output_path):
    values = growth["growth_pct"].dropna()
    visible = values[values.between(-200, 200, inclusive="both")]
    lower_tail = int((values < -200).sum())
    upper_tail = int((values > 200).sum())
    bins = np.arange(-200, 210, 10)

    fig, ax = plt.subplots(figsize=(13, 7.5))
    ax.hist(visible, bins=bins, color="#2563EB", edgecolor="white", linewidth=0.7)
    ax.axvline(0, color="#111827", linewidth=1.2)
    ax.axvline(values.median(), color="#F97316", linewidth=2, linestyle="--")
    fig.suptitle(
        "Распределение роста чистой прибыли строительных компаний",
        x=0.08,
        y=0.985,
        ha="left",
        fontsize=17,
        fontweight="bold",
    )
    fig.text(
        0.08,
        0.947,
        f"2021→2025, шаг 10 п.п.; n={len(values):,}; медиана={values.median():.1f}%",
        fontsize=10.5,
        color="#4B5563",
    )
    ax.text(
        0.01,
        0.95,
        f"За пределами шкалы: ниже −200% — {lower_tail:,}; выше 200% — {upper_tail:,}",
        transform=ax.transAxes,
        va="top",
        fontsize=10,
        bbox={"boxstyle": "round,pad=0.4", "facecolor": "white", "edgecolor": "#D1D5DB"},
    )
    ax.set_xlabel("Рост чистой прибыли, %")
    ax.set_ylabel("Количество компаний")
    ax.grid(axis="y", alpha=0.22)
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout(rect=[0, 0, 1, 0.91])
    fig.savefig(output_path, dpi=180, bbox_inches="tight")
    plt.close(fig)


def plot_top_companies(data, output_path):
    latest = data[data["year"].eq(END_YEAR)].copy()
    latest = latest.dropna(subset=["net_profit"])
    latest = latest.sort_values("net_profit", ascending=False).head(20)
    latest = latest.sort_values("net_profit")

    fig, ax = plt.subplots(figsize=(13, 8.5))
    labels = latest["short_name"].fillna(latest["inn"]).str.slice(0, 42)
    ax.barh(labels, latest["net_profit"] / 1000, color="#0F766E")
    fig.suptitle(
        "Топ-20 компаний по чистой прибыли за 2025 год",
        x=0.28,
        y=0.985,
        ha="left",
        fontsize=17,
        fontweight="bold",
    )
    fig.text(
        0.28,
        0.947,
        "По текущей собранной выборке; данные БФО, млн руб.",
        fontsize=10.5,
        color="#4B5563",
    )
    ax.set_xlabel("Чистая прибыль, млн руб.")
    ax.xaxis.set_major_formatter(FuncFormatter(lambda x, _: f"{x:,.0f}".replace(",", " ")))
    ax.grid(axis="x", alpha=0.22)
    ax.spines[["top", "right", "left"]].set_visible(False)
    fig.tight_layout(rect=[0, 0, 1, 0.91])
    fig.savefig(output_path, dpi=180, bbox_inches="tight")
    plt.close(fig)


def prepare_region_segments(growth):
    segments = growth.groupby("region", dropna=False).agg(
        companies=("inn", "nunique"),
        companies_with_growth=("growth_pct", "count"),
        median_growth_pct=("growth_pct", "median"),
        median_net_profit_2025=("net_profit_2025", "median"),
        profitable_share_2025=("net_profit_2025", lambda values: (values > 0).mean()),
    ).reset_index()
    segments["eligible_for_ranking"] = segments["companies_with_growth"].ge(10)
    segments = segments.sort_values(
        ["eligible_for_ranking", "median_growth_pct", "profitable_share_2025"],
        ascending=[False, False, False],
    )
    return segments


def plot_region_segments(segments, output_path):
    ranked = segments[segments["eligible_for_ranking"]].head(15).copy()
    ranked = ranked.sort_values("median_growth_pct")
    colors = np.where(ranked["median_growth_pct"].ge(0), "#16A34A", "#DC2626")

    fig, ax = plt.subplots(figsize=(13, 8.5))
    ax.barh(ranked["region"], ranked["median_growth_pct"], color=colors)
    ax.axvline(0, color="#111827", linewidth=1)
    fig.suptitle(
        "Перспективные региональные сегменты строительства",
        x=0.29,
        y=0.985,
        ha="left",
        fontsize=17,
        fontweight="bold",
    )
    fig.text(
        0.29,
        0.947,
        "Медианный рост чистой прибыли 2021→2025; минимум 10 компаний с данными",
        fontsize=10.5,
        color="#4B5563",
    )
    ax.set_xlabel("Медианный рост чистой прибыли, %")
    ax.set_ylabel("")
    ax.grid(axis="x", alpha=0.22)
    ax.spines[["top", "right", "left"]].set_visible(False)
    fig.tight_layout(rect=[0, 0, 1, 0.91])
    fig.savefig(output_path, dpi=180, bbox_inches="tight")
    plt.close(fig)


def build_summary(data, growth):
    latest = data[data["year"].eq(END_YEAR)]
    values = growth["growth_pct"].dropna()
    return pd.DataFrame(
        [
            ("Компаний в собранной выборке", data["inn"].nunique()),
            ("Наблюдений компания-год", len(data)),
            ("Компаний с чистой прибылью за 2025", latest["net_profit"].notna().sum()),
            ("Компаний в расчёте роста 2021→2025", len(values)),
            ("Медианный рост чистой прибыли, %", values.median()),
            ("Компаний с ростом выше 0%", (values > 0).sum()),
            ("Компаний с падением ниже 0%", (values < 0).sum()),
            ("Компаний с EBIT за 2025", latest["ebit"].notna().sum()),
        ],
        columns=["Показатель", "Значение"],
    )


def prepare_ebitda_validation(ebitda_path, data):
    columns = [
        "inn", "status", "ebit", "total_amortization", "ebitda",
        "revenue", "quality_flag", "ebitda_validated",
    ]
    if not ebitda_path.exists() or ebitda_path.stat().st_size == 0:
        return pd.DataFrame(columns=columns)

    ebitda = pd.read_csv(ebitda_path, dtype={"inn": "string"})
    ebitda = ebitda.drop_duplicates("inn", keep="last")
    latest = data[data["year"].eq(END_YEAR)][["inn", "revenue"]].drop_duplicates("inn")
    ebitda = ebitda.drop(columns=["revenue"], errors="ignore").merge(
        latest, on="inn", how="left"
    )

    revenue_limit = ebitda["revenue"].abs() * 0.5
    ebit_limit = ebitda["ebit"].abs() * 5
    plausibility_limit = pd.concat([revenue_limit, ebit_limit], axis=1).max(axis=1)
    outlier = (
        ebitda["ebitda"].notna()
        & ebitda["total_amortization"].notna()
        & ebitda["total_amortization"].abs().gt(plausibility_limit)
    )
    ebitda["quality_flag"] = "not_calculated"
    ebitda.loc[ebitda["ebitda"].notna(), "quality_flag"] = "plausibility_check_passed"
    ebitda.loc[outlier, "quality_flag"] = "manual_review_outlier"
    ebitda["ebitda_validated"] = ebitda["ebitda"].where(~outlier)
    return ebitda


def prepare_current_errors(errors_path, data):
    if not errors_path.exists() or errors_path.stat().st_size == 0:
        return pd.DataFrame()
    errors = pd.read_csv(errors_path, dtype={"inn": "string"})
    errors = errors.drop_duplicates("inn", keep="last")
    successful = set(data["inn"].dropna().astype(str))
    return errors[~errors["inn"].isin(successful)].copy()


def add_geocodes(top_500, geocoded_path):
    if not geocoded_path.exists() or geocoded_path.stat().st_size == 0:
        return top_500
    geocoded = pd.read_csv(geocoded_path, dtype={"inn": "string"})
    geocoded = geocoded.drop_duplicates("inn", keep="last")
    columns = [
        "inn", "latitude", "longitude", "geocoded_name",
        "geocode_precision", "geocode_status",
    ]
    available = [column for column in columns if column in geocoded.columns]
    return top_500.merge(geocoded[available], on="inn", how="left")


def write_excel(
    output_path,
    summary,
    data,
    growth,
    top_500,
    region_segments,
    ebitda_validation,
    current_errors,
):
    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        summary.to_excel(writer, sheet_name="Сводка", index=False)
        growth.sort_values("growth_pct", ascending=False).to_excel(
            writer, sheet_name="Рост прибыли", index=False
        )
        top_500.to_excel(writer, sheet_name="Топ-500 для карты", index=False)
        region_segments.to_excel(writer, sheet_name="Регионы", index=False)
        ebitda_validation.to_excel(writer, sheet_name="EBITDA проверка", index=False)
        current_errors.to_excel(writer, sheet_name="Не найдены в БФО", index=False)
        data.to_excel(writer, sheet_name="Данные БФО", index=False)

        for sheet in writer.book.worksheets:
            sheet.freeze_panes = "A2"
            sheet.auto_filter.ref = sheet.dimensions
            sheet.sheet_view.showGridLines = False
            for cell in sheet[1]:
                font = copy(cell.font)
                font.bold = True
                font.color = "FFFFFF"
                cell.font = font
                fill = copy(cell.fill)
                fill.fill_type = "solid"
                fill.fgColor.rgb = "1F4E78"
                cell.fill = fill
            for column in sheet.columns:
                values = [str(cell.value) if cell.value is not None else "" for cell in column[:200]]
                width = min(max(max(map(len, values), default=0) + 2, 10), 42)
                sheet.column_dimensions[column[0].column_letter].width = width


def main():
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    data = pd.read_csv(args.input, dtype={"inn": "string"})
    data = data.drop_duplicates(subset=["inn", "year"], keep="last")
    data["year"] = pd.to_numeric(data["year"], errors="coerce").astype("Int64")

    growth = prepare_growth(data)
    region_segments = prepare_region_segments(growth)
    ebitda_validation = prepare_ebitda_validation(DEFAULT_EBITDA, data)
    current_errors = prepare_current_errors(DEFAULT_ERRORS, data)
    summary = build_summary(data, growth)
    summary = pd.concat([
        summary,
        pd.DataFrame(
            [("Компаний не найдено в БФО", len(current_errors))],
            columns=["Показатель", "Значение"],
        ),
    ], ignore_index=True)
    if not ebitda_validation.empty:
        summary = pd.concat([
            summary,
            pd.DataFrame([
                ("EBITDA распознано автоматически", ebitda_validation["ebitda"].notna().sum()),
                (
                    "EBITDA прошло проверку правдоподобия",
                    ebitda_validation["ebitda_validated"].notna().sum(),
                ),
                (
                    "EBITDA требует проверки как выброс",
                    ebitda_validation["quality_flag"].eq("manual_review_outlier").sum(),
                ),
            ], columns=["Показатель", "Значение"]),
        ], ignore_index=True)
    latest = data[data["year"].eq(END_YEAR)].copy()
    top_500 = latest.sort_values("net_profit", ascending=False).head(500)
    top_500 = add_geocodes(top_500, DEFAULT_GEOCODED)

    growth.to_csv(args.output_dir / "profit_growth_2021_2025.csv", index=False)
    top_500.to_csv(args.output_dir / "top_500_2025.csv", index=False)
    summary.to_csv(args.output_dir / "summary.csv", index=False)
    region_segments.to_csv(args.output_dir / "region_segments.csv", index=False)
    ebitda_validation.to_csv(
        args.output_dir / "ebitda_top500_2025_validated.csv", index=False
    )
    current_errors.to_csv(
        args.output_dir / "collection_errors_current.csv", index=False
    )

    plot_growth_histogram(growth, args.output_dir / "profit_growth_histogram.png")
    plot_top_companies(data, args.output_dir / "top_20_net_profit_2025.png")
    plot_region_segments(
        region_segments,
        args.output_dir / "promising_region_segments.png",
    )
    write_excel(
        args.output_dir / "construction_analysis.xlsx",
        summary,
        data,
        growth,
        top_500,
        region_segments,
        ebitda_validation,
        current_errors,
    )

    print(summary.to_string(index=False))
    print(f"Результаты сохранены: {args.output_dir}")


if __name__ == "__main__":
    main()
