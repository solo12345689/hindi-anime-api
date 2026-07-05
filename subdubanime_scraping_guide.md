# 🌐 SubDubAnime Scraping Guide

This guide documents the layout, architecture, API configurations, and player extraction sequences for [SubDubAnime](https://www.subdubanime.site/).

---

## 📂 1. Homepage & Architecture

Unlike typical platforms that render catalogs in complex HTML structures, SubDubAnime acts as a lightweight frontend wrapper built on top of a centralized API catalog system:
* **Catalog API Endpoint:** `https://test.blakiteapi.xyz/api/getAllAnime.php`
* **JSON Cache Key:** `blakite_v7_categories` (Stored in browser `localStorage`).

The catalog contains three primary categories:
1. `movies`: Individual stand-alone films (Total: 47).
2. `series`: Multi-episode episodic anime series (Total: 223).
3. `dramas`: Live action dramas (Total: 2).

### Catalog JSON Item Structure Example (Series):

```json
{
  "tmdbId": "00249907",
  "originalTmdbId": "249907",
  "title": "Sentenced to Be a Hero (English Subbed)",
  "language": "English Subbed",
  "type": "Series",
  "status": "Ongoing",
  "TMDB_DATA": {
    "genres": ["Animation", "Action & Adventure", "Sci-Fi & Fantasy", "Comedy"],
    "synopsis": "In a world where heroism is a punishment...",
    "rating": "9.6",
    "releaseDate": "2026-01-03",
    "trailer": "https://www.youtube.com/embed/B5qZX2kh-7w"
  },
  "IMAGES": {
    "poster": "https://image.tmdb.org/t/p/w500/k8bh5mvHDx3czHSF56v9lRyulLC.jpg",
    "backdrop": "https://image.tmdb.org/t/p/w1280/6RriaOG7kanuHjs4unVnXyvFrMv.jpg"
  },
  "seasons": {
    "1": {
      "seasonNumber": 1,
      "status": "Ongoing",
      "totalEpisodes": 12
    }
  }
}
```

---

## ⚡ 2. Video Player Integration

When a user selects an episode, the platform redirects to the streaming route:
`https://www.subdubanime.site/2026/07/streaming.html?type=Series&id=TMDB_ID&s=SEASON_NUMBER&ep=EPISODE_NUMBER`

The details page loads an iframe pointing to the player host:
`https://test.blakiteapi.xyz/embed/{TMDB_ID}/{SEASON_NUMBER}-{EPISODE_NUMBER}`

---

## 🎬 3. Reconstructing Rumble CDN Stream Links

Inside the player frame, a call is made to get the stream metadata:
`https://test.blakiteapi.xyz/api/get.php?id={SEASON_NUMBER}-{EPISODE_NUMBER}&tmdbId={TMDB_ID}`

### API JSON Response:

```json
{
  "success": true,
  "data": {
    "animeTitle": "Scum of the Brave (Hindi Dubbed)",
    "dataId": "fwe2/b1/s8/2/-/s/a/D/-saDA",
    "qid": 5,
    "quality": "480p",
    "format": "M3U8",
    "ranges": "38188544-38201963 (240p)\n115173888-115187396 (360p)\n180003328-180016927 (480p)\n365520896-365534588 (720p)\n702574592-702588326 (1080p)"
  }
}
```

### URL Generation Logic

Stream links are served via **Rumble Cloud CDN**:
* **Base URL:** `https://hugh.cdn.rumble.cloud/video/`
* **Quality Configuration:**
  | Label | Code |
  |---|---|
  | `240p` | `oaa` |
  | `360p` | `baa` |
  | `480p` | `caa` |
  | `720p` | `gaa` |
  | `1080p`| `haa` |

For HLS M3U8 streaming formats, you must parse the byte-range from the `ranges` key and append it as `r_range` query parameter:

```python
# Construct 720p HLS stream link
# range_val = "365520896-365534588"
# code = "gaa"
# data_id = "fwe2/b1/s8/2/-/s/a/D/-saDA"
stream_url = f"https://hugh.cdn.rumble.cloud/video/{data_id}.{code}.tar?r_file=chunklist.m3u8&r_type=application%2Fvnd.apple.mpegurl&r_range={range_val}"
```

For direct downloads, the links point to:
`https://hugh.cdn.rumble.cloud/video/{data_id}.{code}.mp4`

---

## 📺 4. Play in MPV Player

Rumble CDN streams do not enforce Referrer checks or TLS fingerprint validation. They can be played instantly in `mpv` without headers:

```powershell
mpv "https://hugh.cdn.rumble.cloud/video/fwe2/b1/s8/2/-/s/a/D/-saDA.gaa.tar?r_file=chunklist.m3u8&r_type=application%2Fvnd.apple.mpegurl&r_range=365520896-365534588"
```

---

## 🛠️ 5. Build Guide: Recreating the Scraper

To write a scraper from scratch for SubDubAnime, follow this step-by-step workflow:

### Step 1: Download the Catalog Database
Make a standard GET request to `https://test.blakiteapi.xyz/api/getAllAnime.php` to fetch the entire site list. This contains details for all items: TMDB IDs, titles, ratings, synopsis, keywords, poster image links, and seasons.

### Step 2: Loop Categories and Episodes
Iterate through the catalog keys: `movies`, `series`, and `dramas`.
* For **movies**, target Season `1`, Episode `1`.
* For **series/dramas**, iterate through the `seasons` configuration dictionary to determine `seasonNumber` and `totalEpisodes`. Then loop through each episode (from `1` to `totalEpisodes`).

### Step 3: Fetch Video ID for Each Episode
For each episode, request its stream ID metadata from:
`https://test.blakiteapi.xyz/api/get.php?id={season}-{episode}&tmdbId={tmdbId}`
Extract the following variables:
* `dataId` (String path parameter)
* `qid` (Int quality index)
* `format` (Stream format e.g., `"M3U8"`)
* `ranges` (String block mapping resolutions to byte-ranges)

### Step 4: Reconstruct Rumble Cloud CDN Video Streams
* Parse the `ranges` string into a dictionary matching quality labels (e.g. `720p`, `1080p`) to their respective byte-ranges.
* Map the available quality levels using the `qid` limit index and quality codes list:
  `['oaa' (240p), 'baa' (360p), 'caa' (480p), 'gaa' (720p), 'haa' (1080p)]`
* Assemble the final CDN URLs:
  `https://hugh.cdn.rumble.cloud/video/{dataId}.{code}.tar?r_file=chunklist.m3u8&r_type=application%2Fvnd.apple.mpegurl&r_range={range_value}`

### Step 5: Save and Stream
* Save the combined metadata object dictionary to a JSON results file.
* Direct the resulting stream links to any standard video player (e.g., `mpv`). No special headers or cookies are required.

---

## 🔍 6. Search Functionality & Scraping

SubDubAnime implements search dynamically on the client side using the local JSON cache.

### How Search Works on the Website:
1. When the page loads, the frontend downloads the complete anime catalog from `getAllAnime.php`.
2. When the user types in the search input box (`input[name="q"]`), a JavaScript event listener triggers.
3. The script filters the cached items in memory by checking if the user query matches the `title` or `genres` parameters.
4. The matching items are displayed instantly in the dropdown search box.

### How to Scrape Search Results:
Because search is handled client-side using the central database, you don't need to make separate API requests for every search query. Instead, you can run search queries against your local scraped JSON database (`subdubanime_full_results.json`) using Python:

```python
import json

def search_anime(query, json_file="subdubanime_full_results.json"):
    with open(json_file, "r", encoding="utf-8") as f:
        catalog = json.load(f)
        
    query = query.lower()
    results = []
    
    # Search across all categories
    for category in ["movies", "series", "dramas"]:
        for item in catalog.get(category, []):
            title = item.get("title", "").lower()
            genres = [g.lower() for g in item.get("genres", [])]
            
            # Check title or genres match
            if query in title or any(query in genre for genre in genres):
                results.append(item)
                
    return results

# Example usage:
# print(search_anime("Sentenced to Be a Hero"))
```

---

## 🎲 7. Recommendation System

The recommendation section (titled "Recomendation" with a typo on the website) is generated **completely client-side using random selection**.

### How Recommendations Work:
1. The player page loads the complete cached catalog (`sourceList`).
2. It filters out the current anime ID so it does not recommend itself:
   ```javascript
   let filtered = sourceList.filter(item => item.id !== currentId);
   ```
3. It shuffles the list randomly in memory:
   ```javascript
   filtered.sort(() => Math.random() - 0.5);
   ```
4. It displays the first 8 or 16 items (`REL_LIMIT`) in the recommendation grid.

There is **no complex recommendation algorithm or server-side API query**. To mock recommendations in Python, you can simply load the local results JSON, filter out the target title, and use `random.sample` to return a list of recommendations:

```python
import json
import random

def get_recommendations(current_tmdb_id, limit=8, json_file="subdubanime_full_results.json"):
    with open(json_file, "r", encoding="utf-8") as f:
        catalog = json.load(f)
        
    all_items = catalog.get("movies", []) + catalog.get("series", []) + catalog.get("dramas", [])
    
    # Filter out current item
    filtered = [item for item in all_items if item.get("tmdbId") != current_tmdb_id]
    
    # Return random sample
    return random.sample(filtered, min(len(filtered), limit))
```

---

## 🔤 8. A-Z List / Alphabetical Filter

SubDubAnime implements the alphabetical filtering bar (A to Z and `#`) entirely on the client side using routing logic.

### How A-Z Alphabetical Filter Works on the Website:
1. When a user clicks a letter in the A-Z list header, the site redirects to the route: `/search/label/{LETTER}` (e.g. `/search/label/A`, `/search/label/B`, or `/search/label/%23` for `#`).
2. The router's label parsing logic intercepts the query and extracts the character.
3. If the extracted label has a length of 1 (`label.length === 1`), it filters the catalog items by matching the first character of their trimmed title:
   - **For `#`:** If the label is `#`, it matches titles that do **not** start with an alphabetic character `[A-Z]` (i.e., numbers or symbols):
     ```javascript
     if(label === '#') return !/[A-Z]/.test(firstChar);
     ```
   - **For Letters (A-Z):** It matches titles starting with that exact letter (case-insensitive):
     ```javascript
     return firstChar === label.toUpperCase();
     ```
4. The filtered items are then sorted by date/timestamp descending (`b.date - a.date`) and rendered into the grid.

### Python Emulator Code:
You can emulate this logic using the script below:

```python
import json
import re

def filter_by_letter(letter, json_file="subdubanime_full_results.json"):
    with open(json_file, "r", encoding="utf-8") as f:
        catalog = json.load(f)
        
    all_items = catalog.get("movies", []) + catalog.get("series", []) + catalog.get("dramas", [])
    filtered_items = []
    
    target_letter = letter.strip().upper()
    
    for item in all_items:
        title = item.get("title", "").strip()
        if not title:
            continue
            
        first_char = title[0].upper()
        
        if target_letter == "#":
            # Match any non-alphabetic character (numbers, symbols)
            if not re.match(r"[A-Z]", first_char):
                filtered_items.append(item)
        elif len(target_letter) == 1:
            if first_char == target_letter:
                filtered_items.append(item)
                
    # Sort by date/timestamp descending
    def get_sort_key(x):
        # Fallback to empty string if date is missing
        return x.get("TMDB_DATA", {}).get("releaseDate") or ""
        
    filtered_items.sort(key=get_sort_key, reverse=True)
    return filtered_items
```




