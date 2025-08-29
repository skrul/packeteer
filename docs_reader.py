#!/usr/bin/env python3
"""
Google Docs Reader for Jam Session Documents
Fetches public Google Docs content and parses structure
"""

import requests
import re
from urllib.parse import urlparse, parse_qs

# Document URLs provided
SAMPLE_DOCS = [
    "https://docs.google.com/document/d/1WQMtuNIIXby3qaL13_Vwod5Pl64Fq3ZEyioqfgfEjO0/edit?tab=t.0#heading=h.prg65i6ip6mc",
    "https://docs.google.com/document/d/18cQuERD6Fh0Ppcwhpdjp3-CCV_6rg84vWqUHCQeA3uc/edit?tab=t.0#heading=h.prg65i6ip6mc", 
    "https://docs.google.com/document/d/1Q8jtOsN7J1AGIKXBsbYHvLCRfo2gVpAJ_9enTJ6FgHc/edit?tab=t.0#heading=h.prg65i6ip6mc",
    "https://docs.google.com/document/d/1Q6pkZFdiEkih4-Rqm7EubNW4_Dj5QyhXsDoTrS4khoM/edit?tab=t.0#heading=h.prg65i6ip6mc",
    "https://docs.google.com/document/d/1jgYnqbkqbYsprMRHolwKUW5SqbK8AdB80NdQLfbod7k/edit?tab=t.0#heading=h.prg65i6ip6mc"
]

def extract_doc_id(url):
    """Extract document ID from Google Docs URL"""
    match = re.search(r'/document/d/([a-zA-Z0-9-_]+)', url)
    return match.group(1) if match else None

def fetch_doc_content(doc_id, format='txt'):
    """Fetch document content using public export API"""
    export_url = f"https://docs.google.com/document/d/{doc_id}/export?format={format}"
    
    try:
        response = requests.get(export_url)
        response.raise_for_status()
        return response.text
    except requests.exceptions.RequestException as e:
        print(f"Error fetching doc {doc_id}: {e}")
        return None

def parse_jam_session_doc(content, doc_id):
    """Parse document content to extract jam session structure"""
    if not content:
        return None
    
    print(f"\n=== DOCUMENT {doc_id} ===")
    print("Raw content preview:")
    print("-" * 40)
    print(content[:1000])  # First 1000 characters
    print("-" * 40)
    
    # Look for patterns that might indicate attendee names and songs
    lines = content.split('\n')
    attendees = []
    current_attendee = None
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
            
        # Try to identify attendee names vs songs
        # This is a first pass - we'll refine based on what we see
        print(f"Line: {line}")
    
    return {"doc_id": doc_id, "attendees": attendees}

def main():
    print("Fetching and analyzing jam session documents...")
    
    for i, url in enumerate(SAMPLE_DOCS, 1):
        print(f"\n--- Processing document {i} ---")
        
        doc_id = extract_doc_id(url)
        if not doc_id:
            print(f"Could not extract doc ID from: {url}")
            continue
            
        print(f"Document ID: {doc_id}")
        
        # Try HTML format to get links
        print(f"\nTrying HTML format to extract links...")
        html_content = fetch_doc_content(doc_id, 'html')
        
        if html_content:
            print("HTML content preview (first 2000 chars):")
            print(html_content[:2000])
            print("\n" + "="*60 + "\n")
            
            # Look for links in HTML
            import re
            links = re.findall(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', html_content, re.IGNORECASE)
            if links:
                print("Found links:")
                for url, text in links[:10]:  # First 10 links
                    print(f"  {text} -> {url}")
            else:
                print("No links found in HTML")
        else:
            print("Failed to fetch HTML format")

if __name__ == "__main__":
    main()