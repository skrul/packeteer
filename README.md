# Packeteer

Tools for downloading jam session song charts and combining them into a single PDF packet.

## Prerequisites

- Python 3.8+
- [uv](https://docs.astral.sh/uv/) (Python package manager)
- [Docker](https://www.docker.com/products/docker-desktop/) (for converting .docx files to PDF)

## Setup

1. Install Python dependencies:

   ```bash
   uv sync
   ```

2. Make sure Docker is running:

   ```bash
   docker ps
   ```

## Creating a Packet

### Step 1: Download the charts

Run `jam_downloader.py` with the Google Docs URL for the jam session song list:

```bash
uv run jam_downloader.py "https://docs.google.com/document/d/YOUR_DOC_ID/edit"
```

This parses the document, finds all the song chart links, downloads them as PDFs, and saves them to the `charts/` directory.

Options:

- `-o <directory>` — Save charts to a different directory (default: `charts`)
- `-p <name>` — Only download charts for a specific person (case insensitive, partial match)

```bash
# Download only Gary's charts
uv run jam_downloader.py "https://docs.google.com/document/d/YOUR_DOC_ID/edit" -p Gary
```

### Step 2: Review the downloaded charts

Check the `charts/` directory and make sure everything looks right. Remove any bad downloads or add missing charts manually.

### Step 3: Combine into a packet

Run `packeteer.py` to merge all the charts into a single `output.pdf`:

```bash
uv run packeteer.py charts
```

This combines the PDFs in a interleaved order so that each person's songs are spread out across the packet, and adds a title header to each page.

Options:

- `-s <0-3>` — Song ordering strategy (default: 1)
  - `0` — Round-robin
  - `1` — Proportional distribution
  - `2` — Middle-weighted
  - `3` — Greedy spread (no back-to-back)
- `-v` — Show the song ordering and grade the spacing

```bash
# Use greedy spread and show the grade
uv run packeteer.py charts -s 3 -v
```

### Step 4: Print or share

The final packet is at `charts/output.pdf`.
