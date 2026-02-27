#!/usr/bin/env python3
"""
Jam Session Chart Downloader
Automatically downloads all song charts from a Google Docs jam session list
and organizes them with proper naming for the packeteer.py combiner.
"""

import argparse
import os
import re
import sys
import requests
from urllib.parse import urlparse, unquote
from pathlib import Path
import time
from typing import List, Dict, Tuple, Optional
import html


class JamSessionDownloader:
    def __init__(self, output_dir: str = "charts"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)
        self.downloads = []
        self.errors = []
        self.gotenberg_started = False

    def _ensure_gotenberg(self):
        """Start Gotenberg container if not already running"""
        import subprocess
        if self.gotenberg_started:
            return
        print(f"    Starting Gotenberg container...")
        subprocess.run(['docker', 'stop', 'gotenberg-temp'],
                     check=False, capture_output=True)
        subprocess.run(['docker', 'rm', 'gotenberg-temp'],
                     check=False, capture_output=True)
        result = subprocess.run([
            'docker', 'run', '-d', '--rm',
            '--name', 'gotenberg-temp',
            '-p', '3001:3000',
            'gotenberg/gotenberg:8'
        ], check=True, capture_output=True, text=True)
        print(f"    Container started: {result.stdout.strip()}")
        for i in range(10):
            try:
                test_response = requests.get('http://localhost:3001/health', timeout=5)
                if test_response.status_code == 200:
                    print(f"    Gotenberg is ready!")
                    self.gotenberg_started = True
                    break
            except requests.exceptions.RequestException:
                pass
            print(f"    Waiting for Gotenberg to start... ({i+1}/10)")
            time.sleep(3)
        if not self.gotenberg_started:
            raise Exception("Gotenberg container failed to start")

    def stop_gotenberg(self):
        """Stop the Gotenberg container if it was started"""
        if self.gotenberg_started:
            import subprocess
            print("Cleaning up Gotenberg container...")
            subprocess.run(['docker', 'stop', 'gotenberg-temp'],
                         check=False, capture_output=True)
            self.gotenberg_started = False
        
    def extract_doc_id(self, url: str) -> Optional[str]:
        """Extract document ID from Google Docs URL"""
        match = re.search(r'/document/d/([a-zA-Z0-9-_]+)', url)
        return match.group(1) if match else None
    
    def fetch_doc_html(self, doc_id: str) -> Optional[str]:
        """Fetch document HTML content using public export API"""
        export_url = f"https://docs.google.com/document/d/{doc_id}/export?format=html"
        
        try:
            response = requests.get(export_url)
            response.raise_for_status()
            return response.text
        except requests.exceptions.RequestException as e:
            self.errors.append(f"Error fetching doc {doc_id}: {e}")
            return None
    
    def parse_jam_session(self, html_content: str, doc_id: str) -> List[Dict]:
        """Parse HTML content to extract attendees and their songs with links.

        Parses the HTML structure directly: attendee names are in <p> tags
        followed by <ul> lists where each <li> is a song. Links within each
        <li> provide both the URL and song title directly.
        """
        if not html_content:
            return []

        # Split HTML into top-level elements (paragraphs and lists)
        # Each <p> might be an attendee name, each <ul> contains their songs
        elements = re.findall(r'<(?:p|ul)[^>]*>.*?</(?:p|ul)>', html_content, re.DOTALL)

        attendees = []
        current_attendee = None

        for element in elements:
            if element.startswith('<p'):
                # Extract plain text from paragraph
                text = re.sub(r'<[^>]+>', '', element).strip()
                text = html.unescape(text)

                # Skip empty, headers, and non-name lines
                if (not text or
                    text.startswith('PHA ') or
                    text.startswith('\ufeffPHA ') or
                    text in ['Spotify Playlist', 'PACKET', '________________'] or
                    '=' in text):
                    continue

                # Check if this looks like an attendee name
                if (len(text.split()) <= 3 and
                    not any(s in text for s in ['http', '.com', '(', ')', '[', ']']) and
                    text.replace(' ', '').isalpha()):
                    current_attendee = {
                        'name': text,
                        'order': None,
                        'songs': []
                    }
                    attendees.append(current_attendee)

            elif element.startswith('<ul') and current_attendee is not None:
                # Parse each list item as a song
                items = re.findall(r'<li[^>]*>(.*?)</li>', element, re.DOTALL)
                for item in items:
                    # Get the full plain text of the item
                    item_text = re.sub(r'<[^>]+>', '', item).strip()
                    item_text = html.unescape(item_text)

                    if not item_text or item_text == '...':
                        continue

                    # Extract links directly from this list item
                    link_pattern = r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>'
                    item_links = re.findall(link_pattern, item, re.DOTALL)

                    song_links = []
                    for url, link_text in item_links:
                        url = html.unescape(url)
                        clean_text = re.sub(r'<[^>]+>', '', html.unescape(link_text)).strip()
                        # Skip non-song links
                        if any(skip in clean_text.lower() for skip in ['spotify', 'packet']):
                            continue
                        song_links.append((url, clean_text))

                    current_attendee['songs'].append({
                        'title': item_text,
                        'links': song_links
                    })

        # Assign order numbers only to attendees with songs
        attendee_order = 0
        for attendee in attendees:
            if attendee['songs']:
                attendee_order += 1
                attendee['order'] = attendee_order

        return attendees
    
    def clean_filename(self, title: str) -> str:
        """Clean song title for use in filename"""
        # Remove artist info and extra details, keep main title
        title = re.sub(r'\s*-\s*[^-]*$', '', title)  # Remove "- Artist" at end
        title = re.sub(r'[^\w\s-]', '', title)  # Remove special chars except hyphens and spaces
        title = re.sub(r'\s+', ' ', title)  # Normalize spaces (no underscores)
        title = title.strip(' -')  # Remove leading/trailing spaces and hyphens
        return title[:50]  # Limit length
    
    async def init_playwright(self):
        """Initialize Playwright browser"""
        if not self.playwright:
            try:
                from playwright.async_api import async_playwright
                self.playwright = await async_playwright().start()
                # Launch with optimized settings for faster performance
                self.browser = await self.playwright.chromium.launch(
                    headless=True,
                    args=[
                        '--no-sandbox',
                        '--disable-dev-shm-usage',
                        '--disable-web-security',
                        '--disable-features=VizDisplayCompositor'
                    ]
                )
                return True
            except ImportError:
                self.errors.append("Playwright not installed. Run: pip install playwright && playwright install")
                return False
            except Exception as e:
                self.errors.append(f"Failed to initialize Playwright: {e}")
                return False
        return True
    
    async def close_playwright(self):
        """Clean up Playwright resources"""
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()
    
    def is_dropbox_docx(self, url: str) -> bool:
        """Check if URL is a Dropbox .doc/.docx file"""
        return 'dropbox.com' in url and ('.docx' in url or '.doc' in url)
    
    def is_dropbox_pdf(self, url: str) -> bool:
        """Check if URL is a Dropbox .pdf file"""
        return 'dropbox.com' in url and '.pdf' in url
    
    def is_google_drive(self, url: str) -> bool:
        """Check if URL is a Google Drive file"""
        return 'drive.google.com' in url
    
    def is_google_docs(self, url: str) -> bool:
        """Check if URL is a Google Docs document that needs conversion"""
        return 'docs.google.com/document' in url
    
    async def download_dropbox_docx_as_pdf(self, url: str, filepath: Path) -> bool:
        """Download Dropbox .docx file as PDF using Playwright"""
        page = None
        context = None
        try:
            if not await self.init_playwright():
                return False
            
            # Create a new context for each download to avoid state issues
            context = await self.browser.new_context()
            page = await context.new_page()
            
            # Set shorter timeouts to avoid hanging
            page.set_default_timeout(30000)  # 30 seconds max
            
            print(f"    Opening Dropbox page...")
            await page.goto(url, wait_until='domcontentloaded', timeout=20000)
            
            # Wait briefly for content to load
            await page.wait_for_timeout(1500)
            
            print(f"    Generating PDF from page content...")
            
            # Skip print button search - go straight to PDF generation for reliability
            pdf_bytes = await page.pdf(
                format='A4',
                margin={'top': '0.5in', 'bottom': '0.5in', 'left': '0.5in', 'right': '0.5in'},
                print_background=True
            )
            
            with open(filepath, 'wb') as f:
                f.write(pdf_bytes)
            
            print(f"    ✓ Generated PDF successfully")
            return True
                
        except Exception as e:
            print(f"    ✗ Error: {e}")
            self.errors.append(f"Failed to download Dropbox docx {url}: {e}")
            return False
        finally:
            # Clean up resources
            if page:
                try:
                    await page.close()
                except:
                    pass
            if context:
                try:
                    await context.close()
                except:
                    pass
    
    async def download_file_async(self, url: str, filepath: Path) -> bool:
        """Download a file from URL to filepath (async version)"""
        try:
            # Handle Google redirect URLs
            if 'google.com/url' in url:
                match = re.search(r'[?&]q=([^&]+)', url)
                if match:
                    actual_url = unquote(match.group(1))
                    url = actual_url
            
            print(f"  Downloading: {url}")
            
            # Use Playwright for Dropbox .docx files
            if self.is_dropbox_docx(url):
                return await self.download_dropbox_docx_as_pdf(url, filepath)
            
            # Regular download for other files
            response = requests.get(url, stream=True)
            response.raise_for_status()
            
            with open(filepath, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
            
            return True
            
        except Exception as e:
            self.errors.append(f"Failed to download {url}: {e}")
            return False
    
    def download_file(self, url: str, filepath: Path) -> bool:
        """Download a file from URL to filepath"""
        try:
            # Handle Google redirect URLs
            if 'google.com/url' in url:
                match = re.search(r'[?&]q=([^&]+)', url)
                if match:
                    actual_url = unquote(match.group(1))
                    url = actual_url
            
            print(f"  Downloading: {url}")
            
            # Handle different link types
            if self.is_dropbox_docx(url):
                return self.download_dropbox_simple(url, filepath)
            elif self.is_dropbox_pdf(url):
                return self.download_dropbox_pdf(url, filepath)
            elif self.is_google_docs(url):
                return self.download_google_docs_simple(url, filepath)
            elif self.is_google_drive(url):
                return self.download_google_drive(url, filepath)
            else:
                # Regular download for direct PDF files
                response = requests.get(url, stream=True, timeout=30)
                response.raise_for_status()
                
                with open(filepath, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        f.write(chunk)
                
                return True
            
        except Exception as e:
            self.errors.append(f"Failed to download {url}: {e}")
            print(f"    ✗ Download failed: {e}")
            return False
    
    def download_dropbox_simple(self, url: str, filepath: Path) -> bool:
        """Download Dropbox .doc/.docx as PDF using Gotenberg"""
        print("    Converting .doc/.docx to PDF using Gotenberg...")
        return self.download_docx_with_gotenberg(url, filepath)
    
    def download_google_docs_simple(self, url: str, filepath: Path) -> bool:
        """Download Google Docs as PDF using Gotenberg"""
        print(f"    Converting Google Doc to PDF using Gotenberg...")
        return self.download_google_docs_with_gotenberg(url, filepath)
    
    
    def download_dropbox_pdf(self, url: str, filepath: Path) -> bool:
        """Download Dropbox .pdf file using direct download"""
        try:
            # Convert sharing URL to direct download URL
            if 'dropbox.com/scl/fi/' in url:
                # Change dl=0 to dl=1 for direct download
                direct_url = url.replace('&dl=0', '&dl=1').replace('?dl=0', '?dl=1')
                if 'dl=1' not in direct_url:
                    direct_url += '&dl=1'
                
                print(f"    Using Dropbox direct download...")
                response = requests.get(direct_url, stream=True, timeout=30)
                response.raise_for_status()
                
                with open(filepath, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        f.write(chunk)
                
                print(f"    ✓ Dropbox PDF download successful")
                return True
            else:
                print(f"    ✗ Unsupported Dropbox URL format")
                return False
                
        except Exception as e:
            self.errors.append(f"Failed to download Dropbox PDF {url}: {e}")
            print(f"    ✗ Dropbox PDF download failed: {e}")
            return False
    
    def download_google_drive(self, url: str, filepath: Path) -> bool:
        """Download Google Drive file using direct download URL"""
        try:
            # Convert Google Drive sharing URL to direct download URL
            file_id = None
            
            if '/file/d/' in url:
                # Extract file ID from URL like: https://drive.google.com/file/d/FILE_ID/view?usp=sharing
                file_id = url.split('/file/d/')[1].split('/')[0]
            elif 'id=' in url:
                # Extract from URL with id parameter
                file_id = url.split('id=')[1].split('&')[0]
            
            if file_id:
                # Use Google Drive direct download URL
                download_url = f"https://drive.google.com/uc?export=download&id={file_id}"
                print(f"    Using Google Drive direct download...")
                
                response = requests.get(download_url, stream=True, timeout=30)
                
                # Handle Google Drive's virus scan redirect for large files
                if 'confirm=' in response.text:
                    # Look for the confirm token
                    import re
                    confirm_token = re.search(r'confirm=([^&]+)', response.text)
                    if confirm_token:
                        confirm_url = f"{download_url}&confirm={confirm_token.group(1)}"
                        response = requests.get(confirm_url, stream=True, timeout=30)
                
                response.raise_for_status()
                
                with open(filepath, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        f.write(chunk)
                
                print(f"    ✓ Google Drive download successful")
                return True
            else:
                print(f"    ✗ Could not extract Google Drive file ID")
                return False
                
        except Exception as e:
            self.errors.append(f"Failed to download Google Drive file {url}: {e}")
            print(f"    ✗ Google Drive download failed: {e}")
            return False
    
    def download_docx_with_gotenberg(self, url: str, filepath: Path) -> bool:
        """Download .docx file and convert to PDF using Gotenberg"""
        import tempfile

        temp_docx_path = None
        try:
            # First, download the .docx file
            print(f"    Downloading .docx file from Dropbox...")
            # Convert sharing URL to direct download URL
            if 'dropbox.com/scl/fi/' in url:
                direct_url = url.replace('&dl=0', '&dl=1').replace('?dl=0', '?dl=1')
                if 'dl=1' not in direct_url:
                    direct_url += '&dl=1'
            else:
                direct_url = url

            response = requests.get(direct_url, stream=True, timeout=30)
            response.raise_for_status()

            # Save to temporary file
            with tempfile.NamedTemporaryFile(suffix='.docx', delete=False) as temp_docx:
                for chunk in response.iter_content(chunk_size=8192):
                    temp_docx.write(chunk)
                temp_docx_path = temp_docx.name

            print(f"    Downloaded .docx to temporary file")

            self._ensure_gotenberg()

            # Convert using Gotenberg API
            print(f"    Converting .docx to PDF with Gotenberg...")
            with open(temp_docx_path, 'rb') as docx_file:
                files = {'files': docx_file}
                convert_response = requests.post(
                    'http://localhost:3001/forms/libreoffice/convert',
                    files=files,
                    timeout=60
                )
                convert_response.raise_for_status()

                # Save the PDF
                with open(filepath, 'wb') as pdf_file:
                    pdf_file.write(convert_response.content)

            print(f"    ✓ Successfully converted .docx to PDF")
            return True

        except Exception as e:
            self.errors.append(f"Failed to convert .docx to PDF {url}: {e}")
            print(f"    ✗ Gotenberg conversion failed: {e}")
            return False
        finally:
            if temp_docx_path:
                try:
                    os.unlink(temp_docx_path)
                except:
                    pass
    
    def download_google_docs_with_gotenberg(self, url: str, filepath: Path) -> bool:
        """Download Google Docs document and convert to PDF using Gotenberg"""
        import tempfile

        temp_docx_path = None
        try:
            # Convert Google Docs URL to export format (docx)
            print(f"    Downloading Google Doc as .docx...")

            # Extract document ID from URL
            doc_id = None
            if '/document/d/' in url:
                doc_id = url.split('/document/d/')[1].split('/')[0]

            if not doc_id:
                raise Exception("Could not extract Google Doc ID from URL")

            # Use Google Docs export API to get .docx format
            export_url = f"https://docs.google.com/document/d/{doc_id}/export?format=docx"

            response = requests.get(export_url, stream=True, timeout=30)
            response.raise_for_status()

            # Save to temporary file
            with tempfile.NamedTemporaryFile(suffix='.docx', delete=False) as temp_docx:
                for chunk in response.iter_content(chunk_size=8192):
                    temp_docx.write(chunk)
                temp_docx_path = temp_docx.name

            print(f"    Downloaded Google Doc to temporary file")

            self._ensure_gotenberg()

            # Convert using Gotenberg API
            print(f"    Converting Google Doc to PDF with Gotenberg...")
            with open(temp_docx_path, 'rb') as docx_file:
                files = {'files': docx_file}
                convert_response = requests.post(
                    'http://localhost:3001/forms/libreoffice/convert',
                    files=files,
                    timeout=60
                )
                convert_response.raise_for_status()

                # Save the PDF
                with open(filepath, 'wb') as pdf_file:
                    pdf_file.write(convert_response.content)

            print(f"    ✓ Successfully converted Google Doc to PDF")
            return True

        except Exception as e:
            self.errors.append(f"Failed to convert Google Doc to PDF {url}: {e}")
            print(f"    ✗ Google Doc conversion failed: {e}")
            return False
        finally:
            if temp_docx_path:
                try:
                    os.unlink(temp_docx_path)
                except:
                    pass
    
    def download_with_subprocess_playwright(self, url: str, filepath: Path) -> bool:
        """Use subprocess to run Playwright in isolation to avoid hanging"""
        import subprocess
        import tempfile
        
        try:
            # Create a simplified Playwright script for File -> Print workflow
            script_content = f'''
import asyncio
from playwright.async_api import async_playwright
from pathlib import Path

async def download_pdf():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)  # Debug mode
        context = await browser.new_context()
        page = await context.new_page()
        page.set_default_timeout(15000)
        
        try:
            print("Opening Dropbox page...")
            await page.goto("{url}", wait_until="networkidle")
            await page.wait_for_timeout(2000)
            
            # Look for File menu button
            print("Looking for File menu...")
            file_selectors = [
                'button:has-text("File")',
                '[aria-label*="File"]',
                'button[title*="File"]'
            ]
            
            file_clicked = False
            for selector in file_selectors:
                try:
                    file_button = await page.wait_for_selector(selector, timeout=3000)
                    if file_button and await file_button.is_visible():
                        print(f"Found File button: {{selector}}")
                        await file_button.click()
                        print("Clicked File menu")
                        file_clicked = True
                        await page.wait_for_timeout(1000)
                        break
                except:
                    continue
            
            if file_clicked:
                # Look for Print option in the opened menu
                print("Looking for Print option in menu...")
                print_selectors = [
                    'text="Print"',
                    '[role="menuitem"]:has-text("Print")',
                    'button:has-text("Print")',
                    '[aria-label*="Print"]'
                ]
                
                for selector in print_selectors:
                    try:
                        print_option = await page.wait_for_selector(selector, timeout=3000)
                        if print_option and await print_option.is_visible():
                            print(f"Found Print option: {{selector}}")
                            
                            # Set up listener for new page (PDF viewer tab)
                            print("Setting up new page listener...")
                            async with context.expect_page() as new_page_info:
                                await print_option.click()
                                print("Clicked Print option")
                            
                            # Get the new PDF viewer page (Chromium's built-in PDF viewer)
                            pdf_page = await new_page_info.value
                            await pdf_page.wait_for_load_state('networkidle')
                            print("Chromium PDF viewer page loaded")
                            
                            # Wait for PDF to fully load in Chromium viewer
                            await pdf_page.wait_for_timeout(3000)
                            print("Waited for PDF to fully load")
                            
                            # Check what's on the page
                            title = await pdf_page.title()
                            print(f"PDF page title: {{title}}")
                            
                            # Get the PDF content from the Chromium PDF viewer
                            print("Extracting PDF from Chromium viewer...")
                            try:
                                # Wait a bit more for PDF to fully load
                                await pdf_page.wait_for_timeout(2000)
                                
                                # The PDF viewer tab has the PDF loaded - we need to get the PDF URL and download it
                                # In Chromium PDF viewer, the actual PDF is loaded from a blob: or chrome-extension: URL
                                current_url = pdf_page.url
                                print(f"PDF viewer URL: {{current_url}}")
                                
                                if 'blob:' in current_url or current_url.endswith('.pdf'):
                                    # This is the actual PDF URL, download it directly
                                    print("Found direct PDF URL, downloading...")
                                    import requests
                                    response = requests.get(current_url, stream=True, timeout=30)
                                    response.raise_for_status()
                                    
                                    with open("{filepath}", "wb") as f:
                                        for chunk in response.iter_content(chunk_size=8192):
                                            f.write(chunk)
                                    
                                    print("SUCCESS: PDF downloaded from direct URL")
                                    await pdf_page.close()
                                    await browser.close()
                                    return
                                else:
                                    # Try to trigger download through Chromium's print dialog
                                    print("Triggering download via print dialog...")
                                    
                                    # Use Ctrl+S to save the PDF
                                    async with pdf_page.expect_download() as download_info:
                                        await pdf_page.keyboard.press('Control+s')
                                        await pdf_page.wait_for_timeout(1000)
                                        # Press Enter to confirm save
                                        await pdf_page.keyboard.press('Enter')
                                    
                                    download = await download_info.value
                                    await download.save_as("{filepath}")
                                    print("SUCCESS: PDF saved via Ctrl+S")
                                    await pdf_page.close()
                                    await browser.close()
                                    return
                                
                            except Exception as e:
                                print(f"Error extracting PDF: {{e}}")
                                # Fallback: try to find and click download button
                                try:
                                    print("Trying to find download button...")
                                    download_btn = await pdf_page.wait_for_selector('button[title="Download"]', timeout=3000)
                                    if download_btn:
                                        async with pdf_page.expect_download() as download_info:
                                            await download_btn.click()
                                        download = await download_info.value  
                                        await download.save_as("{filepath}")
                                        print("SUCCESS: PDF downloaded via download button")
                                        await pdf_page.close()
                                        await browser.close()
                                        return
                                except:
                                    pass
                                
                                print("All PDF extraction methods failed")
                            
                            # Close the PDF viewer page
                            await pdf_page.close()
                            break
                    except:
                        continue
            
            print("File -> Print workflow failed, trying keyboard shortcut...")
            await page.keyboard.press('Control+p')
            await page.wait_for_timeout(3000)
            
            # Try to find download button after Ctrl+P
            try:
                download_btn = await page.wait_for_selector('#download', timeout=10000)
                if download_btn:
                    async with page.expect_download() as download_info:
                        await download_btn.click()
                    download = await download_info.value
                    await download.save_as("{filepath}")
                    print("SUCCESS: PDF downloaded via Ctrl+P")
                else:
                    raise Exception("Download button not found")
            except:
                print("Keyboard shortcut failed, using fallback PDF generation...")
                pdf_bytes = await page.pdf(
                    format="A4",
                    margin={{"top": "0.5in", "bottom": "0.5in", "left": "0.5in", "right": "0.5in"}},
                    print_background=False
                )
                
                with open("{filepath}", "wb") as f:
                    f.write(pdf_bytes)
                print("SUCCESS: Fallback PDF generated")
            
        except Exception as e:
            print(f"Error: {{e}}")
        finally:
            await browser.close()

asyncio.run(download_pdf())
'''
            
            # Write script to temp file
            with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
                f.write(script_content)
                script_path = f.name
            
            # Run with timeout
            result = subprocess.run(
                ['python', script_path],
                capture_output=True,
                text=True,
                timeout=45  # 45 second timeout
            )
            
            # Clean up temp file
            Path(script_path).unlink()
            
            if result.returncode == 0 and 'SUCCESS' in result.stdout:
                print(f"    ✓ PDF generated via subprocess")
                return True
            else:
                print(f"    ✗ Subprocess failed: {result.stderr}")
                return False
                
        except subprocess.TimeoutExpired:
            print(f"    ✗ Subprocess timed out")
            return False
        except Exception as e:
            print(f"    ✗ Subprocess error: {e}")
            return False
    
    def download_and_combine(self, links: List[Tuple[str, str]], filepath: Path, filename: str) -> None:
        """Download multiple links and combine them into a single PDF."""
        from PyPDF2 import PdfWriter, PdfReader
        import tempfile

        temp_files = []
        try:
            for i, (link_url, link_text) in enumerate(links):
                temp_path = filepath.parent / f".tmp_{filepath.stem}_{i}.pdf"
                temp_files.append(temp_path)
                print(f"      Downloading part {i+1}/{len(links)}: {link_text}")
                if not self.download_file(link_url, temp_path):
                    print(f"      ✗ Failed to download part {i+1}")
                    return

            writer = PdfWriter()
            for temp_path in temp_files:
                reader = PdfReader(open(temp_path, "rb"))
                for page in reader.pages:
                    writer.add_page(page)

            with open(filepath, "wb") as out:
                writer.write(out)

            self.downloads.append(str(filepath))
            print(f"      ✓ Combined {len(links)} parts into: {filename}")
        except Exception as e:
            self.errors.append(f"Failed to combine PDFs for {filename}: {e}")
            print(f"      ✗ Failed to combine: {e}")
        finally:
            for temp_path in temp_files:
                try:
                    os.unlink(temp_path)
                except:
                    pass

    def process_document(self, doc_url: str, person_filter: str = None) -> None:
        """Main processing function"""
        print(f"Processing document: {doc_url}")
        
        doc_id = self.extract_doc_id(doc_url)
        if not doc_id:
            self.errors.append(f"Could not extract document ID from: {doc_url}")
            return
        
        html_content = self.fetch_doc_html(doc_id)
        if not html_content:
            return
        
        attendees = self.parse_jam_session(html_content, doc_id)
        
        if not attendees:
            self.errors.append("No attendees found in document")
            return
        
        # Apply person filter if specified
        if person_filter:
            person_filter_lower = person_filter.lower()
            filtered_attendees = []
            for attendee in attendees:
                if person_filter_lower in attendee['name'].lower():
                    filtered_attendees.append(attendee)
            
            if not filtered_attendees:
                self.errors.append(f"No attendee found matching '{person_filter}'")
                return
            
            print(f"Filtering by person: '{person_filter}' (found {len(filtered_attendees)} match(es))")
            attendees = filtered_attendees
        
        attendees_with_songs = [a for a in attendees if a['order'] is not None]
        print(f"Found {len(attendees_with_songs)} attendees with songs:")
        
        for attendee in attendees:
            if attendee['order'] is not None:
                print(f"  {attendee['order']:02d}. {attendee['name']} ({len(attendee['songs'])} songs)")
                
                for song_num, song in enumerate(attendee['songs'], 1):
                    if not song['links']:
                        print(f"    Song {song_num:02d}: {song['title']} (No links found)")
                        continue

                    clean_title = self.clean_filename(song['title'])
                    filename = f"{attendee['order']:02d} - {attendee['name']} - {song_num:02d} - {clean_title}.pdf"
                    filepath = self.output_dir / filename

                    print(f"    Song {song_num:02d}: {song['title']}")

                    if len(song['links']) == 1:
                        link_url, link_text = song['links'][0]
                        if self.download_file(link_url, filepath):
                            self.downloads.append(str(filepath))
                            print(f"      ✓ Saved: {filename}")
                        else:
                            print(f"      ✗ Failed: {filename}")
                    else:
                        # Multiple links - download each and combine into one PDF
                        self.download_and_combine(song['links'], filepath, filename)
        
        # No async cleanup needed with subprocess approach
        
        self.print_summary()
    
    def print_summary(self):
        """Print download summary"""
        print(f"\n{'='*60}")
        print(f"DOWNLOAD SUMMARY")
        print(f"{'='*60}")
        print(f"Successfully downloaded: {len(self.downloads)} files")
        print(f"Errors: {len(self.errors)}")
        
        if self.errors:
            print(f"\nErrors encountered:")
            for error in self.errors:
                print(f"  - {error}")
        
        if self.downloads:
            print(f"\nFiles saved to: {self.output_dir}")
            print(f"Ready for: python packeteer.py {self.output_dir}")


def main():
    parser = argparse.ArgumentParser(description='Download jam session charts from Google Docs')
    parser.add_argument('doc_url', help='Google Docs URL')
    parser.add_argument('-o', '--output', default='charts', help='Output directory (default: charts)')
    parser.add_argument('-p', '--person', help='Filter by person name (case insensitive, partial match supported)')
    
    args = parser.parse_args()
    
    downloader = JamSessionDownloader(args.output)
    try:
        downloader.process_document(args.doc_url, person_filter=args.person)
    finally:
        downloader.stop_gotenberg()


if __name__ == "__main__":
    main()