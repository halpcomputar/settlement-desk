# Settlement Desk

A local dashboard for reviewing U.S. class action settlements. Search listings, filter by deadline and proof requirements, save notes, and track claims.

Built with FastAPI, SQLite, and vanilla JavaScript. Listing data comes from ClassAction.org through Parse. Reviews and notes stay in the local database; API requests are manual.

## Installation

Requires Docker Engine 28+ with Compose, or Python 3.11–3.14 with [uv](https://docs.astral.sh/uv/getting-started/installation/).

```sh
git clone https://github.com/halpcomputar/settlement-desk.git
cd settlement-desk
cp .env.example .env
```

### Parse configuration

Live listings require a [Parse account](https://parse.bot), available credits, and access to the [ClassAction API](https://parse.bot/marketplace/624a46b3-8cdf-453d-bd77-b84610148502/classaction-org-api) (`classaction-org-api`).

Get an API key from [Parse Settings](https://parse.bot/settings). Open the API's **GET `list_settlements`** endpoint and copy the scraper UUID from its URL:

```text
https://api.parse.bot/scraper/{scraper_id}/list_settlements
```

Set both values in `.env`:

```dotenv
PARSE_API_KEY=your_api_key
PARSE_SCRAPER_ID=your_scraper_uuid
```

The scraper UUID is distinct from the marketplace listing ID. The application calls the REST endpoint directly; no Parse SDK is required. See the [Parse documentation](https://docs.parse.bot) for authentication and endpoint details.

Credentials are optional for previewing the interface. Set `SETTLEMENT_LOAD_SAMPLE=true` before creating a database to load three historical example listings.

### Docker

```sh
docker compose up --build -d --wait
```

Open [localhost:8765](http://127.0.0.1:8765).

The image supports AMD64 and ARM64. Compose binds to `127.0.0.1`, runs as a non-root user with a read-only filesystem, and persists the database in the `settlement-data` volume at `/app/data/settlements.sqlite3`.

To update:

```sh
git pull --ff-only
docker compose up --build -d --wait
```

### Python

```sh
uv sync --locked
uv run python launch.py
```

The launcher starts the server and opens the dashboard. To run without opening a browser:

```sh
uv run python server.py
```

## Configuration

| Variable | Default | Description |
| --- | --- | --- |
| `PARSE_API_KEY` | unset | Parse API key |
| `PARSE_SCRAPER_ID` | unset | Scraper UUID for `list_settlements` |
| `SETTLEMENT_PORT` | `8765` | Native server port or Compose host port |
| `SETTLEMENT_DB` | `data/settlements.sqlite3` | Native SQLite path, relative to the repository; Compose uses its volume |
| `SETTLEMENT_LOAD_SAMPLE` | `false` | Import example listings when initializing a database |

Process environment variables override `.env`. Restart the native server or recreate the Compose container after changing configuration.

## Usage

- **Refresh listings** fetches page 0, up to 50 records.
- **Find more settlements** fetches the next page and persists pagination progress across restarts. Empty or repeated pages stop discovery; refreshing resumes it.
- Search and filters operate on cached listings. Review statuses, notes, and CSV exports are stored or generated locally.
- **Night mode** follows the system theme until a preference is selected, then saves that preference in the browser.

Each fetch makes one request with no automatic retries. The confirmation dialog estimates one credit per request; Parse determines actual charges. Requests preserve existing reviews and deduplicate listings by ID. Search terms and review notes are not sent to Parse. Claims are submitted separately through the official settlement sites.

## Remote access

The application has no authentication and is intended for a single user. Keep the loopback binding and use an SSH tunnel for remote access:

```sh
ssh -N -L 8765:127.0.0.1:8765 user@server
```

Then open [localhost:8765](http://127.0.0.1:8765). Direct network exposure requires an authentication layer; the built-in host and CSRF checks do not provide access control.

## Backups

For Docker:

```sh
docker compose stop
docker compose cp app:/app/data/settlements.sqlite3 ./settlement-backup.sqlite3
docker compose start
```

To restore into an existing container, stop it and replace the database:

```sh
docker compose stop
docker compose cp ./settlement-backup.sqlite3 app:/app/data/settlements.sqlite3
docker compose run --rm --no-deps --user 0 --cap-add CHOWN app chown 10001:10001 /app/data/settlements.sqlite3
docker compose up -d --wait
```

For a new installation, run `docker compose up --build -d --wait` once before restoring. Restore replaces the destination database; back it up first. Removing the Compose volume with `docker compose down --volumes` deletes saved listings and reviews.

For native installations, stop the server before copying or replacing the file specified by `SETTLEMENT_DB`. The same SQLite file can be transferred between native and Docker installations. Databases, exports, and `.env` are excluded from Git.

## Limitations

- Coverage depends on the source API and pages fetched. Previously saved listings remain in the collection, including expired entries.
- Eligibility, deadlines, proof requirements, and payout terms are source summaries. Verify details against the official settlement notice.
- Categories are inferred from titles. State restrictions are not structured, so state filtering is not available.

## Development

```sh
uv sync --locked
uv run python -m unittest discover -s tests -v
```

Tests use temporary databases and mocked Parse responses. CI tests Python 3.11 and 3.14 on Linux, macOS, and Windows, plus Docker builds and database persistence on AMD64 and ARM64.

Application code is in `server.py`; the frontend is in `static/` and requires no build step.
