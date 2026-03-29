#!/usr/bin/env python3
"""
Sync all configured MAX accounts to local SQLite DB.

Usage:
  python sync.py                    # last 6 months, all accounts
  python sync.py --months 12
  python sync.py --from 2024-01
  python sync.py --owner רפאל       # only one account
"""
import argparse
import logging
import sys
from datetime import date

from config import load_config
from crawler import MaxCrawler, AuthError
from database import TransactionDB

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def parse_args():
    p = argparse.ArgumentParser(description="Sync MAX transactions to local DB")
    p.add_argument("--months", type=int, default=6)
    p.add_argument("--from", dest="from_month", metavar="YYYY-MM")
    p.add_argument("--owner", help="Sync only this owner (by name)")
    return p.parse_args()


def main():
    args = parse_args()
    try:
        cfg = load_config()
    except ValueError as e:
        logger.error(str(e))
        sys.exit(1)

    db = TransactionDB(cfg.db_path)
    today = date.today()

    accounts = cfg.accounts
    if args.owner:
        accounts = [a for a in accounts if a.owner == args.owner]
        if not accounts:
            logger.error("No account found with owner '%s'", args.owner)
            sys.exit(1)

    total_fetched = total_inserted = 0

    for account in accounts:
        logger.info("=== Syncing account: %s ===", account.owner)
        crawler = MaxCrawler(cfg, account)
        try:
            if args.from_month:
                try:
                    sy, sm = map(int, args.from_month.split("-"))
                except ValueError:
                    logger.error("--from must be YYYY-MM format")
                    sys.exit(1)
                txns = crawler.fetch_range(sy, sm, today.year, today.month)
            else:
                txns = crawler.fetch_last_n_months(args.months)
        except AuthError as e:
            logger.error("Auth failed for %s: %s", account.owner, e)
            continue

        if not txns:
            logger.warning("No transactions returned for %s", account.owner)
            continue

        inserted = db.upsert(txns, owner=account.owner)
        logger.info(
            "[%s] Fetched %d, inserted %d new",
            account.owner, len(txns), inserted,
        )
        total_fetched += len(txns)
        total_inserted += inserted

    stats = db.stats()
    logger.info(
        "Done. Total fetched %d, inserted %d new. DB total: %d (%s → %s)",
        total_fetched, total_inserted,
        stats["total"], stats["earliest"], stats["latest"],
    )


if __name__ == "__main__":
    main()
