import asyncio
import re
import json
import logging
import os
import httpx
from typing import Dict, Any, List, Optional
from fastapi import FastAPI, BackgroundTasks, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from scrapling import Fetcher

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("SubDubScraperAPI")

app = FastAPI(
    title="SubDubAnime Scraper & Catalog API",
    description="API to scrape, query, search, filter, and recommend anime entries.",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DATA_DIR = r"d:\Music\iTunes\Downloads\hindi anime"
CATALOG_FILE = os.path.join(DATA_DIR, "subdubanime_catalog_sample.json")
RESULTS_FILE = os.path.join(DATA_DIR, "subdubanime_full_results.json")

CATALOG_URL = "https://test.blakiteapi.xyz/api/getAllAnime.php"
GET_EP_URL = "https://test.blakiteapi.xyz/api/get.php"
BASE_DURL = "https://hugh.cdn.rumble.cloud/video/"

QUALITY_LABELS = ['240p', '360p', '480p', '720p', '1080p']
QUALITY_CODES = ['oaa', 'baa', 'caa', 'gaa', 'haa']

# Scraping concurrency control
sem = asyncio.Semaphore(15)

# Scraping status tracking
scraping_status = {
    "is_running": False,
    "processed_items": 0,
    "total_items": 0,
    "current_task": "",
    "errors": []
}

def load_local_results() -> Dict[str, Any]:
    if os.path.exists(RESULTS_FILE):
        try:
            with open(RESULTS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error reading results file: {e}")
    return {"movies": [], "series": [], "dramas": []}

def save_local_results(data: Dict[str, Any]):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(RESULTS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

async def fetch_episode_stream(client: httpx.AsyncClient, tmdb_id: str, season: Any, episode: Any) -> Optional[Dict[str, Any]]:
    url = f"{GET_EP_URL}?id={season}-{episode}&tmdbId={tmdb_id}"
    # Custom headers to avoid 415 error codes
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://test.blakiteapi.xyz/"
    }
    async with sem:
        for attempt in range(3):
            try:
                # Use a smaller timeout (8 seconds) to prevent hanging the scraper indefinitely
                response = await client.get(url, headers=headers, timeout=8.0)
                if response.status_code == 200:
                    resp = response.json()
                    if resp.get("success") and "data" in resp:
                        data = resp["data"]
                        data_id = data.get("dataId")
                        format_type = data.get("format", "M3U8")
                        ranges = data.get("ranges", "")
                        qid = data.get("qid", 5)
                        
                        if not data_id:
                            return None
                            
                        range_map = {}
                        if format_type == 'M3U8' and ranges:
                            lines = ranges.split('\n')
                            for line in lines:
                                match = re.match(r'^(\d+-\d+)\s*\(([^)]+)\)', line.strip())
                                if match:
                                    range_map[match.group(2)] = match.group(1)
                                    
                        max_idx = min(qid or 5, len(QUALITY_LABELS)) - 1
                        
                        streams = {}
                        for i in range(max_idx + 1):
                            label = QUALITY_LABELS[i]
                            code = QUALITY_CODES[i]
                            if format_type == 'M3U8':
                                r_range = range_map.get(label, '')
                                stream_url = f"{BASE_DURL}{data_id}.{code}.tar?r_file=chunklist.m3u8&r_type=application%2Fvnd.apple.mpegurl"
                                if r_range:
                                    stream_url += f"&r_range={r_range}"
                            else:
                                stream_url = f"{BASE_DURL}{data_id}.{code}.mp4"
                            streams[label] = stream_url
                            
                        return {
                            "season": int(season),
                            "episode": int(episode),
                            "title": data.get("title", f"Episode {episode}"),
                            "streams": streams
                        }
                    else:
                        # Success false might mean the episode doesn't have a stream URL mapping
                        return None
                elif response.status_code == 415:
                    # Let's retry after a short delay since it's sometimes rate-limit related or intermittent
                    await asyncio.sleep(2.0 * (attempt + 1))
                    continue
            except Exception as e:
                if attempt == 2:
                    logger.warning(f"Error fetching stream for tmdbId={tmdb_id} s={season} ep={episode} (Attempt {attempt+1}): {e}")
                await asyncio.sleep(1.5 * (attempt + 1))
    return None

async def run_scraper_task():
    global scraping_status
    scraping_status["is_running"] = True
    scraping_status["processed_items"] = 0
    scraping_status["errors"] = []
    scraping_status["current_task"] = "Fetching raw catalog database..."
    
    try:
        # Set standard website headers
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36", "Referer": "https://www.subdubanime.site/"}
        limits = httpx.Limits(max_keepalive_connections=5, max_connections=20)
        
        # Load existing results to support resuming and incremental updates
        existing_data = load_local_results()
        scraped_movies = {m["tmdbId"]: m for m in existing_data.get("movies", []) if m.get("video_stream")}
        
        scraped_series = {}
        for s in existing_data.get("series", []):
            tmdb_id = s.get("tmdbId")
            scraped_series[tmdb_id] = {}
            for s_num, eps in s.get("seasons", {}).items():
                scraped_series[tmdb_id][str(s_num)] = {ep["episode"]: ep for ep in eps if ep.get("streams")}

        scraped_dramas = {}
        for d in existing_data.get("dramas", []):
            tmdb_id = d.get("tmdbId")
            scraped_dramas[tmdb_id] = {}
            for s_num, eps in d.get("seasons", {}).items():
                scraped_dramas[tmdb_id][str(s_num)] = {ep["episode"]: ep for ep in eps if ep.get("streams")}

        movies_map = {}
        series_map = {}
        dramas_map = {}
        
        async with httpx.AsyncClient(headers=headers, limits=limits, timeout=10) as client:
            # 1. Fetch live catalog (with fallback to local copy)
            try:
                logger.info(f"Attempting to fetch live catalog from {CATALOG_URL}")
                response = await client.get(CATALOG_URL)
                if response.status_code != 200:
                    raise Exception(f"Failed to fetch catalog from API, status: {response.status_code}")
                catalog_payload = response.json()
                catalog = catalog_payload.get("data", {})
                
                # Save catalog sample locally as backup
                with open(CATALOG_FILE, "w", encoding="utf-8") as f:
                    json.dump(catalog_payload, f, indent=2, ensure_ascii=False)
            except Exception as e:
                logger.warning(f"Failed to fetch live catalog ({e}). Falling back to local catalog sample...")
                if os.path.exists(CATALOG_FILE):
                    with open(CATALOG_FILE, "r", encoding="utf-8") as f:
                        catalog_payload = json.load(f)
                        catalog = catalog_payload.get("data", {})
                else:
                    raise Exception(f"Catalog URL failed and local catalog sample ({CATALOG_FILE}) is missing.")
                
            tasks = []
            
            # Movies
            movies = catalog.get("movies", {})
            for k, v in movies.items():
                tmdb_id = v.get("tmdbId")
                if tmdb_id in scraped_movies:
                    movies_map[k] = scraped_movies[tmdb_id]
                else:
                    tasks.append(("movies", k, v, 1, 1, tmdb_id))
                
            # Series
            series = catalog.get("series", {})
            for k, v in series.items():
                tmdb_id = v.get("tmdbId")
                seasons = v.get("seasons", {})
                for s_num, s_info in seasons.items():
                    tot_episodes = s_info.get("totalEpisodes", 1)
                    for ep in range(1, tot_episodes + 1):
                        if tmdb_id in scraped_series and str(s_num) in scraped_series[tmdb_id] and ep in scraped_series[tmdb_id][str(s_num)]:
                            # Re-use already scraped episode streams
                            if k not in series_map:
                                tmdb_data = v.get("TMDB_DATA", {})
                                series_map[k] = {
                                    "title": v.get("title"),
                                    "tmdbId": v.get("tmdbId"),
                                    "originalTmdbId": v.get("originalTmdbId"),
                                    "language": v.get("language"),
                                    "genres": tmdb_data.get("genres", []),
                                    "rating": tmdb_data.get("rating"),
                                    "synopsis": tmdb_data.get("synopsis"),
                                    "releaseDate": tmdb_data.get("releaseDate"),
                                    "trailer": tmdb_data.get("trailer"),
                                    "poster": v.get("IMAGES", {}).get("poster"),
                                    "backdrop": v.get("IMAGES", {}).get("backdrop"),
                                    "seasons": {}
                                }
                            if str(s_num) not in series_map[k]["seasons"]:
                                series_map[k]["seasons"][str(s_num)] = []
                            series_map[k]["seasons"][str(s_num)].append(scraped_series[tmdb_id][str(s_num)][ep])
                        else:
                            tasks.append(("series", k, v, s_num, ep, tmdb_id))
                        
            # Dramas
            dramas = catalog.get("dramas", {})
            for k, v in dramas.items():
                tmdb_id = v.get("tmdbId")
                seasons = v.get("seasons", {})
                for s_num, s_info in seasons.items():
                    tot_episodes = s_info.get("totalEpisodes", 1)
                    for ep in range(1, tot_episodes + 1):
                        if tmdb_id in scraped_dramas and str(s_num) in scraped_dramas[tmdb_id] and ep in scraped_dramas[tmdb_id][str(s_num)]:
                            # Re-use already scraped drama streams
                            if k not in dramas_map:
                                tmdb_data = v.get("TMDB_DATA", {})
                                dramas_map[k] = {
                                    "title": v.get("title"),
                                    "tmdbId": v.get("tmdbId"),
                                    "originalTmdbId": v.get("originalTmdbId"),
                                    "language": v.get("language"),
                                    "genres": tmdb_data.get("genres", []),
                                    "rating": tmdb_data.get("rating"),
                                    "synopsis": tmdb_data.get("synopsis"),
                                    "releaseDate": tmdb_data.get("releaseDate"),
                                    "trailer": tmdb_data.get("trailer"),
                                    "poster": v.get("IMAGES", {}).get("poster"),
                                    "backdrop": v.get("IMAGES", {}).get("backdrop"),
                                    "seasons": {}
                                }
                            if str(s_num) not in dramas_map[k]["seasons"]:
                                dramas_map[k]["seasons"][str(s_num)] = []
                            dramas_map[k]["seasons"][str(s_num)].append(scraped_dramas[tmdb_id][str(s_num)][ep])
                        else:
                            tasks.append(("dramas", k, v, s_num, ep, tmdb_id))
                    
            total_tasks = len(tasks)
            scraping_status["total_items"] = total_tasks
            scraping_status["current_task"] = f"Scraping video streams concurrently..."
            
            # Run in chunks to prevent connection pool exhaustion, save incrementally
            chunk_size = 15  # Smaller chunk size to lower concurrent load
            for i in range(0, total_tasks, chunk_size):
                chunk = tasks[i:i+chunk_size]
                # Instantiate coroutines
                coros = [fetch_episode_stream(client, t[5], t[3], t[4]) for t in chunk]
                chunk_res = await asyncio.gather(*coros)
                
                for meta, res in zip(chunk, chunk_res):
                    category = meta[0]
                    item_key = meta[1]
                    raw_item = meta[2]
                    s_num = str(meta[3])
                    
                    if category == "movies":
                        if item_key not in movies_map:
                            tmdb_data = raw_item.get("TMDB_DATA", {})
                            movies_map[item_key] = {
                                "title": raw_item.get("title"),
                                "tmdbId": raw_item.get("tmdbId"),
                                "originalTmdbId": raw_item.get("originalTmdbId"),
                                "language": raw_item.get("language"),
                                "genres": tmdb_data.get("genres", []),
                                "rating": tmdb_data.get("rating"),
                                "synopsis": tmdb_data.get("synopsis"),
                                "releaseDate": tmdb_data.get("releaseDate"),
                                "trailer": tmdb_data.get("trailer"),
                                "poster": raw_item.get("IMAGES", {}).get("poster"),
                                "backdrop": raw_item.get("IMAGES", {}).get("backdrop"),
                                "video_stream": res.get("streams") if res else None
                            }
                        elif res:
                            movies_map[item_key]["video_stream"] = res.get("streams")
                            
                    elif category == "series":
                        if item_key not in series_map:
                            tmdb_data = raw_item.get("TMDB_DATA", {})
                            series_map[item_key] = {
                                "title": raw_item.get("title"),
                                "tmdbId": raw_item.get("tmdbId"),
                                "originalTmdbId": raw_item.get("originalTmdbId"),
                                "language": raw_item.get("language"),
                                "genres": tmdb_data.get("genres", []),
                                "rating": tmdb_data.get("rating"),
                                "synopsis": tmdb_data.get("synopsis"),
                                "releaseDate": tmdb_data.get("releaseDate"),
                                "trailer": tmdb_data.get("trailer"),
                                "poster": raw_item.get("IMAGES", {}).get("poster"),
                                "backdrop": raw_item.get("IMAGES", {}).get("backdrop"),
                                "seasons": {}
                            }
                        if res:
                            if s_num not in series_map[item_key]["seasons"]:
                                series_map[item_key]["seasons"][s_num] = []
                            # Avoid duplicates
                            series_map[item_key]["seasons"][s_num] = [ep for ep in series_map[item_key]["seasons"][s_num] if ep["episode"] != res["episode"]]
                            series_map[item_key]["seasons"][s_num].append({
                                "episode": res["episode"],
                                "title": res["title"],
                                "streams": res["streams"]
                            })
                            # Sort episodes
                            series_map[item_key]["seasons"][s_num].sort(key=lambda x: x["episode"])
                            
                    elif category == "dramas":
                        if item_key not in dramas_map:
                            tmdb_data = raw_item.get("TMDB_DATA", {})
                            dramas_map[item_key] = {
                                "title": raw_item.get("title"),
                                "tmdbId": raw_item.get("tmdbId"),
                                "originalTmdbId": raw_item.get("originalTmdbId"),
                                "language": raw_item.get("language"),
                                "genres": tmdb_data.get("genres", []),
                                "rating": tmdb_data.get("rating"),
                                "synopsis": tmdb_data.get("synopsis"),
                                "releaseDate": tmdb_data.get("releaseDate"),
                                "trailer": tmdb_data.get("trailer"),
                                "poster": raw_item.get("IMAGES", {}).get("poster"),
                                "backdrop": raw_item.get("IMAGES", {}).get("backdrop"),
                                "seasons": {}
                            }
                        if res:
                            if s_num not in dramas_map[item_key]["seasons"]:
                                dramas_map[item_key]["seasons"][s_num] = []
                            # Avoid duplicates
                            dramas_map[item_key]["seasons"][s_num] = [ep for ep in dramas_map[item_key]["seasons"][s_num] if ep["episode"] != res["episode"]]
                            dramas_map[item_key]["seasons"][s_num].append({
                                "episode": res["episode"],
                                "title": res["title"],
                                "streams": res["streams"]
                            })
                            # Sort episodes
                            dramas_map[item_key]["seasons"][s_num].sort(key=lambda x: x["episode"])
                
                scraping_status["processed_items"] += len(chunk)
                logger.info(f"Progress: {scraping_status['processed_items']}/{total_tasks}")
                
                # Save results incrementally
                temp_scraped_data = {
                    "movies": list(movies_map.values()),
                    "series": list(series_map.values()),
                    "dramas": list(dramas_map.values())
                }
                save_local_results(temp_scraped_data)
            
            scraping_status["current_task"] = "Idle (Completed Successfully)"
            logger.info("Scraping and results export completed successfully.")
        
    except Exception as e:
        logger.error(f"Scraper error: {e}")
        scraping_status["errors"].append(str(e))
        scraping_status["current_task"] = "Failed"
    finally:
        scraping_status["is_running"] = False

# API ENDPOINTS

@app.get("/")
def home():
    return {
        "message": "SubDubAnime Scraping & Catalog API Service running.",
        "endpoints": {
            "status": "/status (Get scraping status)",
            "scrape": "/scrape (Trigger complete scraper - background task)",
            "all": "/catalog (Get entire catalog)",
            "search": "/search?q={query}",
            "filter": "/filter?letter={A-Z|#}",
            "recommendations": "/recommendations?tmdbId={tmdbId}&limit=8"
        }
    }

@app.get("/status")
def get_status():
    return scraping_status

@app.post("/scrape")
def trigger_scrape(background_tasks: BackgroundTasks):
    if scraping_status["is_running"]:
        return {"status": "already running", "message": "Scraper is currently execution."}
    background_tasks.add_task(run_scraper_task)
    return {"status": "started", "message": "Scraping task initiated in background."}

@app.get("/catalog")
def get_catalog():
    return load_local_results()

@app.get("/search")
def search_catalog(q: str):
    if not q:
        raise HTTPException(status_code=400, detail="Query parameter 'q' is required.")
        
    catalog = load_local_results()
    query = q.lower()
    results = []
    
    for category in ["movies", "series", "dramas"]:
        for item in catalog.get(category, []):
            title = item.get("title", "").lower()
            genres = [g.lower() for g in item.get("genres", [])]
            if query in title or any(query in genre for genre in genres):
                results.append(item)
                
    return results

@app.get("/filter")
def filter_by_letter(letter: str):
    if not letter:
        raise HTTPException(status_code=400, detail="Filter parameter 'letter' is required.")
        
    letter_upper = letter.strip().upper()
    catalog = load_local_results()
    all_items = catalog.get("movies", []) + catalog.get("series", []) + catalog.get("dramas", [])
    filtered_items = []
    
    for item in all_items:
        title = item.get("title", "").strip()
        if not title:
            continue
            
        first_char = title[0].upper()
        if letter_upper == "#":
            if not re.match(r"[A-Z]", first_char):
                filtered_items.append(item)
        elif len(letter_upper) == 1:
            if first_char == letter_upper:
                filtered_items.append(item)
                
    filtered_items.sort(key=lambda x: x.get("releaseDate") or "", reverse=True)
    return filtered_items

@app.get("/recommendations")
def get_recommendations(tmdbId: str, limit: int = 8):
    if not tmdbId:
        raise HTTPException(status_code=400, detail="tmdbId is required.")
        
    catalog = load_local_results()
    all_items = catalog.get("movies", []) + catalog.get("series", []) + catalog.get("dramas", [])
    
    # Filter out current item
    filtered = [item for item in all_items if item.get("tmdbId") != tmdbId]
    
    import random
    random.shuffle(filtered)
    return filtered[:min(len(filtered), limit)]

@app.get("/streams")
async def get_episode_streams(tmdbId: str, s: int = 1, ep: int = 1):
    if not tmdbId:
        raise HTTPException(status_code=400, detail="tmdbId is required.")
        
    # Check if we have it locally first
    catalog = load_local_results()
    
    # 1. Search movies
    for item in catalog.get("movies", []):
        if item.get("tmdbId") == tmdbId:
            if item.get("video_stream"):
                return {"tmdbId": tmdbId, "season": 1, "episode": 1, "streams": item["video_stream"]}
                
    # 2. Search series
    for item in catalog.get("series", []):
        if item.get("tmdbId") == tmdbId:
            seasons = item.get("seasons", {})
            eps = seasons.get(str(s), [])
            for episode_item in eps:
                if episode_item.get("episode") == ep and episode_item.get("streams"):
                    return {"tmdbId": tmdbId, "season": s, "episode": ep, "streams": episode_item["streams"]}
                    
    # 3. Search dramas
    for item in catalog.get("dramas", []):
        if item.get("tmdbId") == tmdbId:
            seasons = item.get("seasons", {})
            eps = seasons.get(str(s), [])
            for episode_item in eps:
                if episode_item.get("episode") == ep and episode_item.get("streams"):
                    return {"tmdbId": tmdbId, "season": s, "episode": ep, "streams": episode_item["streams"]}

    # If not found locally, attempt to fetch it live
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://www.subdubanime.site/"
    }
    async with httpx.AsyncClient(headers=headers, timeout=10) as client:
        res = await fetch_episode_stream(client, tmdbId, s, ep)
        if res and res.get("streams"):
            try:
                # Find category and item to update cache
                with open(CATALOG_FILE, "r", encoding="utf-8") as f:
                    raw_cat = json.load(f).get("data", {})
                
                cat_name = None
                raw_item = None
                for cat in ["movies", "series", "dramas"]:
                    for k, v in raw_cat.get(cat, {}).items():
                        if v.get("tmdbId") == tmdbId:
                            cat_name = cat
                            raw_item = v
                            break
                    if cat_name:
                        break
                
                if cat_name and raw_item:
                    # Update local catalog results structure
                    movies_map = {m["tmdbId"]: m for m in catalog.get("movies", [])}
                    series_map = {s["tmdbId"]: s for s in catalog.get("series", [])}
                    dramas_map = {d["tmdbId"]: d for d in catalog.get("dramas", [])}
                    
                    if cat_name == "movies":
                        if tmdbId not in movies_map:
                            tmdb_data = raw_item.get("TMDB_DATA", {})
                            movies_map[tmdbId] = {
                                "title": raw_item.get("title"), "tmdbId": tmdbId, "originalTmdbId": raw_item.get("originalTmdbId"),
                                "language": raw_item.get("language"), "genres": tmdb_data.get("genres", []),
                                "rating": tmdb_data.get("rating"), "synopsis": tmdb_data.get("synopsis"),
                                "releaseDate": tmdb_data.get("releaseDate"), "trailer": tmdb_data.get("trailer"),
                                "poster": raw_item.get("IMAGES", {}).get("poster"), "backdrop": raw_item.get("IMAGES", {}).get("backdrop"),
                                "video_stream": res["streams"]
                            }
                        else:
                            movies_map[tmdbId]["video_stream"] = res["streams"]
                    elif cat_name == "series":
                        if tmdbId not in series_map:
                            tmdb_data = raw_item.get("TMDB_DATA", {})
                            series_map[tmdbId] = {
                                "title": raw_item.get("title"), "tmdbId": tmdbId, "originalTmdbId": raw_item.get("originalTmdbId"),
                                "language": raw_item.get("language"), "genres": tmdb_data.get("genres", []),
                                "rating": tmdb_data.get("rating"), "synopsis": tmdb_data.get("synopsis"),
                                "releaseDate": tmdb_data.get("releaseDate"), "trailer": tmdb_data.get("trailer"),
                                "poster": raw_item.get("IMAGES", {}).get("poster"), "backdrop": raw_item.get("IMAGES", {}).get("backdrop"),
                                "seasons": {}
                            }
                        s_str = str(s)
                        if s_str not in series_map[tmdbId]["seasons"]:
                            series_map[tmdbId]["seasons"][s_str] = []
                        series_map[tmdbId]["seasons"][s_str] = [x for x in series_map[tmdbId]["seasons"][s_str] if x["episode"] != ep]
                        series_map[tmdbId]["seasons"][s_str].append({"episode": ep, "title": res.get("title", f"Episode {ep}"), "streams": res["streams"]})
                        series_map[tmdbId]["seasons"][s_str].sort(key=lambda x: x["episode"])
                    elif cat_name == "dramas":
                        if tmdbId not in dramas_map:
                            tmdb_data = raw_item.get("TMDB_DATA", {})
                            dramas_map[tmdbId] = {
                                "title": raw_item.get("title"), "tmdbId": tmdbId, "originalTmdbId": raw_item.get("originalTmdbId"),
                                "language": raw_item.get("language"), "genres": tmdb_data.get("genres", []),
                                "rating": tmdb_data.get("rating"), "synopsis": tmdb_data.get("synopsis"),
                                "releaseDate": tmdb_data.get("releaseDate"), "trailer": tmdb_data.get("trailer"),
                                "poster": raw_item.get("IMAGES", {}).get("poster"), "backdrop": raw_item.get("IMAGES", {}).get("backdrop"),
                                "seasons": {}
                            }
                        s_str = str(s)
                        if s_str not in dramas_map[tmdbId]["seasons"]:
                            dramas_map[tmdbId]["seasons"][s_str] = []
                        dramas_map[tmdbId]["seasons"][s_str] = [x for x in dramas_map[tmdbId]["seasons"][s_str] if x["episode"] != ep]
                        dramas_map[tmdbId]["seasons"][s_str].append({"episode": ep, "title": res.get("title", f"Episode {ep}"), "streams": res["streams"]})
                        dramas_map[tmdbId]["seasons"][s_str].sort(key=lambda x: x["episode"])
                        
                    save_local_results({
                        "movies": list(movies_map.values()),
                        "series": list(series_map.values()),
                        "dramas": list(dramas_map.values())
                    })
            except Exception as e:
                logger.error(f"Error caching single episode stream: {e}")
                
            return {"tmdbId": tmdbId, "season": s, "episode": ep, "streams": res["streams"]}
            
    raise HTTPException(status_code=404, detail="Streams could not be resolved.")

if __name__ == "__main__":
    import argparse
    import uvicorn
    
    parser = argparse.ArgumentParser(description="SubDubAnime Scraper & Catalog CLI / API")
    parser.add_argument("action", nargs="?", default="serve", choices=["serve", "scrape", "search", "filter", "recommend", "streams"],
                        help="Action to perform: serve (run FastAPI server), scrape (run scraper directly), search, filter, recommend, streams")
    parser.add_argument("-q", "--query", help="Query string for search")
    parser.add_argument("-l", "--letter", help="Letter/character for filtering (#, A-Z)")
    parser.add_argument("-i", "--tmdbId", help="TMDB ID for recommendations or streams")
    parser.add_argument("-s", "--season", type=int, default=1, help="Season number for streams")
    parser.add_argument("-e", "--episode", type=int, default=1, help="Episode number for streams")
    parser.add_argument("-p", "--port", type=int, default=8000, help="Port to run the FastAPI server on")
    
    args = parser.parse_args()
    
    if args.action == "serve":
        print(f"Starting FastAPI server on http://127.0.0.1:{args.port}...")
        uvicorn.run(app, host="127.0.0.1", port=args.port)
        
    elif args.action == "scrape":
        print("Starting scraper task...")
        asyncio.run(run_scraper_task())
        print(f"Scraper finished. Results saved/updated in {RESULTS_FILE}")
        
    elif args.action == "search":
        if not args.query:
            print("Error: Please provide search query using -q/--query")
            exit(1)
        results = search_catalog(args.query)
        print(json.dumps(results, indent=2, ensure_ascii=False))
        
    elif args.action == "filter":
        if not args.letter:
            print("Error: Please provide letter for filter using -l/--letter")
            exit(1)
        results = filter_by_letter(args.letter)
        print(json.dumps(results, indent=2, ensure_ascii=False))
        
    elif args.action == "recommend":
        if not args.tmdbId:
            print("Error: Please provide tmdbId for recommendation using -i/--tmdbId")
            exit(1)
        results = get_recommendations(args.tmdbId)
        print(json.dumps(results, indent=2, ensure_ascii=False))
        
    elif args.action == "streams":
        if not args.tmdbId:
            print("Error: Please provide tmdbId using -i/--tmdbId")
            exit(1)
        from fastapi import HTTPException
        try:
            results = asyncio.run(get_episode_streams(args.tmdbId, args.season, args.episode))
            print(json.dumps(results, indent=2, ensure_ascii=False))
        except HTTPException as e:
            print(f"Error: {e.detail}")
            exit(1)


