import argparse
import csv
import logging
import re
import time
from pathlib import Path

import pandas as pd
import requests


BASE_DIR = Path(__file__).resolve().parent
DEFAULT_INPUT = BASE_DIR / "construction_companies.csv"
DEFAULT_OUTPUT = BASE_DIR / "structured_financials_long.csv"
DEFAULT_ERRORS = BASE_DIR / "structured_financials_errors.csv"

YEARS = {2021, 2022, 2023, 2024, 2025}


def create_session():
    session = requests.Session()
    session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) "
            "Version/26.5.2 Safari/605.1.15"
        ),
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "ru-RU,ru;q=0.9",
    })
    session.cookies.update({
        "disclaimed": "true",
        "mdd": "1",
    })
    return session


def request_json(session, url, *, params=None, headers=None, attempts=4):
    last_error = None

    for attempt in range(1, attempts + 1):
        try:
            response = session.get(
                url,
                params=params,
                headers=headers,
                timeout=(10, 40),
            )

            if response.status_code == 200:
                return response.json()

            if response.status_code in {429, 500, 502, 503, 504}:
                wait_seconds = min(2 ** attempt, 20)
                time.sleep(wait_seconds)
                continue

            raise RuntimeError(
                f"HTTP {response.status_code}: {response.text[:200]}"
            )

        except (requests.RequestException, ValueError, RuntimeError) as error:
            last_error = error

            if attempt < attempts:
                time.sleep(min(2 ** attempt, 20))

    raise RuntimeError(f"request_failed: {last_error}")


def normalize_inn(value):
    digits = re.sub(r"\D", "", str(value or ""))

    if len(digits) <= 10:
        return digits.zfill(10)

    return digits


def find_organization(session, inn):
    url = "https://bo.nalog.gov.ru/advanced-search/organizations/search"
    data = request_json(
        session,
        url,
        params={
            "query": inn,
            "page": 0,
            "size": 20,
        },
        headers={
            "Referer": f"https://bo.nalog.gov.ru/search?query={inn}"
        },
    )

    content = data.get("content") or []

    if not content:
        return None

    for organization in content:
        found_inn = normalize_inn(organization.get("inn"))

        if found_inn == inn:
            return organization

    return content[0]


def get_bfo_reports(session, org_id):
    url = f"https://bo.nalog.gov.ru/nbo/organizations/{org_id}/bfo/"
    return request_json(
        session,
        url,
        headers={
            "Referer": f"https://bo.nalog.gov.ru/organizations-card/{org_id}"
        },
    )


def correction_sort_key(type_correction):
    correction = type_correction.get("correction") or {}
    version = correction.get("correctionVersion")
    date_present = correction.get("datePresent") or ""
    correction_id = correction.get("id")

    try:
        version = int(version)
    except (TypeError, ValueError):
        version = -1

    try:
        correction_id = int(correction_id)
    except (TypeError, ValueError):
        correction_id = -1

    return version, date_present, correction_id


def get_latest_correction(report):
    type_corrections = report.get("typeCorrections") or []

    if not type_corrections:
        return None

    selected = max(type_corrections, key=correction_sort_key)
    return selected.get("correction") or None


def calculate_ebit(financial_result):
    profit_before_tax = financial_result.get("current2300")

    if profit_before_tax is None:
        return None

    interest_expense = financial_result.get("current2330") or 0
    interest_income = financial_result.get("current2320") or 0

    return profit_before_tax + interest_expense - interest_income


def make_address(organization):
    parts = [
        organization.get("index"),
        organization.get("region"),
        organization.get("district"),
        organization.get("city"),
        organization.get("settlement"),
        organization.get("street"),
        organization.get("house"),
        organization.get("building"),
        organization.get("office"),
    ]
    return ", ".join(str(part).strip() for part in parts if part)


def build_rows(source_row, organization, reports):
    rows = []
    inn = normalize_inn(source_row["ИНН"])
    org_id = organization.get("id")

    common = {
        "inn": inn,
        "org_id": org_id,
        "short_name": organization.get("shortName"),
        "ogrn": organization.get("ogrn"),
        "organization_status": organization.get("statusCode"),
        "region": organization.get("region"),
        "district": organization.get("district"),
        "city": organization.get("city"),
        "settlement": organization.get("settlement"),
        "address": make_address(organization),
        "registry_category": source_row.get("Категория"),
        "registry_okved": source_row.get("ОКВЭД"),
        "registry_activity": source_row.get("Основной вид деятельности"),
        "bo_okved": organization.get("okved2"),
    }

    for report in reports or []:
        try:
            year = int(report.get("period"))
        except (TypeError, ValueError):
            continue

        if year not in YEARS:
            continue

        correction = get_latest_correction(report)

        if correction is None:
            continue

        financial = correction.get("financialResult") or {}

        rows.append({
            **common,
            "year": year,
            "revenue": financial.get("current2110"),
            "gross_profit": financial.get("current2100"),
            "sales_profit": financial.get("current2200"),
            "profit_before_tax": financial.get("current2300"),
            "net_profit": financial.get("current2400"),
            "interest_income": financial.get("current2320"),
            "interest_expense": financial.get("current2330"),
            "ebit": calculate_ebit(financial),
            "correction_id": correction.get("id"),
            "correction_version": correction.get("correctionVersion"),
            "date_present": correction.get("datePresent"),
            "collection_status": "success_bfo",
        })

    if not rows:
        rows.append({
            **common,
            "year": None,
            "revenue": None,
            "gross_profit": None,
            "sales_profit": None,
            "profit_before_tax": None,
            "net_profit": None,
            "interest_income": None,
            "interest_expense": None,
            "ebit": None,
            "correction_id": None,
            "correction_version": None,
            "date_present": None,
            "collection_status": "no_reports_2021_2025",
        })

    return rows


def read_completed_inns(output_path):
    if not output_path.exists() or output_path.stat().st_size == 0:
        return set()

    completed = pd.read_csv(
        output_path,
        dtype={"inn": "string"},
        usecols=["inn"],
    )
    return set(completed["inn"].dropna().astype(str))


def read_terminal_error_inns(errors_path):
    """Не повторять заведомо бесполезный поиск отсутствующих в БФО компаний."""
    if not errors_path.exists() or errors_path.stat().st_size == 0:
        return set()

    errors = pd.read_csv(
        errors_path,
        dtype={"inn": "string"},
        usecols=["inn", "error_type"],
    )
    terminal = errors[errors["error_type"].eq("org_not_found")]
    return set(terminal["inn"].dropna().astype(str))


def append_rows(path, rows):
    dataframe = pd.DataFrame(rows)
    write_header = not path.exists() or path.stat().st_size == 0
    dataframe.to_csv(
        path,
        mode="a",
        header=write_header,
        index=False,
        quoting=csv.QUOTE_MINIMAL,
    )


def append_error(path, source_row, inn, error_type, message):
    row = {
        "inn": inn,
        "registry_category": source_row.get("Категория"),
        "registry_okved": source_row.get("ОКВЭД"),
        "error_type": error_type,
        "error_message": message,
    }
    append_rows(path, [row])


def parse_args():
    parser = argparse.ArgumentParser(
        description="Быстрый сбор структурированной отчётности БФО"
    )
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--errors", type=Path, default=DEFAULT_ERRORS)
    parser.add_argument(
        "--limit",
        type=int,
        default=200,
        help="Максимум новых компаний за один запуск; 0 означает без ограничения",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.15,
        help="Пауза между компаниями в секундах",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    logging.getLogger("urllib3").setLevel(logging.WARNING)

    source = pd.read_csv(
        args.input,
        dtype={"ИНН": "string", "ОКВЭД": "string"},
    )
    source["ИНН"] = source["ИНН"].map(normalize_inn)
    source = source.drop_duplicates(subset=["ИНН"]).reset_index(drop=True)

    completed = read_completed_inns(args.output)
    terminal_errors = read_terminal_error_inns(args.errors)
    completed |= terminal_errors
    pending = source[~source["ИНН"].isin(completed)].copy()

    if args.limit > 0:
        pending = pending.head(args.limit)

    total = len(pending)

    print(f"Всего в реестре: {len(source)}")
    print(f"Уже обработано: {len(completed)}")
    print(f"В текущем запуске: {total}")

    if total == 0:
        print("Новых компаний для обработки нет.")
        return

    session = create_session()

    for number, source_row in enumerate(
        pending.to_dict("records"),
        start=1,
    ):
        inn = normalize_inn(source_row["ИНН"])

        try:
            organization = find_organization(session, inn)

            if organization is None:
                append_error(
                    args.errors,
                    source_row,
                    inn,
                    "org_not_found",
                    "Организация не найдена в БФО",
                )
                print(f"[{number}/{total}] {inn}: org_not_found")
                continue

            reports = get_bfo_reports(session, organization["id"])
            rows = build_rows(source_row, organization, reports)
            append_rows(args.output, rows)

            years = sorted(
                row["year"] for row in rows if row.get("year") is not None
            )
            print(f"[{number}/{total}] {inn}: success {years}")

        except Exception as error:
            append_error(
                args.errors,
                source_row,
                inn,
                type(error).__name__,
                str(error),
            )
            print(f"[{number}/{total}] {inn}: ERROR {type(error).__name__}: {error}")

        time.sleep(max(args.delay, 0))

    print("Готово.")
    print(f"Данные: {args.output}")
    print(f"Ошибки: {args.errors}")


if __name__ == "__main__":
    main()
