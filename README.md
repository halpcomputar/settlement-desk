# Settlement desk

A private dashboard for reviewing U.S. class action settlement listings. Search eligibility summaries, filter deadlines and proof requirements, keep a shortlist, save private notes, and track what you have claimed.

Runs on macOS, Linux, and Windows with Python 3.11–3.14. The browser interface has no build step, external fonts, analytics, or cloud AI dependency. SQLite stores the collection and your reviews on the machine running the server.

## Prerequisites for live listings

Previewing the dashboard needs no Parse account. Fetching live listings requires your own [Parse account](https://parse.bot), API key, access to the [ClassAction API in the Parse marketplace](https://parse.bot/marketplace/624a46b3-8cdf-453d-bd77-b84610148502/classaction-org-api) (`classaction-org-api`), and available Parse credits. This application is not affiliated with Parse or ClassAction.org.

1. Sign in to Parse and open the marketplace API linked above. Add it to your account if prompted, then open its **GET `list_settlements`** endpoint.
2. Create or retrieve your own API key in [Parse Settings → API Keys](https://parse.bot/settings).
3. Copy the scraper UUID from the endpoint URL shown in your account: `https://api.parse.bot/scraper/UUID/list_settlements`. Do not use the marketplace page's UUID or the API slug.
4. Copy `.env.example` to `.env` and fill in `PARSE_API_KEY` and `PARSE_SCRAPER_ID` before starting with Docker or Python below. Keep `.env` private; it is ignored by Git.

The app sends `X-API-Key` with `GET list_settlements`, using zero-based `page` and `limit=50`. No Parse SDK, generated client, bank connection, or email connection is needed. Setup and test calls in Parse may consume credits; consult your account for current pricing. The [canonical Parse documentation](https://docs.parse.bot) and your endpoint's current specification are the source of truth if setup or fields change.

## Docker (MacBook or home server)

Install Docker Desktop on your Mac, or Docker Engine with the Compose plugin on your server. Use Docker Engine 28 or newer for localhost port isolation. You do not need Python or uv on the host. Builds support both Apple Silicon/ARM64 and Intel/AMD64; CI builds and runs both architectures natively.

```sh
git clone https://github.com/halpcomputar/settlement-desk.git
cd settlement-desk
cp .env.example .env
# Edit .env with your Parse API key and scraper UUID.
docker compose up --build -d --wait
```

Open **http://127.0.0.1:8765**. To preview without credentials, set `SETTLEMENT_LOAD_SAMPLE=true` before the first start. The image is built locally from source; no registry login is needed. Credentials are supplied at runtime, never copied into the image.

The app runs as a non-root user. Compose publishes port 8765 only on `127.0.0.1`, uses a read-only container filesystem, and stores the SQLite database in the persistent `settlement-data` named volume. Reviews survive container restarts, recreation, and image rebuilds. This is separate from a native installation's `data/` folder. `SETTLEMENT_DB` in `.env` is for native use; Compose always stores the database in `/app/data/settlements.sqlite3`.

For a remote home server, run Compose there and use the SSH tunnel shown below. There is no built-in login, so keep the localhost port binding. If another app already uses port 8765, change `SETTLEMENT_PORT` in `.env`; the container still listens on 8765 internally.

Useful commands:

```sh
docker compose logs -f                 # inspect logs
docker compose stop                   # stop, retaining data
docker compose start                  # resume
git pull
docker compose up --build -d --wait    # rebuild/update, retaining data
docker compose down                   # remove containers, retaining data
```

Do **not** add `--volumes` / `-v` to `docker compose down` unless you intend to delete your saved collection and notes. The container restarts with Docker unless explicitly stopped. No automatic Parse refreshes run in the background.

### Docker backups and migrating an existing database

Stop the app before copying SQLite:

```sh
docker compose stop
docker compose cp app:/app/data/settlements.sqlite3 ./settlement-backup.sqlite3
docker compose start
```

For a new installation, create the container and volume first, then copy your existing database in and set its ownership (this replaces any database already at that destination):

```sh
docker compose create
docker compose cp ./settlement-backup.sqlite3 app:/app/data/settlements.sqlite3
docker compose run --rm --no-deps --user 0 --cap-add CHOWN app chown 10001:10001 /app/data/settlements.sqlite3
docker compose up -d --wait
```

These steps also work with a stopped native installation's `data/settlements.sqlite3` as the source. Restore only while the app is stopped, and back up existing data first. The one-off ownership command runs without starting the application; normal operation uses UID 10001.

## Quick start on a MacBook

Install [uv](https://docs.astral.sh/uv/getting-started/installation/) and Git, then:

```sh
git clone https://github.com/halpcomputar/settlement-desk.git
cd settlement-desk
cp .env.example .env
uv sync --locked
uv run python launch.py
```

The launcher opens http://127.0.0.1:8765. Leave the terminal running; Ctrl+C stops the server. If the repository is private, Git must be authenticated to an account with access.

You can run the dashboard without Parse credentials. It starts with an empty collection; set `SETTLEMENT_LOAD_SAMPLE=true` in `.env` **before the first launch** to seed three public example listings instead. Samples are historical snapshots, not verified current opportunities. That option only affects a new database.

### Connect Parse

Edit `.env` locally:

```dotenv
PARSE_API_KEY=your_key_here
PARSE_SCRAPER_ID=your_scraper_uuid_here
```

Follow [Prerequisites for live listings](#prerequisites-for-live-listings) to obtain both values from your own account. Restart the server after changing configuration. Existing process environment variables take precedence over `.env`.

Opening, searching, filtering, saving notes, and exporting use no API credits. **Refresh listings** requests only page 0, with a maximum of 50 records and no automatic retries. The dialog shows the expected cost of one credit; actual charging is controlled by Parse. It preserves all existing reviews and notes. It does not fetch the entire catalog or submit claims. **Find more settlements** checks one additional page per click (up to 50 listings, estimated one credit), remembers the next page across restarts, and reports new versus already-saved cases. Duplicate IDs are stored only once and reviews/notes are preserved. Empty or repeated pages stop further discovery requests; Refresh listings starts another search after that. Failed requests leave the search position unchanged and are not retried automatically. A page can return no new cases while still costing a credit. No personal profile, notes, or search terms are sent to Parse.

Account balances and accumulated credit usage are not displayed. Listing-response credit headers are not a reliable current account total; check your Parse account dashboard for your balance. The refresh dialog shows an estimated request cost, not an account balance. The public REST endpoint is used directly, so no generated SDK files or account credentials need to be checked in.

## Windows

```powershell
git clone https://github.com/halpcomputar/settlement-desk.git
cd settlement-desk
Copy-Item .env.example .env
uv sync --locked
uv run python launch.py
```

Put credentials in `.env`, or load an already-saved Windows user variable in the current terminal before launch:

```powershell
$env:PARSE_API_KEY = [Environment]::GetEnvironmentVariable('PARSE_API_KEY', 'User')
```

## Run on a home server

Clone and configure it on the server using the steps above, then run without opening a browser:

```sh
uv sync --locked
uv run python server.py
```

From your MacBook, create an SSH tunnel (replace `you@your-server` with your server login):

```sh
ssh -N -L 8765:127.0.0.1:8765 you@your-server
```

Open http://127.0.0.1:8765 on the MacBook. The application listens only on server loopback; SSH provides access to the remote machine. Keep both the server process and tunnel running. If port 8765 is already occupied on your MacBook, use `-L 8766:127.0.0.1:8765` and browse to port 8766.

This is a single-user app with no login system. Do not expose its port directly to the LAN or Internet. A public or multi-user deployment would need authentication and deployment-specific security work. The built-in CSRF token and host checks do not replace user authentication. Binding to loopback is intentional.

## Display preferences

Use **Night mode** in the top bar to switch themes. The dashboard follows your system theme until you choose a mode, then remembers that choice in the current browser.

## Configuration and backups

| Variable | Default | Purpose |
| --- | --- | --- |
| `PARSE_API_KEY` | unset | Authenticates public-data requests to Parse |
| `PARSE_SCRAPER_ID` | unset | ClassAction API UUID from your account |
| `SETTLEMENT_PORT` | `8765` | Loopback HTTP port |
| `SETTLEMENT_DB` | `data/settlements.sqlite3` | SQLite path; relative paths resolve from the repository |
| `SETTLEMENT_LOAD_SAMPLE` | `false` | Seed public sample listings when creating a new database |

Stop the app before copying `data/settlements.sqlite3` for a backup or transfer to another computer. Each installation has its own database; Git does not synchronize your notes. Prefer connecting to a single server if you want the same collection from multiple computers. Restart after restoring a backup.

`.env`, databases, notes, exports, caches, and virtual environments are ignored by Git. The repository includes source code, dependency metadata, tests, and a small public sample only.

## Current limits

- The saved collection is partial. Refresh checks the first page; Find more settlements checks additional pages on demand. Both keep older saved entries. Pagination cannot guarantee full coverage if the source reorders listings or limits access.
- Eligibility, proof requirements, deadlines, and payout wording come from the source; verify the official notice before claiming. An advertised maximum is not a predicted award.
- Categories are inferred from listing titles. State restrictions are not structured reliably, so there is no state filter yet.
- Expired records remain available for review. The sample file may contain expired listings.
- Reviews currently store a status and freeform notes; use notes for claim confirmation references.

## Development and checks

```sh
uv sync --locked
uv run python -m unittest discover -s tests -v
uv run python server.py
```

Tests use temporary databases and mocked Parse responses; they spend no credits. Application code is in `server.py`; the plain HTML/CSS/JavaScript interface is in `static/`. CI tests Python 3.11 and 3.14 on Linux, macOS, and Windows. `uv.lock` pins dependencies for reproducible installs.

The Docker workflow separately builds on AMD64 and ARM64, checks health and localhost publishing, saves a test review through HTTP, recreates the container, and verifies the review survives in the named volume. It uses disposable sample data and makes no Parse requests. The Dockerfile uses a separate dependency-build stage and an allowlisted build context (`.dockerignore`). See the official [Docker port-publishing documentation](https://docs.docker.com/engine/network/port-publishing/) and [uv Docker guide](https://docs.astral.sh/uv/guides/integration/docker/) for the underlying setup.

## Contributing without publishing personal information

Git records author and committer names and email addresses in every commit. Configure a suitable public identity in each clone before committing. For a generic project identity, run these commands inside this repository (they affect this clone only):

```sh
git config --local user.name "Settlement Desk contributors"
git config --local user.email "contributors@settlement-desk.invalid"
```

Your GitHub account and repository ownership remain visible if you publish the repository. Review patches, PR descriptions, screenshots, logs, and release assets for personal details before uploading. Never commit credentials, local databases, review notes, or exports. Keep local backup copies outside the repository. Do not merge an older private repository's history into this clean repository; transfer reviewed source changes only.
