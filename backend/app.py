import json
import os
import re
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests
from dotenv import load_dotenv
from flask import Flask, abort, jsonify, request, send_from_directory

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / \"backend\" / \".env\")
DATA_PATH = ROOT / "data" / "programs.json"
DB_PATH = ROOT / "backend" / "app.db"

SHOP_ID = os.getenv("YOOKASSA_SHOP_ID", "")
SECRET_KEY = os.getenv("YOOKASSA_SECRET_KEY", "")
BASE_URL = os.getenv("PUBLIC_BASE_URL", "http://localhost:5000")
PRICE_RUB = os.getenv("PRICE_RUB", "10.00")
CURRENCY = "RUB"
PAYMENT_DESCRIPTION = os.getenv("PAYMENT_DESCRIPTION", "Доступ к результату калькулятора ЕГЭ")

SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASS = os.getenv("SMTP_PASS", "")
SMTP_FROM = os.getenv("SMTP_FROM", "")

EGE_SUBJECTS = {
    "Русский язык",
    "Математика",
    "Физика",
    "Информатика",
    "Химия",
    "Биология",
    "География",
    "История",
    "Обществознание",
    "Литература",
    "Иностранный язык",
}

SUBJECT_ALIASES = {
    "Иностранный язык (английский)": "Иностранный язык",
}


app = Flask(__name__)
init_db()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with get_db() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS orders (
                id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                status TEXT NOT NULL,
                payment_id TEXT,
                payment_status TEXT,
                amount TEXT NOT NULL,
                email TEXT,
                send_email INTEGER NOT NULL,
                payload_json TEXT NOT NULL,
                results_json TEXT,
                last_error TEXT
            )
            """
        )


def normalize_name(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def canonical_subject(subject: str) -> str:
    if not subject:
        return ""
    normalized = normalize_name(subject)
    if normalized in SUBJECT_ALIASES:
        return SUBJECT_ALIASES[normalized]
    without_parens = re.sub(r"\s*\([^)]*\)", "", normalized).strip()
    return SUBJECT_ALIASES.get(without_parens, without_parens)


def parse_requirements(raw: str) -> Dict[str, Any]:
    if not raw:
        return {"groups": [], "hasAdditional": False}

    groups = []
    for part in raw.split(";"):
        part = part.strip()
        if not part:
            continue
        options = []
        for option in part.split("/"):
            option = option.strip()
            if not option:
                continue
            matches = list(re.finditer(r"\d+", option))
            min_score = None
            subject_text = option
            if matches:
                last = matches[-1]
                min_score = int(last.group())
                subject_text = option[: last.start()]
            subject = re.sub(r"[\-–—]\s*$", "", subject_text)
            subject = re.sub(r"\s*б\.?\s*$", "", subject).strip()
            canonical = canonical_subject(subject)
            is_additional = canonical not in EGE_SUBJECTS
            options.append(
                {
                    "subject": subject or option,
                    "canonical": canonical,
                    "minScore": min_score,
                    "isAdditional": is_additional,
                }
            )
        group_has_additional = any(opt["isAdditional"] for opt in options)
        group_has_ege = any(not opt["isAdditional"] for opt in options)
        groups.append(
            {
                "options": options,
                "hasAdditional": group_has_additional,
                "hasEge": group_has_ege,
            }
        )

    has_additional = any(group["hasAdditional"] for group in groups)
    return {"groups": groups, "hasAdditional": has_additional}


def load_programs() -> List[Dict[str, Any]]:
    with DATA_PATH.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    programs = payload.get("programs", [])
    for program in programs:
        program["requirements"] = parse_requirements(program.get("examsRaw", ""))
    return programs


def build_metadata(programs: List[Dict[str, Any]]) -> Dict[str, Any]:
    cities = sorted({program.get("location") for program in programs if program.get("location")})
    return {
        "totalPrograms": len(programs),
        "cities": cities,
        "priceRub": PRICE_RUB,
    }


def sanitize_scores(raw_scores: Dict[str, Any]) -> Dict[str, int]:
    scores: Dict[str, int] = {}
    for subject in EGE_SUBJECTS:
        value = raw_scores.get(subject)
        if value is None or value == "":
            continue
        try:
            numeric = int(value)
        except (TypeError, ValueError):
            continue
        scores[subject] = max(0, min(100, numeric))
    return scores


def has_any_score(scores: Dict[str, int]) -> bool:
    return any(value > 0 for value in scores.values())


def program_has_selected_form(program: Dict[str, Any], selected_forms: List[str]) -> bool:
    if not selected_forms:
        return False
    for key in selected_forms:
        seats = program.get("seats", {}).get(key, {})
        if (seats.get("budget", 0) or 0) + (seats.get("paid", 0) or 0) > 0:
            return True
    return False


def is_program_eligible(program: Dict[str, Any], scores: Dict[str, int], include_additional: bool) -> bool:
    requirements = program.get("requirements", {"groups": [], "hasAdditional": False})
    if not requirements["groups"]:
        return True
    if not include_additional and requirements["hasAdditional"]:
        return False

    for group in requirements["groups"]:
        satisfied = False
        for option in group["options"]:
            if option["isAdditional"]:
                continue
            score = scores.get(option["canonical"])
            min_score = option["minScore"] or 0
            if score is not None and score >= min_score:
                satisfied = True
                break
        if not satisfied and include_additional and group["hasAdditional"]:
            satisfied = True
        if not satisfied:
            return False
    return True


def slim_program(program: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "university": program.get("university"),
        "location": program.get("location"),
        "unitCode": program.get("unitCode"),
        "unitName": program.get("unitName"),
        "programCode": program.get("programCode"),
        "programName": program.get("programName"),
        "seats": program.get("seats"),
        "requirements": program.get("requirements"),
    }


def calculate_results(payload: Dict[str, Any], programs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    scores = sanitize_scores(payload.get("scores", {}))
    include_additional = bool(payload.get("filters", {}).get("includeAdditional", False))
    selected_city = payload.get("filters", {}).get("city", "all")
    selected_forms = payload.get("filters", {}).get("forms", [])

    matched = []
    for program in programs:
        if selected_city != "all" and program.get("location") != selected_city:
            continue
        if not program_has_selected_form(program, selected_forms):
            continue
        if not is_program_eligible(program, scores, include_additional):
            continue
        matched.append(slim_program(program))
    return matched


def create_order(payload: Dict[str, Any], email: str, send_email: bool) -> str:
    order_id = str(uuid.uuid4())
    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO orders (id, created_at, status, amount, email, send_email, payload_json)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                order_id,
                now_iso(),
                "pending",
                PRICE_RUB,
                email,
                1 if send_email else 0,
                json.dumps(payload, ensure_ascii=False),
            ),
        )
    return order_id


def update_order_payment(order_id: str, payment_id: str, payment_status: str) -> None:
    with get_db() as conn:
        conn.execute(
            """
            UPDATE orders
            SET payment_id = ?, payment_status = ?
            WHERE id = ?
            """,
            (payment_id, payment_status, order_id),
        )


def update_order_status(order_id: str, status: str, payment_status: str = "") -> None:
    with get_db() as conn:
        conn.execute(
            """
            UPDATE orders
            SET status = ?, payment_status = ?
            WHERE id = ?
            """,
            (status, payment_status, order_id),
        )


def update_order_results(order_id: str, results: List[Dict[str, Any]]) -> None:
    with get_db() as conn:
        conn.execute(
            """
            UPDATE orders
            SET results_json = ?
            WHERE id = ?
            """,
            (json.dumps(results, ensure_ascii=False), order_id),
        )


def set_order_error(order_id: str, message: str) -> None:
    with get_db() as conn:
        conn.execute(
            """
            UPDATE orders
            SET last_error = ?
            WHERE id = ?
            """,
            (message, order_id),
        )


def get_order(order_id: str) -> Optional[sqlite3.Row]:
    with get_db() as conn:
        row = conn.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
    return row


def request_payment(order_id: str) -> Dict[str, Any]:
    if not SHOP_ID or not SECRET_KEY:
        raise RuntimeError("YooKassa credentials are not configured")

    headers = {
        "Idempotence-Key": str(uuid.uuid4()),
        "Content-Type": "application/json",
    }

    payload = {
        "amount": {"value": PRICE_RUB, "currency": CURRENCY},
        "capture": True,
        "confirmation": {
            "type": "redirect",
            "return_url": f"{BASE_URL}/?order_id={order_id}",
        },
        "description": PAYMENT_DESCRIPTION,
        "metadata": {"order_id": order_id},
    }

    response = requests.post(
        "https://api.yookassa.ru/v3/payments",
        auth=(SHOP_ID, SECRET_KEY),
        headers=headers,
        json=payload,
        timeout=20,
    )
    response.raise_for_status()
    return response.json()


def fetch_payment(payment_id: str) -> Dict[str, Any]:
    response = requests.get(
        f"https://api.yookassa.ru/v3/payments/{payment_id}",
        auth=(SHOP_ID, SECRET_KEY),
        timeout=20,
    )
    response.raise_for_status()
    return response.json()


def send_email_results(email: str, results: List[Dict[str, Any]]) -> None:
    if not (SMTP_HOST and SMTP_USER and SMTP_PASS and SMTP_FROM):
        return

    from email.message import EmailMessage
    import smtplib

    lines = ["Ваши результаты по калькулятору ЕГЭ:", ""]
    if not results:
        lines.append("Подходящих программ не найдено.")
    else:
        for item in results:
            title = f"{item.get('programCode', '')} - {item.get('programName', '')}".strip(" -")
            uni = item.get("university", "")
            unit = item.get("unitName") or item.get("unitCode") or ""
            lines.append(f"{uni}")
            if unit:
                lines.append(f"  {unit}")
            lines.append(f"  {title}")
            lines.append("")

    msg = EmailMessage()
    msg["Subject"] = "Результаты калькулятора ЕГЭ"
    msg["From"] = SMTP_FROM
    msg["To"] = email
    msg.set_content("\n".join(lines))

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
        server.starttls()
        server.login(SMTP_USER, SMTP_PASS)
        server.send_message(msg)


PROGRAMS = load_programs()
METADATA = build_metadata(PROGRAMS)


@app.get("/")
def serve_index():
    return send_from_directory(ROOT, "index.html")


@app.get("/<path:filename>")
def serve_static(filename: str):
    allowed = {"styles.css", "app.js", "favicon.ico"}
    if filename not in allowed:
        abort(404)
    return send_from_directory(ROOT, filename)


@app.get("/api/metadata")
def api_metadata():
    return jsonify(METADATA)


@app.post("/api/create-payment")
def api_create_payment():
    payload = request.get_json(silent=True) or {}
    raw_scores = payload.get("scores", {})
    scores = sanitize_scores(raw_scores)
    if not has_any_score(scores):
        return jsonify({"error": "Введите хотя бы один предмет"}), 400

    filters = payload.get("filters", {})
    selected_forms = filters.get("forms", [])
    if not selected_forms:
        return jsonify({"error": "Выберите хотя бы одну форму обучения"}), 400

    send_email = bool(payload.get("sendEmail", False))
    email = (payload.get("email") or "").strip()
    if send_email and not email:
        return jsonify({"error": "Укажите e-mail для отправки результата"}), 400

    order_id = create_order(payload, email, send_email)

    try:
        payment = request_payment(order_id)
    except Exception as exc:  # noqa: BLE001
        set_order_error(order_id, str(exc))
        return jsonify({"error": "Не удалось создать платеж"}), 500

    update_order_payment(order_id, payment.get("id", ""), payment.get("status", ""))

    confirmation_url = payment.get("confirmation", {}).get("confirmation_url")
    if not confirmation_url:
        return jsonify({"error": "Платеж создан без confirmation_url"}), 500

    return jsonify({"orderId": order_id, "confirmationUrl": confirmation_url})


@app.get("/api/payment-status")
def api_payment_status():
    order_id = request.args.get("order_id", "").strip()
    if not order_id:
        return jsonify({"error": "order_id is required"}), 400

    order = get_order(order_id)
    if order is None:
        return jsonify({"error": "order not found"}), 404

    if order["status"] == "paid" and order["results_json"]:
        results = json.loads(order["results_json"])
        return jsonify({"paid": True, "status": order["status"], "results": results})

    if order["status"] != "paid" and order["payment_id"]:
        try:
            verified = fetch_payment(order["payment_id"])
        except Exception as exc:  # noqa: BLE001
            set_order_error(order_id, str(exc))
            return jsonify({"paid": False, "status": order["status"]})

        if verified.get("status") == "succeeded":
            payload = json.loads(order["payload_json"])
            results = calculate_results(payload, PROGRAMS)
            update_order_results(order_id, results)
            update_order_status(order_id, "paid", verified.get("status", ""))
            if order["send_email"] and order["email"]:
                send_email_results(order["email"], results)
            return jsonify({"paid": True, "status": "paid", "results": results})

    return jsonify({"paid": order["status"] == "paid", "status": order["status"]})


@app.post("/api/yookassa/webhook")
def api_yookassa_webhook():
    event = request.get_json(silent=True) or {}
    event_type = event.get("event")
    payment = event.get("object") or {}
    payment_id = payment.get("id")
    metadata = payment.get("metadata") or {}
    order_id = metadata.get("order_id")

    if not payment_id or not order_id:
        return jsonify({"status": "ignored"})

    try:
        verified = fetch_payment(payment_id)
    except Exception as exc:  # noqa: BLE001
        set_order_error(order_id, str(exc))
        return jsonify({"status": "error"}), 500

    status = verified.get("status", "")
    verified_order_id = (verified.get("metadata") or {}).get("order_id")
    if verified_order_id and verified_order_id != order_id:
        return jsonify({"status": "ignored"})

    if event_type == "payment.succeeded" and status == "succeeded":
        order = get_order(order_id)
        if order is None:
            return jsonify({"status": "ignored"})
        payload = json.loads(order["payload_json"])
        results = calculate_results(payload, PROGRAMS)
        update_order_results(order_id, results)
        update_order_status(order_id, "paid", status)
        if order["send_email"] and order["email"]:
            send_email_results(order["email"], results)
    elif event_type == "payment.canceled":
        update_order_status(order_id, "canceled", status)

    return jsonify({"status": "ok"})


if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=5000, debug=True)
