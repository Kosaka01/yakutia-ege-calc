import argparse
import json
import math
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd


def to_int(value):
    if value is None:
        return 0
    if isinstance(value, float) and math.isnan(value):
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def to_str(value):
    if value is None:
        return ""
    if isinstance(value, float) and math.isnan(value):
        return ""
    return str(value).strip()


def build_unit_map(xlsx_path):
    try:
        units_df = pd.read_excel(xlsx_path, sheet_name="УчП")
    except ValueError:
        return {}
    units = {}
    for _, row in units_df.iterrows():
        code = to_str(row.get("УчП"))
        name = to_str(row.get("Расшифровка"))
        if code:
            units[code] = name
    return units


def main():
    parser = argparse.ArgumentParser(description="Convert data.xlsx to programs.json")
    parser.add_argument("--input", default="files/data.xlsx")
    parser.add_argument("--output", default="data/programs.json")
    args = parser.parse_args()

    xlsx_path = Path(args.input)
    if not xlsx_path.exists():
        raise SystemExit(f"Input not found: {xlsx_path}")

    df = pd.read_excel(xlsx_path, sheet_name="Основной")
    df = df[df["Наименование образовательной программы"].notna()].copy()

    unit_map = build_unit_map(xlsx_path)

    programs = []
    for _, row in df.iterrows():
        unit_code = to_str(row.get("УчП"))
        program = {
            "university": to_str(row.get("Наименование ВУЗа")),
            "location": to_str(row.get("Месторасположение")),
            "unitCode": unit_code,
            "unitName": unit_map.get(unit_code, ""),
            "programCode": to_str(row.get("Код НПС")),
            "programName": to_str(row.get("Наименование образовательной программы")),
            "seats": {
                "fullTime": {
                    "budget": to_int(row.get("Количество мест для приема на обучение по очной форме в рамках КЦП (бюджетные места)")),
                    "paid": to_int(row.get("Количество мест для приема на обучение по очной форме по ДОПОУ (платный прием)")),
                },
                "partTime": {
                    "budget": to_int(row.get("Количество мест для приема на обучение по очно-заочной форме в рамках КЦП (бюджетные места)")),
                    "paid": to_int(row.get("Количество мест для приема на обучение по очно-заочной форме по ДОПОУ (платный прием)")),
                },
                "extramural": {
                    "budget": to_int(row.get("Количество мест для приема на обучение по заочной форме в рамках КЦП (бюджетные места)")),
                    "paid": to_int(row.get("Количество мест для приема на обучение по заочной форме по ДОПОУ (платный прием)")),
                },
            },
            "examsRaw": to_str(
                row.get(
                    "Перечень вступительных испытаний для поступающих на базе СОО и минимальное количество баллов"
                )
            ),
        }
        programs.append(program)

    payload = {
        "generatedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "source": str(xlsx_path),
        "programs": programs,
    }

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    print(f"Wrote {len(programs)} programs to {output_path}")


if __name__ == "__main__":
    main()
