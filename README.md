# MaxCrawler

A self-hosted dashboard for tracking MAX credit card transactions.
Fetches data directly from the MAX API using your login credentials, stores it locally in SQLite, and serves an interactive web dashboard.

## Features

- **Automatic login** — authenticates with username + password (no manual cookie copying)
- **Session persistence** — saved sessions reused across syncs; re-login only when expired
- **Multi-account** — sync multiple MAX accounts and filter by person in the dashboard
- **Manual expenses** — log cash, transfers, or Bit payments with category and attribution
- **Category editing** — click any category badge in the table to correct it; survives future syncs
- **Docker support** — run anywhere with a single command

## Quick start

### Local

```bash
pip install -r requirements.txt

cp .env.example .env
# edit .env with your credentials

python sync.py --months 6    # fetch last 6 months
python server.py             # open http://localhost:5000
```

### Docker

```bash
cp .env.example .env
# edit .env with your credentials

docker compose up -d         # open http://localhost:5000
```

To sync inside the container:
```bash
docker compose exec maxcrawler python sync.py --months 6
```

## Configuration (`.env`)

```env
# Account 1
MAX_USERNAME_1=your@email.com
MAX_PASSWORD_1=yourpassword
MAX_OWNER_1=רפאל

# Account 2 (optional)
MAX_USERNAME_2=partner@email.com
MAX_PASSWORD_2=partnerpassword
MAX_OWNER_2=תמר

# API version string (update from DevTools → cav header if requests fail)
MAX_CAV=V4.209-RC.14.88

# Database file path
DB_PATH=transactions.db

# Server (change for Docker / remote access)
FLASK_HOST=0.0.0.0
FLASK_PORT=5000
```

## Sync CLI

```bash
python sync.py                  # last 6 months, all accounts
python sync.py --months 12      # last 12 months
python sync.py --from 2024-01   # from a specific month to today
python sync.py --owner רפאל     # one account only
```

Sync is also available from the dashboard UI via the 🔄 button.

## Project structure

```
MaxCrawler/
├── config.py          — load credentials and settings from .env
├── crawler.py         — MAX API client (login, session persistence, retry on timeout)
├── database.py        — SQLite storage (transactions + manual expenses)
├── sync.py            — CLI sync tool
├── server.py          — Flask API server
├── max.html           — web dashboard (vanilla JS + Chart.js)
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── .env.example
```

## Session persistence

After a successful login, session cookies are saved to `.sessions/<owner>.json`.
On the next sync the saved session is reused — no re-login unless the session has expired.

## Notes

- MAX session cookies expire after a few hours of inactivity. The crawler detects this automatically and re-logs in when needed.
- `MAX_CAV` is the API version string visible in browser DevTools (the `cav` request header). Update it if you get authentication errors after a MAX app update.
- Manual expenses live in a separate table and are never touched by sync.
