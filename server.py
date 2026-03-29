#!/usr/bin/env python3
"""
Flask server — serves the MAX dashboard.

Run with:  python server.py
Open:      http://localhost:5000
"""
import os
import subprocess
import sys
import logging

from flask import Flask, jsonify, request, send_file

from config import load_config
from database import TransactionDB

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

app = Flask(__name__)

try:
    cfg = load_config()
    db = TransactionDB(cfg.db_path)
except ValueError as e:
    logging.error(str(e))
    db = None
    cfg = None

_default_owner = cfg.accounts[0].owner if cfg and cfg.accounts else ""

# Generate recurring expenses for the current month on startup
if db is not None:
    try:
        db.generate_recurring_up_to_today()
    except Exception as e:
        logging.warning("generate_recurring on startup failed: %s", e)


def _enrich(row: dict, cat_lookup: dict) -> dict:
    cat_id = int(row.get("category_id") or 0)
    cat = cat_lookup.get(cat_id, {"icon": "📦", "name": "אחר"})
    row["category_icon"] = cat["icon"]
    row["category_name"] = cat["name"]
    if not row.get("account_owner"):
        row["account_owner"] = _default_owner
    return row


# ── routes ─────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return send_file("max.html")


@app.route("/api/owners")
def owners():
    if cfg is None:
        return jsonify([])
    return jsonify([{"name": a.owner, "username": a.username} for a in cfg.accounts])


@app.route("/api/categories", methods=["GET"])
def get_categories():
    if db is None:
        return jsonify([])
    return jsonify(db.get_categories())


@app.route("/api/categories/<int:cat_id>", methods=["PATCH"])
def patch_category(cat_id):
    if db is None:
        return jsonify({"error": "No database"}), 500
    body = request.get_json(silent=True) or {}
    name = body.get("name", "").strip()
    icon = body.get("icon", "📦").strip()
    if not name:
        return jsonify({"error": "name required"}), 400
    db.update_category(cat_id, name, icon)
    return jsonify({"ok": True})


@app.route("/api/transactions")
def transactions():
    if db is None:
        return jsonify({"error": "No database — check .env"}), 500
    cats = {c["id"]: c for c in db.get_categories()}
    rows = [_enrich(r, cats) for r in db.all()]
    return jsonify(rows)


@app.route("/api/transaction/<txn_id>/category", methods=["PATCH"])
def patch_txn_category(txn_id):
    if db is None:
        return jsonify({"error": "No database"}), 500
    body = request.get_json(silent=True) or {}
    cat_id = body.get("category_id")
    source = body.get("source", "max")
    if cat_id is None:
        return jsonify({"error": "category_id required"}), 400
    ok = db.set_transaction_category(txn_id, int(cat_id), source)
    return jsonify({"ok": ok})


@app.route("/api/transaction/<txn_id>/note", methods=["PATCH"])
def patch_note(txn_id):
    if db is None:
        return jsonify({"error": "No database"}), 500
    body = request.get_json(silent=True) or {}
    source = body.get("source", "max")
    note = body.get("note", "")
    ok = db.update_note(txn_id, note, source)
    return jsonify({"ok": ok})


@app.route("/api/manual", methods=["POST"])
def add_manual():
    if db is None:
        return jsonify({"error": "No database"}), 500
    body = request.get_json(silent=True) or {}
    missing = [f for f in ("activity_date", "merchant_name", "amount", "account_owner")
               if not body.get(f)]
    if missing:
        return jsonify({"error": f"Missing: {missing}"}), 400
    new_id = db.add_manual(
        activity_date=body["activity_date"],
        merchant_name=body["merchant_name"],
        amount=float(body["amount"]),
        category_id=int(body.get("category_id", 0)),
        account_owner=body["account_owner"],
        note=body.get("note", ""),
        currency=body.get("currency", "ILS"),
    )
    return jsonify({"ok": True, "id": new_id})


@app.route("/api/manual/<int:expense_id>", methods=["DELETE"])
def delete_manual(expense_id):
    if db is None:
        return jsonify({"error": "No database"}), 500
    ok = db.delete_manual(expense_id)
    return jsonify({"ok": ok})


@app.route("/api/recurring", methods=["GET"])
def get_recurring():
    if db is None:
        return jsonify([])
    return jsonify(db.get_recurring())


@app.route("/api/recurring", methods=["POST"])
def add_recurring():
    if db is None:
        return jsonify({"error": "No database"}), 500
    body = request.get_json(silent=True) or {}
    missing = [f for f in ("merchant_name", "amount", "account_owner", "start_ym")
               if not body.get(f)]
    if missing:
        return jsonify({"error": f"Missing: {missing}"}), 400
    new_id = db.add_recurring(
        merchant_name=body["merchant_name"],
        amount=float(body["amount"]),
        currency=body.get("currency", "ILS"),
        category_id=int(body.get("category_id", 0)),
        account_owner=body["account_owner"],
        note=body.get("note", ""),
        day_of_month=int(body.get("day_of_month", 1)),
        start_ym=body["start_ym"],
        end_ym=body.get("end_ym", ""),
    )
    db.generate_recurring_up_to_today()
    return jsonify({"ok": True, "id": new_id})


@app.route("/api/recurring/<int:rec_id>", methods=["PATCH"])
def patch_recurring(rec_id):
    if db is None:
        return jsonify({"error": "No database"}), 500
    body = request.get_json(silent=True) or {}
    ok = db.update_recurring(rec_id, **body)
    if ok:
        db.generate_recurring_up_to_today()
    return jsonify({"ok": ok})


@app.route("/api/recurring/<int:rec_id>", methods=["DELETE"])
def delete_recurring(rec_id):
    if db is None:
        return jsonify({"error": "No database"}), 500
    ok = db.delete_recurring(rec_id)
    return jsonify({"ok": ok})


@app.route("/api/recurring/generate", methods=["POST"])
def generate_recurring():
    if db is None:
        return jsonify({"error": "No database"}), 500
    n = db.generate_recurring_up_to_today()
    return jsonify({"ok": True, "generated": n})


@app.route("/api/reset", methods=["POST"])
def reset_db():
    if db is None:
        return jsonify({"error": "No database"}), 500
    body = request.get_json(silent=True) or {}
    keep_categories = bool(body.get("keep_categories", False))
    result = db.reset_db(keep_categories=keep_categories)
    return jsonify(result)


@app.route("/api/sync", methods=["POST"])
def sync():
    body = request.get_json(silent=True) or {}
    months = int(body.get("months", 6))
    from_month = body.get("from_month", "")
    owner = body.get("owner", "")

    args = [sys.executable, "sync.py"]
    args += ["--from", from_month] if from_month else ["--months", str(months)]
    if owner:
        args += ["--owner", owner]

    result = subprocess.run(args, capture_output=True, text=True, cwd=".")
    return jsonify({"ok": result.returncode == 0, "log": result.stdout + result.stderr})


if __name__ == "__main__":
    host = os.getenv("FLASK_HOST", "0.0.0.0")
    port = int(os.getenv("FLASK_PORT", "5000"))
    debug = os.getenv("FLASK_DEBUG", "0") == "1"
    app.run(host=host, port=port, debug=debug)
