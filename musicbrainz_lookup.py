#!/usr/bin/env python3
"""
MusicBrainz release year lookup with local JSON cache and rate limiting.
"""

import json
import os
import re
import time
from pathlib import Path
from typing import Optional

import requests


class MusicBrainzLookup:
    API_URL = "https://musicbrainz.org/ws/2/recording"
    USER_AGENT = "PHA-ArchiveBuilder/1.0 (jam session chart archiver)"
    MIN_REQUEST_INTERVAL = 1.1  # seconds between requests per API policy

    def __init__(self, cache_path: str = "archive/musicbrainz_cache.json"):
        self.cache_path = Path(cache_path)
        self.cache = self._load_cache()
        self._last_request_time = 0.0

    def _load_cache(self) -> dict:
        if self.cache_path.exists():
            with open(self.cache_path) as f:
                return json.load(f)
        return {}

    def _save_cache(self):
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.cache_path, 'w') as f:
            json.dump(self.cache, f, indent=2, sort_keys=True)

    def _cache_key(self, title: str, artist: str) -> str:
        return f"{title.lower().strip()}|{artist.lower().strip()}"

    def _rate_limit(self):
        elapsed = time.time() - self._last_request_time
        if elapsed < self.MIN_REQUEST_INTERVAL:
            time.sleep(self.MIN_REQUEST_INTERVAL - elapsed)
        self._last_request_time = time.time()

    def _search(self, query: str) -> Optional[str]:
        """Execute a MusicBrainz search query, return earliest release year or None."""
        self._rate_limit()
        try:
            response = requests.get(
                self.API_URL,
                params={"query": query, "fmt": "json", "limit": 5},
                headers={"User-Agent": self.USER_AGENT},
                timeout=10,
            )
            response.raise_for_status()
            data = response.json()
        except (requests.RequestException, ValueError):
            return None

        recordings = data.get("recordings", [])
        earliest_year = None
        for rec in recordings:
            for release in rec.get("releases", []):
                date = release.get("date", "")
                if date and len(date) >= 4:
                    year = date[:4]
                    if year.isdigit():
                        if earliest_year is None or year < earliest_year:
                            earliest_year = year
        return earliest_year

    def _simplify(self, text: str) -> str:
        """Strip parentheticals, capo references, and extra whitespace."""
        text = re.sub(r'\(.*?\)', '', text)
        text = re.sub(r'\bcapo\s+\w+\b', '', text, flags=re.IGNORECASE)
        text = re.sub(r'\s+', ' ', text).strip()
        return text

    def get_year(self, title: str, artist: str) -> Optional[str]:
        """Look up earliest release year for a song. Returns cached result if available."""
        key = self._cache_key(title, artist)
        if key in self.cache:
            return self.cache[key] if self.cache[key] else None

        # Progressive search: exact, title-only, simplified
        queries = [
            f'recording:"{title}" AND artist:"{artist}"',
            f'recording:"{title}"',
        ]
        simplified = self._simplify(title)
        if simplified.lower() != title.lower():
            queries.append(f'recording:"{simplified}" AND artist:"{artist}"')

        year = None
        for query in queries:
            year = self._search(query)
            if year:
                break

        self.cache[key] = year
        self._save_cache()
        return year
