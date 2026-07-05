import sys
import os
import json
import re
import urllib.parse
import httpx

DATA_DIR = r"d:\Music\iTunes\Downloads\hindi anime"
CATALOG_FILE = os.path.join(DATA_DIR, "subdubanime_catalog_sample.json")
RESULTS_FILE = os.path.join(DATA_DIR, "subdubanime_full_results.json")

GET_EP_URL = "https://test.blakiteapi.xyz/api/get.php"
BASE_DURL = "https://hugh.cdn.rumble.cloud/video/"
QUALITY_LABELS = ['240p', '360p', '480p', '720p', '1080p']
QUALITY_CODES = ['oaa', 'baa', 'caa', 'gaa', 'haa']

def load_data():
    # Use full results first, fall back to catalog sample if needed
    if os.path.exists(RESULTS_FILE):
        try:
            with open(RESULTS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    if os.path.exists(CATALOG_FILE):
        try:
            with open(CATALOG_FILE, "r", encoding="utf-8") as f:
                catalog_payload = json.load(f)
                # Normalize raw catalog to match results format
                catalog = catalog_payload.get("data", {})
                normalized = {"movies": [], "series": [], "dramas": []}
                for cat in ["movies", "series", "dramas"]:
                    for k, v in catalog.get(cat, {}).items():
                        v["tmdbId"] = v.get("tmdbId") or k
                        normalized[cat].append(v)
                return normalized
        except Exception:
            pass
    return {"movies": [], "series": [], "dramas": []}

def find_show(query_or_id, data):
    # Try exact TMDB ID match first
    for cat in ["movies", "series", "dramas"]:
        for item in data.get(cat, []):
            if item.get("tmdbId") == query_or_id or item.get("originalTmdbId") == query_or_id:
                return item, cat

    # Try title match (case-insensitive fuzzy match)
    query_lower = query_or_id.lower()
    matches = []
    for cat in ["movies", "series", "dramas"]:
        for item in data.get(cat, []):
            if query_lower in item.get("title", "").lower():
                matches.append((item, cat))
    
    if len(matches) == 1:
        return matches[0]
    elif len(matches) > 1:
        print(f"\nMultiple matches found for '{query_or_id}':")
        for idx, (m, cat) in enumerate(matches):
            print(f" {idx + 1}. [{m.get('tmdbId')}] {m.get('title')} ({cat.capitalize()})")
        print("")
        try:
            sel = int(input("Select show number: ")) - 1
            if 0 <= sel < len(matches):
                return matches[sel]
        except Exception:
            pass
    return None, None

def fetch_live_stream(tmdb_id, season, episode):
    url = f"{GET_EP_URL}?id={season}-{episode}&tmdbId={tmdb_id}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://test.blakiteapi.xyz/"
    }
    try:
        # 5 second timeout to fail fast if API host is down
        with httpx.Client(headers=headers, timeout=5.0) as client:
            resp = client.get(url)
            if resp.status_code == 200:
                resp_json = resp.json()
                if resp_json.get("success") and "data" in resp_json:
                    data = resp_json["data"]
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
                    return streams
    except Exception:
        pass
    return None

def resolve_streams(tmdb_id, season, episode, data):
    # 1. Try to find in local results database
    for cat in ["movies", "series", "dramas"]:
        for item in data.get(cat, []):
            if item.get("tmdbId") == tmdb_id:
                if cat == "movies":
                    if item.get("video_stream"):
                        return item["video_stream"]
                else:
                    seasons = item.get("seasons", {})
                    # Seasons can be list or dict
                    if isinstance(seasons, dict):
                        eps = seasons.get(str(season), [])
                    else:
                        eps = []
                    for ep in eps:
                        if ep.get("episode") == int(episode) and ep.get("streams"):
                            return ep["streams"]

    # 2. Try live lookup
    print(f"Stream links not found locally. Attempting live lookup for TMDB ID {tmdb_id} (S{season}E{episode})...")
    live_streams = fetch_live_stream(tmdb_id, season, episode)
    if live_streams:
        return live_streams
    return None

def cmd_home():
    data = load_data()
    print("==================================================")
    print("                  SUBDUBANIME HOME                ")
    print("==================================================")
    
    for cat in ["movies", "series", "dramas"]:
        items = data.get(cat, [])[:5]
        print(f"\n--- Latest {cat.capitalize()} ({len(data.get(cat, []))} total) ---")
        for item in items:
            rating = item.get("rating") or item.get("TMDB_DATA", {}).get("rating") or "N/A"
            print(f" [{item.get('tmdbId')}] {item.get('title')} (Rating: {rating})")
    print("")

def cmd_search(query):
    data = load_data()
    query_lower = query.lower()
    results = []
    for cat in ["movies", "series", "dramas"]:
        for item in data.get(cat, []):
            title = item.get("title", "").lower()
            genres = [g.lower() for g in (item.get("genres") or item.get("TMDB_DATA", {}).get("genres", []))]
            if query_lower in title or any(query_lower in g for g in genres):
                results.append((item, cat))
                
    print(f"\nSearch results for '{query}':")
    if not results:
        print(" No results found.")
    else:
        for idx, (item, cat) in enumerate(results):
            rating = item.get("rating") or item.get("TMDB_DATA", {}).get("rating") or "N/A"
            print(f" {idx+1}. [{item.get('tmdbId')}] {item.get('title')} ({cat.capitalize()}) - Rating: {rating}")
    print("")

def cmd_episodes(show_query):
    data = load_data()
    item, cat = find_show(show_query, data)
    if not item:
        print(f"Show not found: {show_query}")
        return
        
    print(f"\n==================================================")
    print(f" {item.get('title')} ({cat.capitalize()})")
    print(f"==================================================")
    
    if cat == "movies":
        print(f" This is a Movie. Episode ID: {item.get('tmdbId')}-1-1")
    else:
        # Try local results format first
        seasons = item.get("seasons", {})
        if seasons:
            for s_num, eps in seasons.items():
                print(f"\n Season {s_num}:")
                for ep in eps:
                    print(f"  Episode {ep.get('episode')}: {ep.get('title')} (ID: {item.get('tmdbId')}-{s_num}-{ep.get('episode')})")
        else:
            # Fall back to raw catalog season schema
            raw_catalog = os.path.exists(CATALOG_FILE)
            if raw_catalog:
                with open(CATALOG_FILE, "r", encoding="utf-8") as f:
                    raw_data = json.load(f).get("data", {}).get(cat, {}).get(item.get("tmdbId"), {})
                    raw_seasons = raw_data.get("seasons", {})
                    for s_num, s_info in raw_seasons.items():
                        tot_eps = s_info.get("totalEpisodes", 1)
                        print(f"\n Season {s_num} ({tot_eps} episodes):")
                        for ep in range(1, tot_eps + 1):
                            print(f"  Episode {ep} (ID: {item.get('tmdbId')}-{s_num}-{ep})")
    print("")

def cmd_detail(show_id, show_type="tvshow"):
    data = load_data()
    item, cat = find_show(show_id, data)
    if not item:
        print(f"Show with ID {show_id} not found.")
        return
        
    tmdb_data = item.get("TMDB_DATA") or item
    print(f"\n==================================================")
    print(f" Title:       {item.get('title')}")
    print(f" Type:        {cat.capitalize()}")
    print(f" Rating:      {tmdb_data.get('rating', 'N/A')}/10")
    print(f" Release:     {tmdb_data.get('releaseDate', 'N/A')}")
    print(f" Genres:      {', '.join(tmdb_data.get('genres', []))}")
    print(f" Trailer:     {tmdb_data.get('trailer', 'N/A')}")
    print(f" Synopsis:    {tmdb_data.get('synopsis', 'No synopsis available.')}")
    print(f"==================================================")
    print("")

def cmd_stream(episode_id):
    data = load_data()
    parts = episode_id.split("-")
    if len(parts) == 1:
        # Movie
        tmdb_id, season, episode = parts[0], 1, 1
    elif len(parts) == 3:
        tmdb_id, season, episode = parts[0], parts[1], parts[2]
    else:
        print("Invalid episode_id format. Use TMDBID-SEASON-EPISODE or just TMDBID for movies.")
        return
        
    streams = resolve_streams(tmdb_id, season, episode, data)
    if not streams:
        print(f"Failed to resolve streaming links for {episode_id}.")
        return
        
    print(f"\nStreaming links for {episode_id}:")
    for q, url in streams.items():
        print(f"  [{q}]: {url}")
    print("")

def cmd_url(url_str):
    parsed = urllib.parse.urlparse(url_str)
    params = urllib.parse.parse_qs(parsed.query)
    
    # Parse query parameters from site route
    # e.g., ?type=Series&id=TMDB_ID&s=SEASON_NUMBER&ep=EPISODE_NUMBER
    # Or embed url: /embed/{TMDB_ID}/{SEASON_NUMBER}-{EPISODE_NUMBER}
    tmdb_id = params.get("id", [None])[0]
    season = params.get("s", ["1"])[0]
    episode = params.get("ep", [None])[0] or params.get("episode", ["1"])[0]
    
    if not tmdb_id:
        # Try parsing from embed path logic
        match = re.search(r'/embed/([^/]+)/(\d+)-(\d+)', url_str)
        if match:
            tmdb_id = match.group(1)
            season = match.group(2)
            episode = match.group(3)
            
    if not tmdb_id:
        print("Could not parse TMDB ID or episode info from the provided URL.")
        return
        
    print(f"Parsed URL: TMDB ID={tmdb_id}, Season={season}, Episode={episode}")
    cmd_stream(f"{tmdb_id}-{season}-{episode}")

def cmd_interactive():
    data = load_data()
    print("Welcome to SubDubAnime Interactive CLI Menu!")
    while True:
        print("\n--- Main Menu ---")
        print("1. Search Anime / Movies")
        print("2. Browse Home Catalog")
        print("3. Resolve direct URL")
        print("4. Exit")
        choice = input("Select an option (1-4): ").strip()
        
        if choice == "1":
            q = input("Enter search query: ").strip()
            if not q:
                continue
            # Search logic
            results = []
            for cat in ["movies", "series", "dramas"]:
                for item in data.get(cat, []):
                    title = item.get("title", "").lower()
                    genres = [g.lower() for g in (item.get("genres") or item.get("TMDB_DATA", {}).get("genres", []))]
                    if q.lower() in title or any(q.lower() in g for g in genres):
                        results.append((item, cat))
            if not results:
                print("No matches found.")
                continue
            print("\nMatches:")
            for idx, (m, cat) in enumerate(results):
                print(f" {idx + 1}. {m.get('title')} ({cat.capitalize()})")
            
            try:
                sel = int(input("\nSelect item number to view details: ")) - 1
                if 0 <= sel < len(results):
                    item, cat = results[sel]
                    # Show details
                    tmdb_data = item.get("TMDB_DATA") or item
                    print(f"\n--- {item.get('title')} ({cat.capitalize()}) ---")
                    print(f"Rating:   {tmdb_data.get('rating', 'N/A')}/10")
                    print(f"Genres:   {', '.join(tmdb_data.get('genres', []))}")
                    print(f"Synopsis: {tmdb_data.get('synopsis', 'No synopsis')}")
                    
                    if cat == "movies":
                        play = input("\nResolve streaming link? (y/n): ").strip().lower()
                        if play == 'y':
                            cmd_stream(item.get("tmdbId"))
                    else:
                        # TV Show / Drama seasons listing
                        cmd_episodes(item.get("tmdbId"))
                        ep_sel = input("\nEnter Episode ID to stream (e.g. TMDBID-S-EP): ").strip()
                        if ep_sel:
                            cmd_stream(ep_sel)
            except Exception as e:
                print(f"Error: {e}")
                
        elif choice == "2":
            cmd_home()
        elif choice == "3":
            url_val = input("Enter SubDubAnime URL: ").strip()
            if url_val:
                cmd_url(url_val)
        elif choice == "4":
            print("Goodbye!")
            break

def main():
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python app.py home")
        print("  python app.py search \"<query>\"")
        print("  python app.py episodes \"<show_name_or_id>\"")
        print("  python app.py detail <id> tvshow/movie")
        print("  python app.py stream <episode_id>")
        print("  python app.py url \"<url>\"")
        print("  python app.py interactive")
        sys.exit(1)
        
    action = sys.argv[1].lower()
    
    if action == "home":
        cmd_home()
    elif action == "search":
        if len(sys.argv) < 3:
            print("Error: query required. Usage: python app.py search \"<query>\"")
            sys.exit(1)
        cmd_search(sys.argv[2])
    elif action == "episodes":
        if len(sys.argv) < 3:
            print("Error: show name or ID required. Usage: python app.py episodes \"<show_name_or_id>\"")
            sys.exit(1)
        cmd_episodes(sys.argv[2])
    elif action == "detail":
        if len(sys.argv) < 3:
            print("Error: ID required. Usage: python app.py detail <id> [tvshow/movie]")
            sys.exit(1)
        show_type = sys.argv[3] if len(sys.argv) > 3 else "tvshow"
        cmd_detail(sys.argv[2], show_type)
    elif action == "stream":
        if len(sys.argv) < 3:
            print("Error: episode ID required. Usage: python app.py stream <episode_id>")
            sys.exit(1)
        cmd_stream(sys.argv[2])
    elif action == "url":
        if len(sys.argv) < 3:
            print("Error: URL required. Usage: python app.py url \"<url>\"")
            sys.exit(1)
        cmd_url(sys.argv[2])
    elif action == "interactive":
        cmd_interactive()
    else:
        print(f"Unknown action: {action}")
        sys.exit(1)

if __name__ == "__main__":
    main()
