import pandas as pd
from pypdf import PdfReader
import requests
import io
import pymupdf
import pytesseract
import re
import shutil
from pathlib import Path

tesseract_path = shutil.which("tesseract")
if tesseract_path:
    pytesseract.pytesseract.tesseract_cmd = tesseract_path

from PIL import Image

#Здесь лежат все проверенные, в ходе ручной проверки, резы
VERIFIED_AMORTIZATION_OVERRIDES = {
    ("5027006369", 2025): {
        "intangible": 0,
        "total": 19_592,
        "source": (
            "clarification_55282492_page_17_"
            "visual_review"
        )
    }
}

# Функции для ебит

def calculate_ebit_from_financial(financial):
    profit_before_tax = financial.get("current2300")

    if profit_before_tax is None:
        return None

    interest_expense = financial.get("current2330") or 0
    interest_income = financial.get("current2320") or 0

    return (
        profit_before_tax
        + interest_expense
        - interest_income
    )


def get_ebit_by_year(bfo_data):

    result = {}

    for report in bfo_data:
        year = int(report["period"])
        fin = report["typeCorrections"][0]["correction"]["financialResult"]
        ebit = calculate_ebit_from_financial(fin)
        result[year] = ebit
    return result

# Функции для ебита

def calculate_ebita(ebit,intangible_amortization):
    ebita = ebit + intangible_amortization
    return ebita

def get_ebita_by_year(ebit_by_year, amortization_by_year):
    result = {}

    for year in ebit_by_year:
        if year in amortization_by_year:

            ebit = ebit_by_year[year]
            amortization = amortization_by_year[year]

            if ebit is None or amortization is None:
                continue

            ebita = calculate_ebita(
                ebit,
                amortization
            )

            result[year] = ebita

    return result

# Функции для амортизации и оски

def get_amortization_by_year(reader):
    result = {}

    NMA_page_text = None

    for page in reader.pages:
        text = page.extract_text()

        if "Наличие и движение нематериальных активов" in text:
            NMA_page_text = text
            break

    if NMA_page_text is None:
        return None

    start = NMA_page_text.find("3. Нематериальные активы")
    end = NMA_page_text.find("4. Основные средства")

    NMA_text = NMA_page_text[start:end]
    NMA = NMA_text.splitlines()

    amortization_by_year = {}

    for line in NMA:
        if "За 2025 г." in line or "За 2024 г." in line:
            parts = line.split()

            amortization = parts[5]
            year = int(parts[1])

            amortization = amortization.replace("(", "")
            amortization = amortization.replace(")", "")
            amortization = int(amortization)

            amortization_by_year[year] = amortization

    start_OS = NMA_page_text.find("4. Основные средства")
    end_OS = NMA_page_text.find("5. Финансовые вложения")

    OS_text = NMA_page_text[start_OS:end_OS]
    OS = OS_text.splitlines()

    count = 0
    OS_by_year = {}

    for line in OS:
        if "За 2025 г." in line or "За 2024 г." in line:
            parts = line.split()

            half_a = parts[-6]
            half_b = parts[-5]

            res = int(half_a.replace("(", "") + half_b.replace(")", ""))
            year = int(parts[1])
            OS_by_year[year] = res

            count += 1

            if count == 2:
                break

    total_amortization_by_year = {}

    for year in OS_by_year:
        total_amortization = OS_by_year[year] + amortization_by_year[year]
        total_amortization_by_year[year] = total_amortization

    result["intangible"] = amortization_by_year
    result["total"] = total_amortization_by_year

    return result


# Функции для ебитды

def get_ebitda_by_year(ebit_by_year, amortization_by_year):
    result = {}

    for year in ebit_by_year:
        if year in amortization_by_year:

            ebit = ebit_by_year[year]
            amortization = amortization_by_year[year]

            if ebit is None or amortization is None:
                continue

            ebitda = ebit + amortization

            result[year] = ebitda

    return result

#Функции для создания сессии/запросов по реестру через сессию

def create_session():
    session = requests.Session()

    session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) "
            "Version/26.5.2 Safari/605.1.15"
        ),
        "Accept": "*/*",
        "Accept-Language": "ru"
    })

    session.cookies.update({
        "disclaimed": "true",
        "mdd": "1"
    })

    return session

def get_org_id(inn, session):
    url = "https://bo.nalog.gov.ru/advanced-search/organizations/search"

    params = {
        "query": inn,
        "page": 0,
        "size": 20
    }

    headers = {
        "Referer": f"https://bo.nalog.gov.ru/search?query={inn}"
    }

    response = session.get(
        url,
        params=params,
        headers=headers
    )

    if response.status_code != 200:
        return None

    data = response.json()

    if not data["content"]:
        return None

    return data["content"][0]["id"]

def get_bfo_data(org_id, session):
    url = f"https://bo.nalog.gov.ru/nbo/organizations/{org_id}/bfo/"

    headers = {
        "Referer": f"https://bo.nalog.gov.ru/organizations-card/{org_id}"
    }

    response = session.get(
        url,
        headers=headers
    )

    if response.status_code != 200:
        return None

    return response.json()

def get_clarification_id(bfo_data, year):

    for report in bfo_data:
       if int(report["period"]) == year:
            correction = report["typeCorrections"][0]["correction"]
            return correction["id"]
    return None

def get_clarification_reader(clarification_id, session):
    url = f"https://bo.nalog.gov.ru/download/clarification/{clarification_id}"

    response = session.get(url)

    if response.status_code != 200:
        return None

    pdf_file = io.BytesIO(response.content)
    reader = PdfReader(pdf_file)

    return reader

def pdf_has_text(reader):
    for page in reader.pages:
        text = page.extract_text()

        if text and text.strip():
            return True

    return False

def flatten_company_result(company, year):
    ebit_by_year = company.get("ebit") or {}
    ebita_by_year = company.get("ebita") or {}
    ebitda_by_year = company.get("ebitda") or {}

    amortization = company.get("amortization") or {}
    intangible_by_year = (
        amortization.get("intangible") or {}
    )
    total_by_year = (
        amortization.get("total") or {}
    )

    return {
        "inn": str(company.get("inn", "")),
        "org_id": company.get("org_id"),
        "year": year,
        "ebit": ebit_by_year.get(year),
        "intangible_amortization":
            intangible_by_year.get(year),
        "total_amortization":
            total_by_year.get(year),
        "ebita": ebita_by_year.get(year),
        "ebitda": ebitda_by_year.get(year),
        "status": company.get("status"),
        "amortization_source":
            company.get("amortization_source"),
        "error": None
    }

def get_clarification_bytes(clarification_id, session):
    url = f"https://bo.nalog.gov.ru/download/clarification/{clarification_id}"

    response = session.get(url)

    if response.status_code != 200:
        print("Ошибка загрузки PDF")
        return None

    return response.content

def get_total_amortization_from_ocr(ocr_pages, year):
    for page_number, text in ocr_pages.items():

        if "расходы по обычным видам деятельности" not in text.lower():
            continue

        for line in text.splitlines():
            if "амортизация" not in line.lower():
                continue

            parts = line.split()

            numbers = []

            for part in parts[1:]:
                cleaned = (
                    part
                    .replace("[", "")
                    .replace("]", "")
                    .replace("(", "")
                    .replace(")", "")
                    .replace("|", "")
                )

                if cleaned.isdigit():
                    numbers.append(cleaned)


            if len(numbers) == 3:
                if year == 2025:
                    return int(numbers[0] + numbers[1])

                if year == 2024:
                    return int(numbers[2])

            if len(numbers) == 2 and year == 2025:
                return int(numbers[0] + numbers[1])

    return None

def get_intangible_amortization_from_ocr(ocr_pages, year):
    for page_number, text in ocr_pages.items():
        for line in text.splitlines():
            low = line.lower()

            if (
                "нематериальные активы - всего" in low
                and f"за {year}" in low
            ):
                parts = line.split()

                if len(parts) < 3:
                    continue

                if parts[-3].isdigit():
                    return int(parts[-3])

    return None


def get_ocr_pages(pdf_bytes):
    document = pymupdf.open(
        stream=pdf_bytes,
        filetype="pdf"
    )

    ocr_pages = {}

    for i, page in enumerate(document):
        pixmap = page.get_pixmap(dpi=150)

        image = Image.open(
            io.BytesIO(
                pixmap.tobytes("png")
            )
        )

        text = pytesseract.image_to_string(
            image,
            lang="rus"
        )

        candidates = [text]

        # Если обычный OCR почти ничего не увидел,
        # повторяем страницу при 300 DPI и с поворотом.
        if len(text.strip()) < 200:
            high_res_pixmap = page.get_pixmap(dpi=300)

            high_res_image = Image.open(
                io.BytesIO(
                    high_res_pixmap.tobytes("png")
                )
            )

            for angle in (90, -90):
                rotated_image = high_res_image.rotate(
                    angle,
                    expand=True
                )

                rotated_text = pytesseract.image_to_string(
                    rotated_image,
                    lang="rus",
                    config="--psm 6"
                )

                candidates.append(rotated_text)

        text = max(
            candidates,
            key=lambda value: sum(
                char.isalnum()
                for char in value
            )
        )

        ocr_pages[i + 1] = text

    return ocr_pages

def get_amortization_from_ocr_pages(ocr_pages, year):
    intangible = get_intangible_amortization_from_ocr(
        ocr_pages,
        year
    )

    total = get_total_amortization_from_ocr(
        ocr_pages,
        year
    )

    return {
        "intangible": {
            year: intangible
        },
        "total": {
            year: total
        }
    }

def get_amortization_from_ocr(pdf_bytes, year):
    ocr_pages = get_ocr_pages(pdf_bytes)

    return get_amortization_from_ocr_pages(
        ocr_pages,
        year
    )
def amortization_is_valid(amortization, year):
    if amortization is None:
        return False

    intangible = amortization.get("intangible", {})
    total = amortization.get("total", {})

    if year not in intangible:
        return False

    if year not in total:
        return False

    if intangible[year] is None:
        return False

    if total[year] is None:
        return False

    return True

def intangible_amortization_is_valid(amortization, year):
    if amortization is None:
        return False

    value = amortization.get("intangible", {}).get(year)

    return value is not None


def total_amortization_is_valid(amortization, year):
    if amortization is None:
        return False

    value = amortization.get("total", {}).get(year)

    return value is not None

def has_numeric_amortization_disclosure_ocr(ocr_pages):
    for text in ocr_pages.values():
        for line in text.splitlines():
            low = line.lower()

            if "амортиз" not in low:
                continue

            parts = line.split()

            numeric_parts = []

            for part in parts:
                cleaned = (
                    part
                    .replace("(", "")
                    .replace(")", "")
                    .replace("[", "")
                    .replace("]", "")
                    .replace("|", "")
                )

                if cleaned.isdigit():
                    numeric_parts.append(cleaned)

            if numeric_parts:
                return True

    return False

def has_scanned_amortization_table(ocr_pages):
    for text in ocr_pages.values():
        low = text.lower()

        if (
            "наименован" in low
            and "амортиз" in low
            and (
                "переоцен" in low
                or "накоплен" in low
            )
        ):
            return True

    return False

def get_amortization_from_movement_table(reader, year):
    os_amortization = None
    intangible_amortization = None

    for page in reader.pages:
        text = page.extract_text()

        if not text:
            continue

        low = text.lower()


        if (
            "ведомость по ос" in low
            and f"обороты за {year}" in low
        ):

            for line in text.splitlines():
                if not line.strip().lower().startswith("итого"):
                    continue

                parts = line.split()[1:]  # убираем "Итого"

                values = []

                i = 0

                while i < len(parts):
                    current = parts[i]

                    if current.isdigit():
                        if (
                                i + 1 < len(parts)
                                and parts[i + 1].isdigit()
                                and len(parts[i + 1]) == 3
                        ):
                            value = int(
                                current + parts[i + 1]
                            )
                            values.append(value)
                            i += 2
                        else:
                            values.append(
                                int(current)
                            )
                            i += 1

                    else:
                        i += 1

                if len(values) >= 10:
                    os_amortization = values[4]


                    break


        if "нематериальные активы общества" in low:
            for line in text.splitlines():

                if not line.strip().lower().startswith("итого"):
                    continue

                numbers = re.findall(r"\d+", line)

                if numbers:
                    values = [
                        int(number)
                        for number in numbers
                    ]
                    if all(value == 0 for value in values):
                        intangible_amortization = 0
                        break

    if os_amortization is None:
        return None

    if intangible_amortization is None:
        return {
            "intangible": {
                year: None
            },
            "total": {
                year: os_amortization
            }
        }

    return {
        "intangible": {
            year: intangible_amortization
        },
        "total": {
            year: (
                os_amortization
                + intangible_amortization
            )
        }
    }

#Кор функция

def get_company_financials(inn, year, session):
    result = {}

    org_id = get_org_id(inn, session)

    if org_id is None:
        return {
            "inn": inn,
            "status": "org_not_found"
        }

    bfo_data = get_bfo_data(org_id, session)


    if bfo_data is None:
        return {
            "inn": inn,
            "org_id": org_id,
            "status": "bfo_error"
        }

    ebit_by_year = get_ebit_by_year(bfo_data)

    clarification_id = get_clarification_id(
        bfo_data,
        year
    )

    if clarification_id is None:
        return {
            "inn": inn,
            "org_id": org_id,
            "ebit": ebit_by_year,
            "ebita": None,
            "ebitda": None,
            "status": "no_clarification"
        }

    reader = get_clarification_reader(
        clarification_id,
        session
    )

    if reader is None:
        return {
            "inn": inn,
            "org_id": org_id,
            "ebit": ebit_by_year,
            "ebita": None,
            "ebitda": None,
            "status": "pdf_error"
        }

    amortization = None
    status = None
    amortization_source = None

    if pdf_has_text(reader):

        amortization = get_amortization_by_year(
            reader
        )

        if amortization_is_valid(amortization, year):
            status = "success"

        else:

            amortization = get_amortization_from_movement_table(
                reader,
                year
            )

            if amortization_is_valid(amortization, year):
                status = "success_movement_table"

            elif not has_numeric_amortization_disclosure(reader):
                return {
                    "inn": inn,
                    "org_id": org_id,
                    "ebit": ebit_by_year,
                    "ebita": None,
                    "ebitda": None,
                    "status": "no_amortization_disclosure"
                }

            else:
                pdf_bytes = get_clarification_bytes(
                    clarification_id,
                    session
                )

                if pdf_bytes is not None:
                    amortization = get_amortization_from_ocr(
                        pdf_bytes,
                        year
                    )

                if amortization_is_valid(amortization, year):
                    status = "success_ocr_fallback"

                elif amortization_is_empty(amortization, year):
                    status = "no_amortization_disclosure"

                else:
                    status = "parse_error"

    else:
        pdf_bytes = get_clarification_bytes(
            clarification_id,
            session
        )

        if pdf_bytes is None:
            return {
                "inn": inn,
                "org_id": org_id,
                "ebit": ebit_by_year,
                "ebita": None,
                "ebitda": None,
                "status": "pdf_download_error"
            }

        ocr_pages = get_ocr_pages(pdf_bytes)

        amortization = get_amortization_from_ocr_pages(
            ocr_pages,
            year
        )

        if amortization_is_valid(amortization, year):
            status = "success_ocr"

        elif has_scanned_amortization_table(ocr_pages):
            status = "manual_review_scanned_table"

        elif has_numeric_amortization_disclosure_ocr(ocr_pages):
            status = "parse_error_ocr"

        else:
            status = "no_amortization_disclosure"

    ebita_by_year = {}
    ebitda_by_year = {}

    if status == "manual_review_scanned_table":
        override = VERIFIED_AMORTIZATION_OVERRIDES.get(
            (str(inn), year)
        )

        if override is not None:
            amortization = {
                "intangible": {
                    year: override["intangible"]
                },
                "total": {
                    year: override["total"]
                }
            }

            status = "success_verified_override"
            amortization_source = override["source"]

    if intangible_amortization_is_valid(amortization, year):
        ebita_by_year = get_ebita_by_year(
            ebit_by_year,
            amortization["intangible"]
        )

    if total_amortization_is_valid(amortization, year):
        ebitda_by_year = get_ebitda_by_year(
            ebit_by_year,
            amortization["total"]
        )

    if ebita_by_year and ebitda_by_year:
        pass

    elif ebita_by_year or ebitda_by_year:
        status = "partial_success"

    else:
        return {
            "inn": inn,
            "org_id": org_id,
            "ebit": ebit_by_year,
            "ebita": None,
            "ebitda": None,
            "status": status,
            "amortization": amortization,
            "amortization_source": amortization_source
        }

    result["inn"] = inn
    result["org_id"] = org_id
    result["ebit"] = ebit_by_year
    result["ebita"] = ebita_by_year
    result["ebitda"] = ebitda_by_year
    result["status"] = status
    result["amortization"] = amortization
    result["amortization_source"] = amortization_source

    return result

#fallback сценарии для ocrки и парсинга

def has_numeric_amortization_disclosure(reader):
    for page in reader.pages:
        text = page.extract_text()

        if not text:
            continue

        low = text.lower()

        if (
            "амортизация" in low
            or "накопленная амортизация" in low
            or "наличие и движение нематериальных активов" in low
        ):
            for line in text.splitlines():
                line_low = line.lower()

                if "амортиз" in line_low:
                    if any(char.isdigit() for char in line):
                        return True

    return False

def amortization_is_empty(amortization, year):
    if amortization is None:
        return True

    intangible = amortization.get("intangible", {})
    total = amortization.get("total", {})

    intangible_value = intangible.get(year)
    total_value = total.get(year)

    return (
        intangible_value is None
        and total_value is None
    )

def inspect_amortization_disclosure(reader):
    keywords = [
        "амортиз",
        "расходы по обычным видам деятельности",
        "основные средства",
        "нематериальные активы"
    ]

    matches = []

    for page_number, page in enumerate(reader.pages, start=1):
        text = page.extract_text()

        if not text:
            continue

        lines = text.splitlines()

        for line_number, line in enumerate(lines):
            low = line.lower()

            if any(keyword in low for keyword in keywords):

                start = max(0, line_number - 2)
                end = min(len(lines), line_number + 3)

                context = lines[start:end]

                matches.append({
                    "page": page_number,
                    "line": line.strip(),
                    "context": context
                })

    return matches


if __name__ == "__main__":
    base_dir = Path(__file__).resolve().parent
    input_path = base_dir / "construction_companies.csv"
    output_path = base_dir / "ebitda_results_2025_first_20.xlsx"

    target_year = 2025
    batch_size = 20

    source_dataframe = pd.read_csv(
        input_path,
        dtype={
            "ИНН": "string",
            "ОКВЭД": "string"
        }
    )
    source_dataframe["ИНН"] = (
        source_dataframe["ИНН"]
        .str.strip()
        .str.zfill(10)
    )

    source_dataframe = (
        source_dataframe
        .drop_duplicates(subset=["ИНН"])
        .reset_index(drop=True)
    )

    work_dataframe = source_dataframe.head(
        batch_size
    )

    session = create_session()
    all_rows = []

    total_companies = len(work_dataframe)

    for index, source_row in enumerate(
        work_dataframe.to_dict("records"),
        start=1
    ):
        inn = source_row["ИНН"]

        print(
            f"[{index}/{total_companies}]",
            "Обрабатывается ИНН:",
            inn
        )

        try:
            company = get_company_financials(
                inn,
                target_year,
                session
            )

            result_row = flatten_company_result(
                company,
                target_year
            )

        except Exception as e:
            result_row = {
                "inn": str(inn),
                "org_id": None,
                "year": target_year,
                "ebit": None,
                "intangible_amortization": None,
                "total_amortization": None,
                "ebita": None,
                "ebitda": None,
                "status": "error",
                "amortization_source": None,
                "error": (
                    f"{type(e).__name__}: {e}"
                )
            }

        result_row["subject_type"] = (
            source_row["Тип субъекта"]
        )
        result_row["category"] = (
            source_row["Категория"]
        )
        result_row["main_activity"] = (
            source_row["Основной вид деятельности"]
        )
        result_row["okved"] = (
            source_row["ОКВЭД"]
        )

        all_rows.append(result_row)

        print(
            inn,
            result_row["status"],
            "EBITDA:",
            result_row["ebitda"]
        )

    columns = [
        "inn",
        "subject_type",
        "category",
        "main_activity",
        "okved",
        "org_id",
        "year",
        "ebit",
        "intangible_amortization",
        "total_amortization",
        "ebita",
        "ebitda",
        "status",
        "amortization_source",
        "error",
    ]

    result_dataframe = pd.DataFrame(
        all_rows,
        columns=columns
    )

    result_dataframe["inn"] = (
        result_dataframe["inn"]
        .astype("string")
    )

    with pd.ExcelWriter(
        output_path,
        engine="openpyxl"
    ) as writer:
        result_dataframe.to_excel(
            writer,
            sheet_name="EBITDA",
            index=False
        )

        worksheet = writer.sheets["EBITDA"]

        worksheet.freeze_panes = "A2"
        worksheet.auto_filter.ref = (
            worksheet.dimensions
        )

        column_widths = {
            "A": 14,
            "B": 20,
            "C": 22,
            "D": 48,
            "E": 12,
            "F": 12,
            "G": 10,
            "H": 14,
            "I": 25,
            "J": 22,
            "K": 14,
            "L": 14,
            "M": 34,
            "N": 48,
            "O": 35,
        }

        for column, width in column_widths.items():
            worksheet.column_dimensions[
                column
            ].width = width

        for row in worksheet.iter_rows(
            min_row=2,
            min_col=8,
            max_col=12
        ):
            for cell in row:
                cell.number_format = "#,##0.00"

    print(
        "\nОбработано компаний:",
        len(result_dataframe)
    )

    print(
        "Excel-файл сохранён:",
        output_path
    )
