# SubDubAnime Scraper & Catalog API

![Python Version](https://img.shields.io/badge/python-3.8+-blue.svg)
![License](https://img.shields.io/badge/license-MIT-green.svg)
![Platform](https://img.shields.io/badge/platform-cross--platform-lightgrey.svg)

A resilient, concurrent Python scraper, catalog API, and CLI client for SubDubAnime (`subdubanime.site`).
No authentication, registration, or headers needed to extract stream URLs. Automatically reconstructs direct, referer-free Rumble CDN links for movies, series, and dramas — featuring offline caching, resilient scraping with fallback backups, and an interactive streaming console.

```bash
python app.py home                              # Browse latest catalog (movies, series, dramas)
python app.py search "<query>"                  # Search locally cached titles and genres
python app.py episodes "<show_name_or_id>"      # List seasons and episode IDs for a show
python app.py detail <id>                       # Show metadata details (rating, release, synopsis)
python app.py stream <episode_id>               # Resolve direct Rumble CDN HLS/MP4 stream URLs
python app.py url "https://subdubanime.site/..." # Extract stream details from any page/embed URL
python app.py interactive                       # Full interactive console menu
```

## Table of Contents
* [Features](#features)
* [Installation](#installation)
* [Quick Start](#quick-start)
* [CLI Commands (App Client)](#cli-commands-app-client)
  * [home](#1-home--browse-latest-catalog)
  * [search](#2-search--search-local-catalog)
  * [episodes](#3-episodes--list-show-seasons-and-episodes)
  * [detail](#4-detail--get-show-details)
  * [stream](#5-stream--get-playable-stream-urls)
  * [url](#6-url--resolve-streams-from-page-urls)
  * [interactive](#7-interactive--interactive-menu-mode)
* [API & Scraper Interface](#api--scraper-interface)
  * [serve](#1-serve--fastapi-web-server)
  * [scrape](#2-scrape--resilient-concurrent-scraper)
  * [API Endpoints](#3-api-endpoints)
* [How It Works — Internals](#how-it-works--internals)
  * [Rumble CDN Stream Reconstruction](#1-rumble-cdn-stream-reconstruction)
  * [Resilient Scraper Architecture](#2-resilient-scraper-architecture)
  * [Offline Fallback & Cache Systems](#3-offline-fallback--cache-systems)
* [Troubleshooting](#troubleshooting)
* [Disclaimer](#disclaimer)
* [License](#license)

---

## Features
* **Zero Headers Required** — Extracted Rumble CDN video streams do not enforce referrer checks or TLS fingerprint checks. They play directly in browsers, VLC, or MPV.
* **Resilient Concurrency** — Multi-threaded scraper queries the backend API in concurrent chunks with built-in speed regulation.
* **Failure Fallback** — Scraper automatically falls back to the offline backup (`subdubanime_catalog_sample.json`) if the central catalog server is down.
* **State Resuming** — Incremental saving saves results to disk chunk-by-chunk. If the scraping task is aborted, it automatically skips already scraped items upon restarting.
* **Unified API** — FastAPI web backend exposes clean REST endpoints for frontend integrations, search, filtering, and recommendations.
* **Interactive CLI Menu** — Streamlined terminal experience lets you search shows, read summaries, list episodes, and obtain direct play links without opening a browser.

---

## Installation
```bash
git clone https://github.com/solo12345689/subdubanime.git
cd subdubanime

# Install requirements (only needed if running the API server/scraper)
pip install -r requirements.txt
```
* **Requirements:** Python 3.8+
* **Dependencies:** `fastapi`, `uvicorn`, `httpx`, `scrapling`, `beautifulsoup4` (Client script `app.py` has no external dependencies except standard libraries).

---

## Quick Start

### 1. Run the CLI Client (app.py)
```bash
# Browse highlights
python app.py home

# Search for a show
python app.py search "Ne Zha"

# Resolve streams for an episode ID
python app.py stream 228689-1-1

# Launch the interactive mode
python app.py interactive
```

### 2. Run the FastAPI Server & Scraper (api.py)
```bash
# Start the web API
python api.py serve --port 8000

# Run the background scraper
python api.py scrape
```

---

## CLI Commands (App Client)

### 1. home — Browse Latest Catalog
Displays the latest Movies, TV Series, and Live Action Dramas in the catalog.
```bash
python app.py home
```

### 2. search — Search Local Catalog
Performs a case-insensitive fuzzy match across titles and genres inside the local database.
```bash
python app.py search "sorcerer"
```

### 3. episodes — List Show Seasons and Episodes
Accepts a search query or exact TMDB ID to display all available seasons, episode numbers, and corresponding IDs.
```bash
python app.py episodes "Genie, Make a Wish"
```

### 4. detail — Get Show Details
Displays genres, synopsis, ratings, trailer links, and metadata for a specific ID.
```bash
python app.py detail "228689" tvshow
```

### 5. stream — Get Playable Stream URLs
Resolves direct Rumble CDN video stream URLs (M3U8 HLS or MP4) for a movie or TV episode ID (format: `TMDBID-SEASON-EPISODE`).
```bash
python app.py stream 228689-1-1
```
**Output:**
```text
Streaming links for 228689-1-1:
  [240p]: https://hugh.cdn.rumble.cloud/video/fww1/4b/s8/2/w/k/i/r/wkirz.oaa.tar?r_file=chunklist.m3u8&r_type=application%2Fvnd.apple.mpegurl&r_range=91039232-91071279
  [360p]: https://hugh.cdn.rumble.cloud/video/fww1/4b/s8/2/w/k/i/r/wkirz.baa.tar?r_file=chunklist.m3u8&r_type=application%2Fvnd.apple.mpegurl&r_range=275212288-275244801
  [480p]: https://hugh.cdn.rumble.cloud/video/fww1/4b/s8/2/w/k/i/r/wkirz.caa.tar?r_file=chunklist.m3u8&r_type=application%2Fvnd.apple.mpegurl&r_range=429128192-429160797
  [720p]: https://hugh.cdn.rumble.cloud/video/fww1/4b/s8/2/w/k/i/r/wkirz.gaa.tar?r_file=chunklist.m3u8&r_type=application%2Fvnd.apple.mpegurl&r_range=871629824-871662529
```

### 6. url — Resolve Streams from Page URLs
Takes a standard web page streaming URL or player embed URL, parses its routing parameters, and resolves the streams directly.
```bash
python app.py url "https://www.subdubanime.site/2026/07/streaming.html?type=Series&id=228689&s=1&ep=1"
```

### 7. interactive — Interactive Menu Mode
Launches a command-driven menu interface to search, browse, view show details, list episodes, and fetch streaming links inside a loop.
```bash
python app.py interactive
```

---

## API & Scraper Interface

### 1. serve — FastAPI Web Server
Starts the local API server using Uvicorn. The server runs by default on `127.0.0.1` and handles incoming requests for catalog details, searches, recommendations, and live stream resolutions.

**To start the server:**
```bash
python api.py serve --port 8000
```

**Features of the FastAPI web server:**
* **Auto-Port binding**: Change the port with the `--port` flag (e.g., `--port 8080`).
* **Interactive Swagger UI**: Once the server is running, navigate to [http://localhost:8000/docs](http://localhost:8000/docs) in your browser to view, test, and execute the API endpoints interactively.
* **Alternative Documentation**: View the ReDoc documentation style at [http://localhost:8000/redoc](http://localhost:8000/redoc).
* **Live Stream Resolution**: If an endpoint (like `/streams`) requests an episode that hasn't been scraped yet, the FastAPI server will query the remote backend, resolve the stream, cache the result to the local JSON file on the fly, and serve the links.

**Quick verification test (via `curl`):**
```bash
curl -X 'GET' 'http://localhost:8000/streams?tmdbId=228689&s=1&ep=1' -H 'accept: application/json'
```

### 2. scrape — Resilient Concurrent Scraper
Runs the scraper pipeline inside your terminal console:
```bash
python api.py scrape
```
* Bypasses network errors by falling back to `subdubanime_catalog_sample.json` if the central server is down.
* Checks already completed items in `subdubanime_full_results.json` to skip re-scraping them.
* Saves progress incrementally after every chunk to prevent data loss.

### 3. API Endpoints
The following endpoints are supported by the FastAPI server:

* **`GET /catalog`** — Fetch the entire scraped catalog database.
* **`GET /search?q={query}`** — Search catalog items matching a query string.
* **`GET /filter?letter={char}`** — A-Z filter bar logic (matching title starts, `#` matches numbers/symbols).
* **`GET /recommendations?tmdbId={id}&limit=8`** — Get client-side random recommendations, excluding the active item.
* **`GET /streams?tmdbId={id}&s={season}&ep={episode}`** — On-demand stream resolver. Checks cache, fetches live if missing, updates the database, and returns CDN streams.

---

## How It Works — Internals

### 1. Rumble CDN Stream Reconstruction
When query details are loaded, the script calls `test.blakiteapi.xyz/api/get.php?id={season}-{episode}&tmdbId={tmdbId}`. This API returns a code-key (`dataId`), format type, and byte ranges:
```json
{
  "format": "M3U8",
  "dataId": "fww1/4b/s8/2/w/k/i/r/wkirz",
  "ranges": "91039232-91071279 (240p)\n275212288-275244801 (360p)\n429128192-429160797 (480p)\n871629824-871662529 (720p)"
}
```
The stream links are assembled dynamically by mapping the quality configurations:
```python
stream_url = f"https://hugh.cdn.rumble.cloud/video/{dataId}.{code}.tar?r_file=chunklist.m3u8&r_type=application%2Fvnd.apple.mpegurl&r_range={range_val}"
```
Where code maps as `240p` -> `oaa`, `360p` -> `baa`, `480p` -> `caa`, `720p` -> `gaa`, `1080p` -> `haa`.

### 2. Resilient Scraper Architecture
The scraping loop manages requests concurrently by dividing them into chunks controlled by a semaphore. 
```python
# Run in regulated chunks to prevent connection pool drops
chunk_size = 15
for i in range(0, total_tasks, chunk_size):
    chunk_res = await asyncio.gather(*coroutines)
```
Each task evaluates individual connection errors. Failures trigger up to 3 retry attempts with exponential back-off delays.

### 3. Offline Fallback & Cache Systems
* **Fallback catalog:** If the live catalog request times out on connect, the app recovers using `subdubanime_catalog_sample.json`.
* **Incremental persistence:** Scraped catalog lists write back to disk immediately after each chunk gathers. If the process is aborted in the middle, `subdubanime_full_results.json` preserves everything collected.

---

## Troubleshooting

### Connection Timeouts (ConnectTimeout)
If you experience connection timeouts when fetching live streams:
1. **System-wide VPN**: The domain `test.blakiteapi.xyz` may be geo-blocked or blocked by your local ISP. Ensure you are using a system-wide VPN (like Cloudflare WARP) instead of a browser-only extension so that terminal traffic is also unblocked.
2. **Windows Defender Firewall**: Verify that `python.exe` or your terminal is not blocked from outbound connections by your firewall.

### 404: Streams could not be resolved
This occurs if the endpoint has no stream URL mapping configured on the backend server or if the remote server is down. Check the CLI output for individual request attempt logs.

---

## Disclaimer
This project is for educational and research purposes only. It interacts with public API interfaces used by the SubDubAnime front-end. We do not host, store, or redistribute any media files.

---

## License
MIT License. Created in 2026.
