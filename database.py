import sqlite3
import json


CREATE_TRANSACTIONS = """
CREATE TABLE IF NOT EXISTS transactions (
    id              TEXT PRIMARY KEY,
    card_number     TEXT,
    activity_date   TEXT,
    purchase_date   TEXT,
    merchant_name   TEXT,
    amount          REAL,
    original_amount REAL,
    currency        TEXT,
    plan_name       TEXT,
    category_id     INTEGER,
    installments    INTEGER,
    account_owner   TEXT,
    note            TEXT,
    raw_json        TEXT
);
"""

CREATE_MANUAL = """
CREATE TABLE IF NOT EXISTS manual_expenses (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    activity_date   TEXT,
    merchant_name   TEXT,
    amount          REAL,
    currency        TEXT DEFAULT 'ILS',
    category_id     INTEGER DEFAULT 0,
    account_owner   TEXT,
    note            TEXT,
    recurring_id    INTEGER
);
"""

CREATE_RECURRING = """
CREATE TABLE IF NOT EXISTS recurring_expenses (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    merchant_name TEXT NOT NULL,
    amount        REAL NOT NULL,
    currency      TEXT DEFAULT 'ILS',
    category_id   INTEGER DEFAULT 0,
    account_owner TEXT,
    note          TEXT,
    day_of_month  INTEGER DEFAULT 1,
    active        INTEGER DEFAULT 1,
    start_ym      TEXT,
    end_ym        TEXT
);
"""

# Categories — IDs match MAX's own categoryId field.
# Only IDs confirmed from actual transaction data have real names.
# All others use a neutral "#N" placeholder; edit via the ⚙️ modal.
CREATE_CATEGORIES = """
CREATE TABLE IF NOT EXISTS categories (
    id      INTEGER PRIMARY KEY,
    icon    TEXT,
    name    TEXT
);
"""

DEFAULT_CATEGORIES = [
    (0,  "📦", "אחר"),
    (1,  "📦", "#1"),
    (2,  "⛽", "דלק"),           # סונול
    (3,  "📦", "#3"),
    (4,  "🍦", "קינוחים"),       # אייס
    (5,  "📦", "#5"),
    (6,  "🌐", "אינטרנט"),       # PayPal / Porkbun
    (7,  "🛍️", "קניות"),         # שופרסל / משנת יוסף
    (8,  "🛒", "סופרמרקט"),      # קרביץ
    (9,  "📱", "אפליקציות"),     # UPAPP
    (10, "🚗", "תחבורה וחניה"), # פנגו
    (11, "🏛️", "שירותים עירוניים"), # מועצה דתית
    (12, "📦", "#12"),
    (13, "📞", "תקשורת"),        # פלאפון
    (14, "❤️", "תרומות"),        # איחוד הצלה
    (15, "📦", "#15"),
    (16, "📦", "#16"),
    (17, "🏦", "העברות"),        # PayBox
    (18, "📦", "#18"),
    (19, "📦", "#19"),
    (20, "🍕", "מסעדות"),        # פיצה שמש
    (21, "📦", "#21"),
    (22, "📦", "#22"),
    (23, "📦", "#23"),
    (24, "📦", "#24"),
    (25, "📦", "#25"),
    (26, "🏠", "שכר דירה"),
]


def _row_id(txn: dict) -> str:
    """Stable unique ID — uses card-network-assigned references.
    runtimeReference.id is regenerated on every API call; never use it as a key.
    """
    if txn.get("arn"):
        return str(txn["arn"])
    ref = (txn.get("dealData") or {}).get("refNbr", "")
    if ref:
        return ref
    card = txn.get("shortCardNumber", "")
    d = (txn.get("paymentDate") or "")[:10]
    merchant = txn.get("merchantName", "")
    amount = txn.get("actualPaymentAmount", "")
    return f"{card}_{d}_{merchant}_{amount}"


def _parse(txn: dict, owner: str = "") -> tuple:
    deal = txn.get("dealData") or {}
    return (
        _row_id(txn),
        txn.get("shortCardNumber", ""),
        (txn.get("paymentDate") or "")[:10],
        (txn.get("purchaseDate") or "")[:10],
        txn.get("merchantName", ""),
        txn.get("actualPaymentAmount") or txn.get("amount") or 0.0,
        txn.get("originalAmount") or txn.get("actualPaymentAmount") or 0.0,
        txn.get("originalCurrency", "ILS"),
        txn.get("planName", ""),
        txn.get("categoryId", 0),
        deal.get("originalTerm") or 1,
        owner,
        None,   # note — starts empty
        json.dumps(txn, ensure_ascii=False),
    )


class TransactionDB:
    def __init__(self, db_path: str = "transactions.db"):
        self.path = db_path
        self._init()

    def _init(self):
        with self._conn() as conn:
            conn.execute(CREATE_TRANSACTIONS)
            conn.execute(CREATE_MANUAL)
            conn.execute(CREATE_CATEGORIES)
            conn.execute(CREATE_RECURRING)
            # seed categories (INSERT OR IGNORE keeps user edits)
            conn.executemany(
                "INSERT OR IGNORE INTO categories (id, icon, name) VALUES (?,?,?)",
                DEFAULT_CATEGORIES,
            )
            # column migrations — transactions
            cols = [r[1] for r in conn.execute("PRAGMA table_info(transactions)")]
            for col, defn in [
                ("plan_name",    "TEXT"),
                ("account_owner","TEXT"),
                ("note",         "TEXT"),
            ]:
                if col not in cols:
                    conn.execute(f"ALTER TABLE transactions ADD COLUMN {col} {defn}")
            # column migrations — manual_expenses
            mcols = [r[1] for r in conn.execute("PRAGMA table_info(manual_expenses)")]
            if "recurring_id" not in mcols:
                conn.execute("ALTER TABLE manual_expenses ADD COLUMN recurring_id INTEGER")

    def _conn(self):
        return sqlite3.connect(self.path)

    # ── categories ────────────────────────────────────────────────────────────

    def get_categories(self) -> list[dict]:
        with self._conn() as conn:
            conn.row_factory = sqlite3.Row
            return [dict(r) for r in conn.execute(
                "SELECT id, icon, name FROM categories ORDER BY id"
            ).fetchall()]

    def update_category(self, cat_id: int, name: str, icon: str) -> bool:
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO categories (id, icon, name) VALUES (?,?,?) "
                "ON CONFLICT(id) DO UPDATE SET name=excluded.name, icon=excluded.icon",
                (cat_id, icon, name),
            )
            return True

    def set_transaction_category(self, txn_id: str, cat_id: int, source: str = "max") -> bool:
        table = "transactions" if source == "max" else "manual_expenses"
        with self._conn() as conn:
            cur = conn.execute(
                f"UPDATE {table} SET category_id=? WHERE id=?", (cat_id, txn_id)
            )
            return cur.rowcount > 0

    # ── notes ─────────────────────────────────────────────────────────────────

    def update_note(self, txn_id: str, note: str, source: str = "max") -> bool:
        table = "transactions" if source == "max" else "manual_expenses"
        with self._conn() as conn:
            cur = conn.execute(
                f"UPDATE {table} SET note=? WHERE id=?", (note, txn_id)
            )
            return cur.rowcount > 0

    # ── MAX transactions ──────────────────────────────────────────────────────

    def upsert(self, transactions: list[dict], owner: str = "") -> int:
        inserted = 0
        with self._conn() as conn:
            for txn in transactions:
                row = _parse(txn, owner)
                cur = conn.execute(
                    """
                    INSERT OR IGNORE INTO transactions
                    (id, card_number, activity_date, purchase_date,
                     merchant_name, amount, original_amount, currency,
                     plan_name, category_id, installments, account_owner, note, raw_json)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    row,
                )
                inserted += cur.rowcount
        return inserted

    def all_transactions(self) -> list[dict]:
        with self._conn() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT *, 'max' AS source FROM transactions ORDER BY activity_date DESC"
            ).fetchall()
        return [dict(r) for r in rows]

    # ── manual expenses ───────────────────────────────────────────────────────

    def add_manual(
        self,
        activity_date: str,
        merchant_name: str,
        amount: float,
        category_id: int,
        account_owner: str,
        note: str = "",
        currency: str = "ILS",
    ) -> int:
        with self._conn() as conn:
            cur = conn.execute(
                """INSERT INTO manual_expenses
                   (activity_date, merchant_name, amount, currency,
                    category_id, account_owner, note)
                   VALUES (?,?,?,?,?,?,?)""",
                (activity_date, merchant_name, amount, currency,
                 category_id, account_owner, note),
            )
            return cur.lastrowid

    def delete_manual(self, expense_id: int) -> bool:
        with self._conn() as conn:
            cur = conn.execute(
                "DELETE FROM manual_expenses WHERE id = ?", (expense_id,)
            )
            return cur.rowcount > 0

    def all_manual(self) -> list[dict]:
        with self._conn() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT *, 'manual' AS source FROM manual_expenses ORDER BY activity_date DESC"
            ).fetchall()
        return [dict(r) for r in rows]

    # ── combined ──────────────────────────────────────────────────────────────

    def all(self) -> list[dict]:
        return self.all_transactions() + self.all_manual()

    def stats(self) -> dict:
        with self._conn() as conn:
            total = conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
            earliest = conn.execute("SELECT MIN(activity_date) FROM transactions").fetchone()[0]
            latest   = conn.execute("SELECT MAX(activity_date) FROM transactions").fetchone()[0]
        return {"total": total, "earliest": earliest, "latest": latest}

    # ── reset ─────────────────────────────────────────────────────────────────

    def reset_db(self, keep_categories: bool = False) -> dict:
        """Drop and recreate transaction/manual tables. Optionally reset categories too."""
        with self._conn() as conn:
            conn.execute("DROP TABLE IF EXISTS transactions")
            conn.execute("DROP TABLE IF EXISTS manual_expenses")
            if not keep_categories:
                conn.execute("DROP TABLE IF EXISTS categories")
            conn.execute(CREATE_TRANSACTIONS)
            conn.execute(CREATE_MANUAL)
            if not keep_categories:
                conn.execute(CREATE_CATEGORIES)
                conn.executemany(
                    "INSERT INTO categories (id, icon, name) VALUES (?,?,?)",
                    DEFAULT_CATEGORIES,
                )
        return {"ok": True, "kept_categories": keep_categories}

    # ── recurring expenses ────────────────────────────────────────────────────

    def get_recurring(self) -> list[dict]:
        with self._conn() as conn:
            conn.row_factory = sqlite3.Row
            return [dict(r) for r in conn.execute(
                "SELECT * FROM recurring_expenses ORDER BY id"
            ).fetchall()]

    def add_recurring(self, merchant_name: str, amount: float, currency: str,
                      category_id: int, account_owner: str, note: str,
                      day_of_month: int, start_ym: str, end_ym: str = "") -> int:
        with self._conn() as conn:
            cur = conn.execute(
                """INSERT INTO recurring_expenses
                   (merchant_name, amount, currency, category_id, account_owner,
                    note, day_of_month, active, start_ym, end_ym)
                   VALUES (?,?,?,?,?,?,?,1,?,?)""",
                (merchant_name, amount, currency, category_id, account_owner,
                 note, day_of_month, start_ym, end_ym or None),
            )
            return cur.lastrowid

    def update_recurring(self, rec_id: int, **fields) -> bool:
        allowed = {"merchant_name", "amount", "currency", "category_id",
                   "account_owner", "note", "day_of_month", "active", "start_ym", "end_ym"}
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return False
        sql = ", ".join(f"{k}=?" for k in updates)
        with self._conn() as conn:
            cur = conn.execute(
                f"UPDATE recurring_expenses SET {sql} WHERE id=?",
                (*updates.values(), rec_id),
            )
            return cur.rowcount > 0

    def delete_recurring(self, rec_id: int) -> bool:
        with self._conn() as conn:
            conn.execute(
                "DELETE FROM manual_expenses WHERE recurring_id=?", (rec_id,)
            )
            cur = conn.execute(
                "DELETE FROM recurring_expenses WHERE id=?", (rec_id,)
            )
            return cur.rowcount > 0

    def generate_recurring(self, year: int, month: int) -> int:
        """Insert manual_expense entries for active recurring rules that haven't
        been generated yet for the given month. Returns number of new entries."""
        import calendar as _cal
        ym = f"{year}-{month:02d}"
        last_day = _cal.monthrange(year, month)[1]
        generated = 0
        with self._conn() as conn:
            rules = conn.execute(
                """SELECT * FROM recurring_expenses
                   WHERE active=1
                     AND (start_ym IS NULL OR start_ym <= ?)
                     AND (end_ym   IS NULL OR end_ym   >= ?)""",
                (ym, ym),
            ).fetchall()
            for r in rules:
                already = conn.execute(
                    "SELECT 1 FROM manual_expenses WHERE recurring_id=? AND activity_date LIKE ?",
                    (r[0], f"{ym}%"),
                ).fetchone()
                if already:
                    continue
                day = min(r[7], last_day)   # day_of_month clamped to month length
                activity_date = f"{ym}-{day:02d}"
                conn.execute(
                    """INSERT INTO manual_expenses
                       (activity_date, merchant_name, amount, currency,
                        category_id, account_owner, note, recurring_id)
                       VALUES (?,?,?,?,?,?,?,?)""",
                    (activity_date, r[1], r[2], r[3], r[4], r[5], r[6], r[0]),
                )
                generated += 1
        return generated

    def generate_recurring_up_to_today(self) -> int:
        """Generate recurring entries for all months from the earliest start_ym
        up to the current month."""
        from datetime import date as _date
        today = _date.today()
        with self._conn() as conn:
            row = conn.execute(
                "SELECT MIN(start_ym) FROM recurring_expenses WHERE active=1"
            ).fetchone()[0]
        if not row:
            return 0
        y, m = map(int, row.split("-"))
        total = 0
        while (y, m) <= (today.year, today.month):
            total += self.generate_recurring(y, m)
            m += 1
            if m > 12:
                m = 1
                y += 1
        return total
