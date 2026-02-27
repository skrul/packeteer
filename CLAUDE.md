# Jam Session Chart Downloader

## Overview

`jam_downloader.py` is an automated tool that downloads song charts from Google Docs jam session lists and organizes them for combining with `packeteer.py`.

## Requirements

### System Dependencies

- **Python 3.8+**
- **Docker** (Docker Desktop for Mac/Windows)
- **Gotenberg container** for document conversion

### Python Dependencies

Install with:
```bash
uv sync
```

### Docker Setup

The tool automatically manages a Gotenberg container for .docx to PDF conversion. Ensure Docker is running:

```bash
# Start Docker Desktop (Mac/Windows)
open -a Docker  # macOS
# or start Docker Desktop from Applications

# Verify Docker is running
docker ps
```

## Input Format

The tool expects a Google Docs URL containing a jam session song list with the following structure:

```
PHA [Month] [Year]
Spotify Playlist
PACKET
________________

[Person Name 1]
* [Song Title 1] - [Artist]
* [Song Title 2] - [Artist]

[Person Name 2]
* [Song Title 1] - [Artist]
* [Song Title 2] - [Artist]
```

### Supported Link Sources

- **Dropbox .docx files**: Converted to PDF using Gotenberg (LibreOffice-based conversion)
- **Dropbox .pdf files**: Direct download  
- **Google Docs documents**: Converted to PDF using Gotenberg (exports as .docx then converts)
- **Google Drive files**: Direct download using file ID extraction
- **Direct PDF URLs**: Simple HTTP download

## Usage

```bash
uv run jam_downloader.py <google_doc_url> [--output <directory>] [--person <name>]
```

### Parameters

- `doc_url`: Google Docs URL (required)
- `-o, --output`: Output directory (default: `charts`)  
- `-p, --person`: Filter by person name (case insensitive, partial match supported)

### Examples

```bash
# Download all songs
uv run jam_downloader.py "https://docs.google.com/document/d/YOUR_DOC_ID/edit?usp=sharing"

# Download to specific directory
uv run jam_downloader.py "https://docs.google.com/document/d/YOUR_DOC_ID/edit" -o monthly_charts

# Download only Gary's songs (preserves his original order number)
uv run jam_downloader.py "https://docs.google.com/document/d/YOUR_DOC_ID/edit" -p Gary

# Case insensitive and partial matching work
uv run jam_downloader.py "https://docs.google.com/document/d/YOUR_DOC_ID/edit" -p dave  # matches "Dave"
uv run jam_downloader.py "https://docs.google.com/document/d/YOUR_DOC_ID/edit" -p car   # matches "Carolyn"
```

## Output

Creates properly named PDF files in the specified directory (default: `charts/`):

```
01 - Gary - 01 - Mrs Robinson.pdf
01 - Gary - 02 - After the Gold Rush.pdf  
02 - Rob - 01 - Always on my mind.pdf
06 - Noah - 01 - Im gonna find another you - v01.pdf
06 - Noah - 01 - Im gonna find another you - v02.pdf
```

### File Naming Convention

- `<order> - <person> - <song#> - <title>.pdf` (single link)
- `<order> - <person> - <song#> - <title> - v<version>.pdf` (multiple links)

Where:
- `<order>`: Zero-padded order number (01, 02, 03...) assigned only to attendees with songs
- `<person>`: Person's name from the document
- `<song#>`: Zero-padded song number for that person (01, 02, 03...)
- `<title>`: Cleaned song title (spaces, no special characters)
- `<version>`: Zero-padded version number (01, 02, etc.) for multiple chart versions (capo variations)

**Note**: Attendees without songs are skipped in numbering, so order numbers may not be consecutive.

## Integration with Packeteer

The output is designed to work seamlessly with the existing `packeteer.py`:

```bash
uv run jam_downloader.py "google-doc-url"
# Review downloaded files in charts/
uv run packeteer.py charts
# Result: charts/output.pdf
```

## Features

- **Dynamic attendee parsing**: Handles changing rosters month-to-month
- **Multi-source downloads**: Supports Dropbox, Google Drive, Google Docs, and direct links
- **Clean PDF conversion**: Uses Gotenberg with LibreOffice for professional .docx to PDF conversion
- **Multi-version support**: Handles capo variations and multiple chart versions
- **Person filtering**: Download songs for specific attendees while preserving order numbers
- **Error handling**: Continues processing if individual downloads fail
- **Progress reporting**: Shows detailed download status
- **Container management**: Automatically manages Gotenberg Docker container lifecycle

## Technical Details

### Dropbox .docx Conversion Process

1. Downloads .docx file directly from Dropbox (using dl=1 parameter)
2. Saves to temporary file
3. Starts Gotenberg Docker container (if not already running)
4. Sends .docx file to Gotenberg's LibreOffice conversion API
5. Receives clean PDF conversion
6. Saves PDF to final location
7. Cleans up temporary files

### Gotenberg Container Management

- **Lazy initialization**: Container starts only when first .docx file is encountered
- **Health checks**: Waits for Gotenberg to be ready before processing
- **Reuse**: Same container processes all .docx files in a session
- **Auto-cleanup**: Container stopped at end of processing
- **Port**: Uses localhost:3001 to avoid conflicts

### Google Docs Conversion Process

1. Extracts document ID from Google Docs URL
2. Uses Google Docs export API to download as .docx format
3. Saves to temporary file
4. Uses same Gotenberg container to convert .docx to PDF
5. Saves PDF to final location
6. Cleans up temporary files

### Google Drive Handling

Converts sharing URLs to direct download URLs:
- Extracts file ID from sharing URL
- Uses `https://drive.google.com/uc?export=download&id={file_id}`
- Handles virus scan redirects for large files

## Troubleshooting

- **Docker not running**: Start Docker Desktop and verify with `docker ps`
- **Port 3001 in use**: Change the port in the code or stop conflicting services
- **Gotenberg container fails**: Check Docker daemon is running and you have internet access
- **Missing links**: Songs without links are reported but don't stop processing
- **Access errors**: Ensure Google Doc is publicly accessible or shareable via link
- **Large .docx files**: Gotenberg can handle large files but may take longer to convert

## Error Handling

The tool continues processing even if individual downloads fail:
- Prints success/failure status for each file
- Collects errors in summary report
- Never stops entire process due to single file failure
- Provides detailed error messages for debugging

## Performance

- Processes ~20 songs in 2-3 minutes (faster than previous Playwright approach)
- Gotenberg container reuse eliminates startup overhead for multiple .docx files
- Clean LibreOffice-based conversion produces professional-quality PDFs
- No more hanging issues - reliable Docker-based processing
- Container starts in ~5 seconds and handles all conversions efficiently

## Recent Changes (Gotenberg Migration)

**August 2025**: Migrated from Playwright-based .docx conversion to Gotenberg:

**Previous Issues Fixed**:
- ❌ Blank PDFs from Playwright's `page.pdf()`
- ❌ Dropbox UI elements in converted PDFs  
- ❌ Hanging browser sessions
- ❌ Complex File → Print workflow

**New Gotenberg Approach**:
- ✅ Clean, professional PDF conversion using LibreOffice
- ✅ Direct .docx download and API-based conversion
- ✅ Reliable Docker container management
- ✅ Faster processing with container reuse
- ✅ Better error handling and debugging