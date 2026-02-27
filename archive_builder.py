#!/usr/bin/env python3
"""
Archive Builder - Download and organize all PHA jam session charts into a flat archive.

Usage:
    python archive_builder.py scan --url "https://docs.google.com/document/d/.../edit"
    python archive_builder.py scan --urls urls.txt
    python archive_builder.py scan --discover
    python archive_builder.py download
    python archive_builder.py download --dry-run
    python archive_builder.py status
"""

import argparse
import csv
import os
import re
import sys
from pathlib import Path
from typing import List, Dict, Optional, Tuple

from jam_downloader import JamSessionDownloader
from musicbrainz_lookup import MusicBrainzLookup


MANIFEST_FIELDS = [
    "month", "person", "title", "artist", "year", "year_source",
    "capo", "source_url", "status",
]

INT_TO_ROMAN = {
    1: "I", 2: "II", 3: "III", 4: "IV", 5: "V",
    6: "VI", 7: "VII", 8: "VIII", 9: "IX", 10: "X",
    11: "XI", 12: "XII",
}


def int_to_roman(n: int) -> str:
    return INT_TO_ROMAN.get(n, str(n))


def parse_capo(link_text: str) -> Optional[str]:
    """Extract capo info from link text, return roman numeral string or None."""
    m = re.search(r'\bcapo\s+(\d+)\b', link_text, re.IGNORECASE)
    if m:
        return int_to_roman(int(m.group(1)))
    # Also check for roman numerals already in text
    m = re.search(r'\bcapo\s+(I{1,3}|IV|V|VI{0,3}|IX|X|XI{0,3})\b', link_text, re.IGNORECASE)
    if m:
        return m.group(1).upper()
    return None


def parse_song_text(text: str) -> Tuple[str, str]:
    """Split 'Song Title - Artist' into (title, artist) using last ' - '."""
    if ' - ' in text:
        parts = text.rsplit(' - ', 1)
        return parts[0].strip(), parts[1].strip()
    return text.strip(), ""


def clean_archive_filename(title: str, artist: str, year: str, capo: str = "") -> str:
    """Build archive filename: Title - Artist (Year).pdf or Title - Artist (Year) (Capo VII).pdf"""
    def sanitize(s):
        s = re.sub(r'[^\w\s\'-]', '', s)
        s = re.sub(r'\s+', ' ', s).strip()
        return s

    clean_title = sanitize(title)
    clean_artist = sanitize(artist)
    year_str = year if year else "unknown"

    if clean_artist:
        name = f"{clean_title} - {clean_artist} ({year_str})"
    else:
        name = f"{clean_title} ({year_str})"

    if capo:
        name += f" (Capo {capo})"

    return name + ".pdf"


def extract_month_from_html_title(html_content: str) -> str:
    """Extract month/year from the HTML <title> tag (document title)."""
    if not html_content:
        return "unknown"
    m = re.search(r'<title[^>]*>(.*?)</title>', html_content, re.IGNORECASE | re.DOTALL)
    if m:
        title = m.group(1).strip()
        pm = re.search(r'PHA\s+(\w+\s+\d{4})', title)
        if pm:
            return pm.group(1).strip()
    return "unknown"


class ArchiveBuilder:
    def __init__(self, archive_dir: str = "archive"):
        self.archive_dir = Path(archive_dir)
        self.archive_dir.mkdir(parents=True, exist_ok=True)
        self.manifest_path = self.archive_dir / "manifest.csv"
        self.mb = MusicBrainzLookup(str(self.archive_dir / "musicbrainz_cache.json"))

    def _read_manifest(self) -> List[Dict]:
        """Read manifest CSV into list of dicts."""
        if not self.manifest_path.exists():
            return []
        rows = []
        with open(self.manifest_path, newline='', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                rows.append(row)
        return rows

    def _write_manifest(self, rows: List[Dict]):
        """Write manifest CSV from list of dicts."""
        with open(self.manifest_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=MANIFEST_FIELDS, extrasaction='ignore')
            writer.writeheader()
            writer.writerows(rows)

    def _existing_keys(self, rows: List[Dict]) -> set:
        """Return set of (title, artist, capo, source_url) for deduplication."""
        keys = set()
        for row in rows:
            key = (
                row.get("title", "").lower(),
                row.get("artist", "").lower(),
                row.get("capo", ""),
                row.get("source_url", ""),
            )
            keys.add(key)
        return keys

    def scan_url(self, doc_url: str, existing_rows: List[Dict], doc_title: str = "") -> List[Dict]:
        """Parse a single Google Doc and return new manifest rows."""
        downloader = JamSessionDownloader(str(self.archive_dir))
        doc_id = downloader.extract_doc_id(doc_url)
        if not doc_id:
            print(f"  Could not extract doc ID from: {doc_url}")
            return []

        html_content = downloader.fetch_doc_html(doc_id)
        if not html_content:
            print(f"  Could not fetch document: {doc_url}")
            return []

        # Use provided doc title (from Drive API), fall back to HTML title, then text export
        month = "unknown"
        if doc_title:
            m = re.search(r'PHA\s+(\w+\s+\d{4})', doc_title)
            if m:
                month = m.group(1).strip()
        if month == "unknown":
            month = extract_month_from_html_title(html_content)
        if month == "unknown":
            import requests as _requests
            try:
                text_resp = _requests.get(
                    f"https://docs.google.com/document/d/{doc_id}/export?format=txt"
                )
                if text_resp.ok:
                    m = re.search(r'(?:\ufeff)?PHA\s+(\w+\s+\d{4})', text_resp.text)
                    if m:
                        month = m.group(1).strip()
            except Exception:
                pass
        print(f"  Document: PHA {month}")

        attendees = downloader.parse_jam_session(html_content, doc_id)
        existing_keys = self._existing_keys(existing_rows)
        new_rows = []

        for attendee in attendees:
            if not attendee['songs']:
                continue
            person = attendee['name']
            for song in attendee['songs']:
                raw_title = song['title']
                title, artist = parse_song_text(raw_title)
                links = song['links']  # list of (url, link_text) tuples

                if not links:
                    # Still add to manifest with empty source_url so user can fill in
                    key = (title.lower(), artist.lower(), "", "")
                    if key not in existing_keys:
                        year = self.mb.get_year(title, artist) if artist else None
                        row = {
                            "month": month,
                            "person": person,
                            "title": title,
                            "artist": artist,
                            "year": year or "",
                            "year_source": "musicbrainz" if year else "",
                            "capo": "",
                            "source_url": "",
                            "status": "no_link",
                        }
                        new_rows.append(row)
                        existing_keys.add(key)
                    continue

                for link_url, link_text in links:
                    capo = parse_capo(link_text)
                    capo_str = capo if capo else ""
                    key = (title.lower(), artist.lower(), capo_str, link_url)
                    if key in existing_keys:
                        continue

                    year = self.mb.get_year(title, artist) if artist else None

                    row = {
                        "month": month,
                        "person": person,
                        "title": title,
                        "artist": artist,
                        "year": year or "",
                        "year_source": "musicbrainz" if year else "",
                        "capo": capo_str,
                        "source_url": link_url,
                        "status": "pending",
                    }
                    new_rows.append(row)
                    existing_keys.add(key)

        return new_rows

    @staticmethod
    def _needs_attention(row: Dict) -> bool:
        """Return True if a row has issues that need manual review."""
        return (not row.get("year")
                or not row.get("artist")
                or not row.get("source_url")
                or row.get("month") == "unknown")

    def cmd_scan(self, urls: List, titles: List[str] = None, split: bool = False):
        """Scan one or more Google Docs and append new songs to manifest.

        urls: list of URL strings
        titles: optional parallel list of document titles (from Drive API)
        split: if True, write two manifests (ready + needs_attention)
        """
        existing_rows = self._read_manifest()
        all_new = []

        for i, url in enumerate(urls):
            title = titles[i] if titles and i < len(titles) else ""
            print(f"\nScanning: {title or url}")
            new_rows = self.scan_url(url, existing_rows + all_new, doc_title=title)
            all_new.extend(new_rows)
            print(f"  Found {len(new_rows)} new song entries")

        combined = existing_rows + all_new

        if split:
            ready = [r for r in combined if not self._needs_attention(r)]
            attention = [r for r in combined if self._needs_attention(r)]
            self._write_manifest(ready)
            attention_path = self.archive_dir / "needs_attention.csv"
            with open(attention_path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=MANIFEST_FIELDS, extrasaction='ignore')
                writer.writeheader()
                writer.writerows(attention)
            print(f"\nSplit manifests:")
            print(f"  Ready ({len(ready)}): {self.manifest_path}")
            print(f"  Needs attention ({len(attention)}): {attention_path}")
        elif all_new:
            self._write_manifest(combined)

        # Summary
        years_found = sum(1 for r in all_new if r.get("year"))
        years_missing = sum(1 for r in all_new if not r.get("year"))
        no_link = sum(1 for r in all_new if r.get("status") == "no_link")
        print(f"\nScan complete:")
        print(f"  New entries added: {len(all_new)}")
        print(f"  Years found: {years_found}")
        print(f"  Years missing: {years_missing}")
        print(f"  Songs without links: {no_link}")
        if not split:
            print(f"  Manifest: {self.manifest_path}")

    def cmd_download(self, dry_run: bool = False):
        """Download pending songs from manifest."""
        rows = self._read_manifest()
        if not rows:
            print("No manifest found. Run 'scan' first.")
            return

        pending = [r for r in rows if r.get("status") == "pending"]
        print(f"Found {len(pending)} pending downloads out of {len(rows)} total entries")

        if not pending:
            print("Nothing to download.")
            return

        if dry_run:
            print("\nDry run - would download:")
            for r in pending:
                fn = clean_archive_filename(
                    r["title"], r["artist"],
                    r.get("year", ""), r.get("capo", "")
                )
                print(f"  {fn}")
                print(f"    from: {r['source_url']}")
            return

        downloader = JamSessionDownloader(str(self.archive_dir))
        downloaded = 0
        errors = 0

        try:
            for i, row in enumerate(rows):
                if row.get("status") != "pending":
                    continue

                filename = clean_archive_filename(
                    row["title"], row["artist"],
                    row.get("year", ""), row.get("capo", "")
                )
                filepath = self.archive_dir / filename

                print(f"\n[{downloaded + errors + 1}/{len(pending)}] {filename}")

                if filepath.exists():
                    print(f"  Already exists, marking downloaded")
                    row["status"] = "downloaded"
                    downloaded += 1
                    continue

                if downloader.download_file(row["source_url"], filepath):
                    row["status"] = "downloaded"
                    downloaded += 1
                    print(f"  ✓ Downloaded")
                else:
                    row["status"] = "error"
                    errors += 1
                    print(f"  ✗ Failed")

                # Save progress after each download
                self._write_manifest(rows)
        finally:
            downloader.stop_gotenberg()

        self._write_manifest(rows)
        print(f"\nDownload complete: {downloaded} succeeded, {errors} failed")

    def cmd_status(self):
        """Print summary of manifest status."""
        rows = self._read_manifest()
        if not rows:
            print("No manifest found. Run 'scan' first.")
            return

        status_counts = {}
        for r in rows:
            s = r.get("status", "unknown")
            status_counts[s] = status_counts.get(s, 0) + 1

        months = sorted(set(r.get("month", "unknown") for r in rows))
        year_filled = sum(1 for r in rows if r.get("year"))

        print(f"Archive manifest: {self.manifest_path}")
        print(f"Total entries: {len(rows)}")
        print(f"Months: {len(months)} ({', '.join(months)})")
        print(f"Years filled: {year_filled}/{len(rows)}")
        print(f"\nStatus breakdown:")
        for status, count in sorted(status_counts.items()):
            print(f"  {status}: {count}")

    def cmd_merge(self):
        """Merge fixed rows from needs_attention.csv into manifest.csv."""
        attention_path = self.archive_dir / "needs_attention.csv"
        if not attention_path.exists():
            print(f"No {attention_path} found. Nothing to merge.")
            return

        with open(attention_path, newline='', encoding='utf-8') as f:
            attention_rows = list(csv.DictReader(f))

        manifest_rows = self._read_manifest()
        existing_keys = self._existing_keys(manifest_rows)

        merged = 0
        skipped = 0
        still_needs_attention = []

        for row in attention_rows:
            if row.get("status") == "skip":
                skipped += 1
                continue

            if row.get("source_url"):
                if row.get("status") not in ("pending", "downloaded", "error"):
                    row["status"] = "pending"

                key = (
                    row.get("title", "").lower(),
                    row.get("artist", "").lower(),
                    row.get("capo", ""),
                    row.get("source_url", ""),
                )
                if key not in existing_keys:
                    manifest_rows.append(row)
                    existing_keys.add(key)
                    merged += 1
                else:
                    skipped += 1
            elif self._needs_attention(row):
                still_needs_attention.append(row)
            else:
                manifest_rows.append(row)
                merged += 1

        self._write_manifest(manifest_rows)

        if still_needs_attention:
            with open(attention_path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=MANIFEST_FIELDS, extrasaction='ignore')
                writer.writeheader()
                writer.writerows(still_needs_attention)
        else:
            attention_path.unlink()

        print(f"Merged: {merged} rows into manifest.csv")
        print(f"Skipped: {skipped} rows")
        if still_needs_attention:
            print(f"Still needs attention: {len(still_needs_attention)} rows")
        else:
            print(f"needs_attention.csv cleared - all rows processed")

    def cmd_discover(self, credentials_path: str = "credentials.json"):
        """Use Google Drive API to find all PHA docs."""
        try:
            from google.oauth2.credentials import Credentials
            from google_auth_oauthlib.flow import InstalledAppFlow
            from google.auth.transport.requests import Request
            from googleapiclient.discovery import build
        except ImportError:
            print("Google API libraries not installed. Run:")
            print("  pip install google-api-python-client google-auth-oauthlib")
            return []

        SCOPES = ["https://www.googleapis.com/auth/drive.metadata.readonly"]
        token_path = "token.json"
        creds = None

        if os.path.exists(token_path):
            creds = Credentials.from_authorized_user_file(token_path, SCOPES)

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                if not os.path.exists(credentials_path):
                    print(f"Missing {credentials_path}. Download from Google Cloud Console.")
                    return []
                flow = InstalledAppFlow.from_client_secrets_file(credentials_path, SCOPES)
                creds = flow.run_local_server(port=0)
            with open(token_path, 'w') as f:
                f.write(creds.to_json())

        service = build("drive", "v3", credentials=creds)
        query = "name contains 'PHA' and mimeType = 'application/vnd.google-apps.document'"
        results = service.files().list(
            q=query, fields="files(id, name, createdTime)",
            orderBy="createdTime", pageSize=100,
        ).execute()

        all_files = results.get("files", [])
        # Filter to docs whose name starts with "PHA " (e.g. "PHA December 2020")
        files = [f for f in all_files if f["name"].startswith("PHA ")]
        urls = []
        titles = []
        print(f"Found {len(files)} PHA documents (filtered from {len(all_files)} candidates):")
        for f in files:
            url = f"https://docs.google.com/document/d/{f['id']}/edit"
            print(f"  {f['name']} - {url}")
            urls.append(url)
            titles.append(f["name"])

        return urls, titles


def main():
    parser = argparse.ArgumentParser(
        description="Archive builder for PHA jam session charts"
    )
    parser.add_argument(
        "-d", "--dir", default="archive",
        help="Archive directory (default: archive)"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # scan
    scan_parser = subparsers.add_parser("scan", help="Scan Google Docs and build manifest")
    scan_group = scan_parser.add_mutually_exclusive_group(required=True)
    scan_group.add_argument("--url", help="Single Google Doc URL to scan")
    scan_group.add_argument("--urls", help="Text file with one Google Doc URL per line")
    scan_group.add_argument("--discover", action="store_true",
                           help="Use Google Drive API to find all PHA docs")
    scan_parser.add_argument("--split", action="store_true",
                            help="Split into manifest.csv (ready) and needs_attention.csv")

    # download
    dl_parser = subparsers.add_parser("download", help="Download pending songs from manifest")
    dl_parser.add_argument("--dry-run", action="store_true",
                          help="Preview downloads without fetching")

    # merge
    subparsers.add_parser("merge", help="Merge fixed rows from needs_attention.csv into manifest")

    # status
    subparsers.add_parser("status", help="Show manifest summary")

    args = parser.parse_args()
    builder = ArchiveBuilder(args.dir)

    if args.command == "scan":
        split = args.split
        if args.discover:
            urls, titles = builder.cmd_discover()
            if urls:
                builder.cmd_scan(urls, titles=titles, split=split)
        elif args.url:
            builder.cmd_scan([args.url], split=split)
        elif args.urls:
            with open(args.urls) as f:
                urls = [line.strip() for line in f if line.strip()]
            builder.cmd_scan(urls, split=split)

    elif args.command == "merge":
        builder.cmd_merge()

    elif args.command == "download":
        builder.cmd_download(dry_run=args.dry_run)

    elif args.command == "status":
        builder.cmd_status()


if __name__ == "__main__":
    main()
