# Camp Link Discovery Engine

Discovers **summer camp primary-source URLs** for Middlesex County, MA (~53 towns): recreation departments, community education catalogs (e.g. [Lexington Lexplorations](https://lexingtoncommunityed.org/lexplorations/)), YMCA/JCC pages, and local parent blogs.

**Not** aggregators (ActivityHero, Macaroni Kid, Kidvoyage, Yelp) or after-school program guides.

## Setup

```bash
python3.11 -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
crawl4ai-setup || python -m playwright install chromium
```

If crawls fail with `Executable doesn't exist` under `~/Library/Caches/ms-playwright/`, install browsers into the default user cache (not a sandbox temp path):

```bash
env -u PLAYWRIGHT_BROWSERS_PATH python -m playwright install chromium
```

No API key required for the default free search providers (`local_google`, `duckduckgo`).

Optional: copy `.env.example` → `.env` only if using a paid provider like Serper.

### Ollama (agent mode)

```bash
brew install ollama          # macOS
ollama serve                 # in a separate terminal
ollama pull llama3.2         # agent mode
ollama pull llama3.2:1b      # fast camp-page filter (Phase B)
```

Configure model and URL in `config/settings.py` (`ollama_model`, `ollama_filter_model`, `ollama_base_url`).

Phase B harvest runs an optional **local LLM camp filter** (on by default): it reads page text and drops town-gov noise, adult programs, etc. Disable with `--no-llm-validate` if Ollama is not running.

## Search providers (cost)

Set `search_provider` in `config/settings.py`:

| Provider | Cost | API key | Notes |
|----------|------|---------|-------|
| `local_google` | **Free** | None | Google results via local `ddgs` library |
| `duckduckgo` | **Free** | None | DuckDuckGo via local `ddgs` library |
| `serper` | ~$0.001/query | `SERPER_API_KEY` | Fast, reliable paid Google API (2,500 free credits on signup) |
| `dataforseo` | ~$0.0006/query (standard) · ~$0.002 (live) | `DATAFORSEO_LOGIN` + `DATAFORSEO_PASSWORD` | Cheapest at scale; credits never expire. Default `dataforseo_mode="standard"` is queued/slower, set to `"live"` for instant results |
| `google_cse` | 100 free/day | CSE keys | Google Custom Search |
| `brave` | $5/1k (+$5 free/mo) | `BRAVE_API_KEY` | Not implemented yet |

**DataForSEO** (`dataforseo`): set credentials in `.env`:

```bash
DATAFORSEO_LOGIN=you@example.com
DATAFORSEO_PASSWORD=your_api_password
```

`"standard"` mode posts a queued task and polls for the result (~$0.60/1k, completes in seconds–minutes). `"live"` mode returns instantly (~$2/1k). Tune with `dataforseo_mode` and `dataforseo_poll_timeout_s` in `config/settings.py`.

Free providers run searches from your computer. They are slower and may rate-limit if you run thousands of queries back-to-back — use `delay_seconds` and `--limit` for testing.

## Usage

### Scripted pipeline (default)

```bash
# Plan only — no API calls, no cost (default)
python -m src.run --dry-run

# Live Phase A search (summer directory keywords)
python -m src.run --no-dry-run --phase A --limit 5

# Crawl validated directory candidates → camp_links.csv
python -m src.run --no-dry-run --phase B

# Full run (Phase C disabled — summer-only scope)
python -m src.run --no-dry-run --limit 50
```

### Agent mode (Ollama)

Autonomous loop: **observe → plan → act → reflect → remember**. Memory persists in `cache/agent_memory.json`.

```bash
python -m src.run --agent --dry-run
python -m src.run --agent --no-dry-run
python -m src.run --agent --no-dry-run --limit 30
```

The agent prefers crawling high-yield primary sources (communityed.org, myrec.com, .gov/recreation) before new searches, and learns from outcomes across runs.

## Output

| File | Purpose |
|------|---------|
| `data/candidates.csv` | Validated search result pages (directories) |
| `data/rejected_candidates.csv` | Blocked aggregators / after-school hits |
| `data/camp_links.csv` | Deduplicated camp/program URLs (handoff artifact) |
| `cache/seen_searches.json` | Avoids repeat searches |
| `cache/seen_urls.json` | Avoids duplicate URL storage |
| `cache/agent_memory.json` | Agent lessons and domain/query scores |
| `logs/run_YYYY-MM-DD.log` | Scripted run log |
| `logs/agent_YYYY-MM-DD.log` | Agent run log |

## Source targeting

### Want (primary sources)

| Type | Example |
|------|---------|
| Community education | `lexingtoncommunityed.org/lexplorations` |
| Municipal rec (myrec) | `actonma.myrec.com/info/activities` |
| Town .gov recreation | `acton-ma.gov/recreation` |
| YMCA / JCC | local branch summer camp pages |
| Local blogs | town-specific parent guides (not Macaroni Kid) |

### Blocked at ingest (`config/sources.py`)

ActivityHero, Macaroni Kid, Kidvoyage, Yelp, summercamps.com, and similar aggregators. Title patterns like "after school", "childcare", "daycare" are rejected unless overridden by summer-camp context.

## Configuration

Edit files under `config/` only:

| File | Purpose |
|------|---------|
| `config/settings.py` | Caps, provider, Ollama, `dry_run` |
| `config/towns.py` | Municipality list |
| `config/keywords.py` | Phase A summer directory keywords |
| `config/sources.py` | Aggregator denylist, preferred hosts |
| `config/prompts.py` | Ollama agent prompts |

### Annual keyword maintenance

Update year-specific terms in `config/keywords.py` each spring (e.g. `"2026 community education summer"` → `"2027 ..."`).

Phase C is **disabled** (`PHASE_C_KEYWORDS = []`) — this engine targets summer camp **directories**, not per-activity gap-fill.

## Pipeline

1. **Phase A** — summer directory searches with validation funnel
2. **Phase B** — crawl validated candidates (preferred sources first)
3. **Phase C** — disabled (summer-only scope)

## Resetting polluted test data

If an earlier run saved aggregator URLs, clear before re-running:

```bash
rm -f data/candidates.csv data/rejected_candidates.csv
rm -f cache/seen_searches.json   # optional — forces fresh searches
```

## Scheduling

Run weekly (or nightly) to gap-fill new camp listings. Examples assume project root and activated venv.

### macOS / Linux (cron)

```bash
crontab -e
```

Add (Sundays at 2 AM):

```
0 2 * * 0 cd "/Users/yashmathur/Desktop/firefly web scraper" && ./venv/bin/python -m src.run --no-dry-run >> logs/cron.log 2>&1
```

Agent mode cron example:

```
0 3 * * 0 cd "/Users/yashmathur/Desktop/firefly web scraper" && ./venv/bin/python -m src.run --agent --no-dry-run --limit 100 >> logs/cron.log 2>&1
```

### macOS (launchd)

Save as `~/Library/LaunchAgents/com.firefly.camp-link-engine.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.firefly.camp-link-engine</string>
  <key>ProgramArguments</key>
  <array>
    <string>/Users/yashmathur/Desktop/firefly web scraper/venv/bin/python</string>
    <string>-m</string><string>src.run</string>
    <string>--no-dry-run</string>
  </array>
  <key>WorkingDirectory</key>
  <string>/Users/yashmathur/Desktop/firefly web scraper</string>
  <key>StartCalendarInterval</key>
  <dict>
    <key>Weekday</key><integer>0</integer>
    <key>Hour</key><integer>2</integer>
    <key>Minute</key><integer>0</integer>
  </dict>
  <key>StandardOutPath</key>
  <string>/Users/yashmathur/Desktop/firefly web scraper/logs/launchd.log</string>
  <key>StandardErrorPath</key>
  <string>/Users/yashmathur/Desktop/firefly web scraper/logs/launchd.err</string>
</dict>
</plist>
```

Load: `launchctl load ~/Library/LaunchAgents/com.firefly.camp-link-engine.plist`

## Retargeting another region

1. Set `STATE` in `config/settings.py`
2. Replace `TOWNS` in `config/towns.py`
3. Adjust `PHASE_A_KEYWORDS` in `config/keywords.py`
4. Clear or archive `cache/` and `data/` to start fresh (optional)

No changes to `src/` are required.
