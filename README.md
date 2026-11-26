# NewsLens

Search recent news, select an article to get an AI-generated summary and
sentiment, and revisit everything that's ever been analysed via History.
See `newslens-feature-spec.md` for the full product/API specification this
was built against.

## Quick start (local)

```bash
cp .env.example .env
# then edit .env: supply real GNEWS_API_KEY and OPENAI_API_KEY

docker compose up --build -d
docker compose ps
docker compose logs -f app
```

Open **http://localhost:8000/**. Interactive API docs (Swagger UI) are at
**http://localhost:8000/docs**.

```bash
docker compose down      # stops the stack, keeps saved data
docker compose down -v   # destructive: also deletes the database volume
```

## Environment variables

All of these are **required** — there are no in-code defaults. `.env.example`
documents a working value for each; `app/config.py` fails fast with a clear
error at startup if any is missing.

| Variable | Purpose |
| --- | --- |
| `NEWS_PROVIDER` | Selects the implementation in `app/services/news/` (currently `gnews`) |
| `GNEWS_API_KEY` | Your GNews API key |
| `GNEWS_BASE_URL` | GNews search endpoint (operational config, not a code constant) |
| `AI_PROVIDER` | Selects the implementation in `app/services/analysis/` (currently `openai`) |
| `OPENAI_API_KEY` | Your OpenAI API key |
| `OPENAI_MODEL` | Model identifier your key's project actually has access to (verify with `client.models.list()` — see Known limitations) |
| `DATABASE_URL` | SQLAlchemy connection string; `db` is the Compose service hostname |

## Database

One table, `article_analyses` (see `app/models.py` / spec §7). Schema is
created automatically on startup via SQLAlchemy's `create_all()` — there is
no migration framework for this single-table schema. Data lives in the
named Docker volume `aries_db_data` and survives `docker compose down`
(without `-v`) and container rebuilds.

## Running tests

```bash
docker compose run --rm app pytest -q
```

GNews and OpenAI are always mocked — no test run ever consumes real API
credits. Tests target an isolated `newslens_test` database, created
automatically; they never touch the database your `.env` points the app
itself at.

- `tests/integration/` — real Postgres, mocked providers. Exercises our own
  persistence and constraint/race-handling logic (the unique-URL dedup
  recovery in particular), which is exactly the kind of thing that
  shouldn't be mocked away.
- `tests/unit/` — no database, no network at all. Pure logic: OpenAI
  response parsing, output validation, and SDK-exception-to-HTTP-error
  mapping.

## API

Base path `/api`, JSON throughout, UTC timestamps with a literal `Z` suffix.

| Method & path | Purpose |
| --- | --- |
| `GET /api/articles?query=...` | Search recent news (1–200 char query); normalised results include an `analysis_id` hint for already-saved articles. Never calls the AI provider. |
| `POST /api/analyses` | Submit an article snapshot; returns the saved analysis (`201` if newly generated, `200` if it already existed — same resource shape either way). |
| `GET /api/analyses` | History: all saved analyses, newest first, capped at 100 rows. Never calls GNews or OpenAI. |
| `GET /api/analyses/{id}` | Fetch one saved analysis by id, or `404`. |

```bash
curl "http://localhost:8000/api/articles?query=artificial+intelligence"
```

## Architecture

- **Layered monolith**: FastAPI serves both the JSON API and the static UI
  (`app/static/`) from one origin — no separate frontend build or server.
- **Provider seam**: `app/services/news/` and `app/services/analysis/` each
  dispatch to a provider module selected at runtime by `NEWS_PROVIDER` /
  `AI_PROVIDER`. Adding a provider is one new module implementing the same
  function signature, plus one dict entry — no interfaces, no DI container.
- **Dedup and race handling** (`app/services/analysis/store.py`): a POST
  checks the database first; if nothing exists, the read transaction is
  released *before* the OpenAI call (never holding a DB connection open
  across an external request); the new row is then inserted in a short
  write transaction. If a concurrent request already won the race, the
  resulting unique-constraint violation on `article_url` is caught
  specifically (by constraint name) and recovered into the winning row,
  rather than surfacing as an error.
- **Client state** (`app/static/app.js`): one status map per view, keyed by
  URL/id (`pending` / `ready` / `error`), not three separate maps. An
  in-flight request is never aborted just because the user selected
  something else — it's left to finish and update the cache/badge, but a
  late response only repaints the detail panel if it's still the active
  selection.

## Known limitations

- **No authentication.** The hosted demo is intentionally public — a
  deliberate product decision, not an oversight. Anyone with the URL can
  trigger billable GNews/OpenAI requests; mitigate with provider-side
  spend/quota controls (an OpenAI budget cap in particular) rather than a
  login.
- **GNews free-tier behaviour**, observed directly while building this:
  article `content` is truncated (hence `content_scope: "excerpt"` on
  every saved analysis today); the same story is sometimes returned
  multiple times under different syndicated URLs, since de-duplication is
  URL-based only, not content-based; and the daily request quota is shared
  across everyone using this demo.
- **Article identity is the provider URL, used verbatim** — no
  canonicalisation. A re-syndicated copy of a story at a different URL is,
  by design, a different article.
- **Client-supplied snapshot provenance.** `POST /api/analyses` trusts the
  snapshot the client submits rather than independently re-fetching the
  article server-side; a client could in principle submit a modified
  snapshot. Accepted for this restricted demo.
- **Possible concurrent duplicate inference.** Two simultaneous first-time
  requests for the same brand-new URL can each trigger a real OpenAI call;
  only one result is ever persisted (the unique constraint on
  `article_url` guarantees that), but both calls still happen. No
  distributed locking — not justified at this scale.
- **History has a quiet 100-row cap**, not pagination. It bounds an
  otherwise-ever-growing, shared, never-deleted table without adding any
  pagination UI or API surface.

## Deployment

Hosted on [Render](https://render.com), via the `render.yaml` Blueprint in
this repo — a web service (built from the same `Dockerfile` used locally)
plus a free-tier managed Postgres database.

**Hosted URL:** _pending first deploy — added here once live._

To deploy this yourself from a fork:

1. Push to your own GitHub repo (already done here).
2. On Render: **New → Blueprint**, connect the repo. Render reads
   `render.yaml` automatically and proposes the web service + database.
3. When prompted, supply your own `GNEWS_API_KEY` and `OPENAI_API_KEY` —
   these are intentionally left out of `render.yaml` (`sync: false`) so
   they're never committed to the repo.
4. Apply. `DATABASE_URL` is wired automatically from the database Render
   creates (see `app/config.py`'s connection-string normalisation — a
   managed provider's plain `postgres://`/`postgresql://` string is
   rewritten to the `postgresql+psycopg://` form SQLAlchemy needs, with no
   manual edits required).

**Known hosting-specific behaviour, verified against Render's docs before
deploying, not assumed:**
- The free web service spins down after 15 minutes idle and takes about a
  minute to cold-start back up on the next request (Render shows its own
  loading page meanwhile) — the first hit after idle time will be slow.
- The free Postgres plan **expires 30 days after creation**, with a
  14-day grace period before Render deletes it (data included) if not
  upgraded to a paid plan by then. Accepted for this demo; upgrading to
  the $6/month tier at any point before expiry removes this limit
  entirely with no other changes needed.

## AI assistance disclosure

This project — specification review, implementation, tests, and this
README — was built collaboratively with Claude (Anthropic) under direct
human review throughout. The git history reflects the actual incremental,
reviewed build process: see commit messages for what was verified at each
step and why specific design decisions were made.
