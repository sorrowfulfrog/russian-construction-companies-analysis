import argparse
import csv
from pathlib import Path

import pandas as pd

from functions import create_session, flatten_company_result, get_company_financials


BASE_DIR = Path(__file__).resolve().parent
DEFAULT_INPUT = BASE_DIR / "results" / "top_500_2025.csv"
DEFAULT_OUTPUT = BASE_DIR / "results" / "ebitda_top500_2025.csv"


def parse_args():
    parser = argparse.ArgumentParser(description="Расчёт EBITDA для топ-компаний")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--year", type=int, default=2025)
    return parser.parse_args()


def read_completed(path):
    if not path.exists() or path.stat().st_size == 0:
        return set()
    data = pd.read_csv(
        path,
        dtype={"inn": "string"},
        usecols=["inn", "status"],
    )
    completed = data[~data["status"].eq("error")]
    return set(completed["inn"].dropna().astype(str))


def append_row(path, row):
    pd.DataFrame([row]).to_csv(
        path,
        mode="a",
        header=not path.exists() or path.stat().st_size == 0,
        index=False,
        quoting=csv.QUOTE_MINIMAL,
    )


def main():
    args = parse_args()
    source = pd.read_csv(args.input, dtype={"inn": "string"})
    source = source.drop_duplicates("inn").sort_values("net_profit", ascending=False)
    completed = read_completed(args.output)
    pending = source[~source["inn"].isin(completed)].copy()
    if args.limit > 0:
        pending = pending.head(args.limit)

    session = create_session()
    total = len(pending)

    for number, source_row in enumerate(pending.to_dict("records"), start=1):
        inn = str(source_row["inn"])
        try:
            company = get_company_financials(inn, args.year, session)
            result = flatten_company_result(company, args.year)
        except Exception as error:
            result = {
                "inn": inn,
                "org_id": source_row.get("org_id"),
                "year": args.year,
                "ebit": source_row.get("ebit"),
                "intangible_amortization": None,
                "total_amortization": None,
                "ebita": None,
                "ebitda": None,
                "status": "error",
                "amortization_source": None,
                "error": f"{type(error).__name__}: {error}",
            }

        result["short_name"] = source_row.get("short_name")
        result["region"] = source_row.get("region")
        result["address"] = source_row.get("address")
        result["net_profit"] = source_row.get("net_profit")
        append_row(args.output, result)
        print(
            f"[{number}/{total}] {inn}: {result.get('status')}; "
            f"EBITDA={result.get('ebitda')}"
        )

    print(f"Результат: {args.output}")


if __name__ == "__main__":
    main()
