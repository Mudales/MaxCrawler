import json
import os
import time
import uuid
import calendar
import logging
from datetime import date

import requests

from config import Config, AccountConfig, LOGIN_URL

logger = logging.getLogger(__name__)

TRANSACTIONS_URL = (
    "https://www.max.co.il/api/registered/transactionDetails/"
    "getTransactionsAndGraphs"
)
LOGIN_PAGE_URL = "https://www.max.co.il/login"
SESSIONS_DIR = ".sessions"
MAX_RETRIES = 3


class AuthError(Exception):
    pass


class MaxCrawler:
    def __init__(self, config: Config, account: AccountConfig):
        self.config = config
        self.account = account
        self.session = requests.Session()
        self._logged_in = False
        self._cid = str(uuid.uuid4())
        self._sid = str(uuid.uuid4())

    # ── session persistence ───────────────────────────────────────────────────

    def _cookie_path(self) -> str:
        os.makedirs(SESSIONS_DIR, exist_ok=True)
        safe = self.account.owner.replace("/", "_").replace(" ", "_")
        return os.path.join(SESSIONS_DIR, f"{safe}.json")

    def _save_session(self):
        path = self._cookie_path()
        data = {
            "cookies": dict(self.session.cookies),
            "cid": self._cid,
            "sid": self._sid,
        }
        with open(path, "w") as f:
            json.dump(data, f)
        logger.debug("Session saved for %s", self.account.owner)

    def _load_session(self) -> bool:
        path = self._cookie_path()
        if not os.path.exists(path):
            return False
        try:
            with open(path) as f:
                data = json.load(f)
            cookies = data.get("cookies", {})
            if not cookies:
                return False
            self.session.cookies.update(cookies)
            self._cid = data.get("cid", self._cid)
            self._sid = data.get("sid", self._sid)
            logger.info("[%s] Loaded saved session.", self.account.owner)
            return True
        except (json.JSONDecodeError, KeyError):
            return False

    def _clear_session(self):
        self.session.cookies.clear()
        self._logged_in = False
        path = self._cookie_path()
        if os.path.exists(path):
            os.remove(path)

    def _is_session_valid(self) -> bool:
        """Quick check: hit a lightweight authenticated endpoint."""
        try:
            resp = self.session.get(
                "https://www.max.co.il/api/registered/transactionDetails/"
                "getTransactionsAndGraphs",
                params={"filterData": json.dumps({
                    "userIndex": -1, "cardIndex": -1, "monthView": True,
                    "date": date.today().strftime("%Y-%m-%d"),
                    "dates": {"startDate": "0", "endDate": "0"},
                    "bankAccount": {"bankAccountIndex": -1, "cards": None},
                }), "firstCallCardIndex": "-1null", "v": self.config.cav},
                headers=self._base_headers(),
                timeout=10,
            )
            return resp.status_code == 200
        except Exception:
            return False

    # ── auth ─────────────────────────────────────────────────────────────────

    def _base_headers(self, referer: str = "https://www.max.co.il/") -> dict:
        return {
            "User-Agent": self.config.user_agent,
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9",
            "Origin": "https://www.max.co.il",
            "Referer": referer,
            "cav": self.config.cav,
            "cid": self._cid,
            "sid": self._sid,
            "dnt": "1",
            "sec-fetch-dest": "empty",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "same-origin",
        }

    def login(self) -> None:
        logger.info("Initialising session for %s (%s)…",
                    self.account.owner, self.account.username)
        self.session.get(
            LOGIN_PAGE_URL,
            headers={"User-Agent": self.config.user_agent,
                     "Accept": "text/html,application/xhtml+xml,*/*;q=0.8"},
            timeout=15,
        )

        resp = self.session.post(
            LOGIN_URL,
            json={"username": self.account.username,
                  "password": self.account.password,
                  "id": None},
            headers={
                **self._base_headers(
                    "https://www.max.co.il/login"
                    "?ReturnURL=https:%2F%2Fwww.max.co.il%2Fhomepage"
                ),
                "Content-Type": "application/json",
            },
            timeout=20,
        )

        if resp.status_code != 200:
            raise AuthError(
                f"Login failed for {self.account.owner}: "
                f"HTTP {resp.status_code} — {resp.text[:200]}"
            )

        data = resp.json()
        result = data.get("result", {})
        status = result.get("loginStatus") or result.get("status") or ""
        if status.lower() not in ("success", "authenticated", ""):
            if result.get("isError") or data.get("isError"):
                raise AuthError(f"Login rejected for {self.account.owner}: {data}")

        logger.info("Login successful for %s.", self.account.owner)
        self._logged_in = True
        self._save_session()

    def ensure_logged_in(self) -> None:
        if self._logged_in:
            return
        # Try to reuse saved session first
        if self._load_session():
            if self._is_session_valid():
                self._logged_in = True
                logger.info("[%s] Reusing saved session (no re-login needed).",
                            self.account.owner)
                return
            else:
                logger.info("[%s] Saved session expired, logging in fresh.",
                            self.account.owner)
                self._clear_session()
        self.login()

    # ── data fetching ────────────────────────────────────────────────────────

    def _filter_data(self, year: int, month: int) -> str:
        last_day = calendar.monthrange(year, month)[1]
        date_str = f"{year}-{month:02d}-{last_day:02d}"
        payload = {
            "userIndex": -1, "cardIndex": -1, "monthView": True,
            "date": date_str,
            "dates": {"startDate": "0", "endDate": "0"},
            "bankAccount": {"bankAccountIndex": -1, "cards": None},
        }
        return json.dumps(payload, separators=(",", ":"))

    def _do_fetch(self, params: dict) -> requests.Response:
        return self.session.get(
            TRANSACTIONS_URL,
            params=params,
            headers=self._base_headers(
                "https://www.max.co.il/transaction-details/personal"
            ),
            timeout=30,
        )

    @staticmethod
    def _is_auth_error(data: dict) -> bool:
        """Detect session-expired / not-logged-in inside a 200 response body."""
        result = data.get("result") or {}
        if not isinstance(result, dict):
            return True
        status = (result.get("loginStatus") or result.get("status") or "").lower()
        if status in ("sessionexpired", "unauthorized", "notloggedin", "error"):
            return True
        if data.get("isError") or result.get("isError"):
            return True
        return False

    def fetch_month(self, year: int, month: int) -> list[dict]:
        self.ensure_logged_in()
        params = {
            "filterData": self._filter_data(year, month),
            "firstCallCardIndex": "-1null",
            "v": self.config.cav,
        }
        logger.info("[%s] Fetching %d-%02d", self.account.owner, year, month)
        resp = self._do_fetch(params)

        # ── handle HTTP-level auth errors ─────────────────────────────────────
        if resp.status_code in (401, 403):
            logger.warning("[%s] HTTP %d — re-logging in…",
                           self.account.owner, resp.status_code)
            self._clear_session()
            self.login()
            resp = self._do_fetch(params)

        resp.raise_for_status()

        # ── parse JSON — may fail if session silently expired (HTML redirect) ─
        try:
            data = resp.json()
        except ValueError:
            logger.warning("[%s] Non-JSON response for %d-%02d — re-logging in…",
                           self.account.owner, year, month)
            self._clear_session()
            self.login()
            resp = self._do_fetch(params)
            resp.raise_for_status()
            data = resp.json()

        # ── detect auth error inside a 200 JSON body ──────────────────────────
        if self._is_auth_error(data):
            logger.warning("[%s] Auth error in JSON for %d-%02d — re-logging in…",
                           self.account.owner, year, month)
            self._clear_session()
            self.login()
            resp = self._do_fetch(params)
            resp.raise_for_status()
            data = resp.json()

        result = data.get("result") or {}
        transactions = (
            result.get("transactions", [])
            or result.get("transactionList", [])
            or []
        )
        logger.info("  → %d transactions", len(transactions))
        return transactions

    def fetch_range(
        self,
        start_year: int,
        start_month: int,
        end_year: int,
        end_month: int,
        sleep_sec: float = 1.5,
    ) -> list[dict]:
        self.ensure_logged_in()
        all_txns: list[dict] = []
        year, month = start_year, start_month
        while (year, month) <= (end_year, end_month):
            for attempt in range(MAX_RETRIES):
                try:
                    txns = self.fetch_month(year, month)
                    all_txns.extend(txns)
                    break
                except (requests.Timeout, requests.ConnectionError) as e:
                    if attempt < MAX_RETRIES - 1:
                        wait = 5 * (2 ** attempt)   # 5 → 10 → 20 sec
                        logger.warning(
                            "Timeout for %d-%02d (attempt %d/%d), retrying in %ds…",
                            year, month, attempt + 1, MAX_RETRIES, wait,
                        )
                        time.sleep(wait)
                    else:
                        logger.error(
                            "Skipping %d-%02d after %d failed attempts: %s",
                            year, month, MAX_RETRIES, e,
                        )
                except requests.HTTPError as e:
                    logger.error("HTTP error for %d-%02d: %s", year, month, e)
                    break
                except AuthError as e:
                    logger.error("Auth error for %d-%02d: %s", year, month, e)
                    break
            time.sleep(sleep_sec)
            month += 1
            if month > 12:
                month = 1
                year += 1
        return all_txns

    def fetch_last_n_months(self, n: int = 6) -> list[dict]:
        today = date.today()
        end_year, end_month = today.year, today.month
        start_month = end_month - n + 1
        start_year = end_year
        while start_month <= 0:
            start_month += 12
            start_year -= 1
        return self.fetch_range(start_year, start_month, end_year, end_month)
