import os
import sys
from PyPDF2 import PdfWriter, PdfReader
import io
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
import re
from reportlab.lib.pagesizes import A4
import argparse


def round_robin(files):
    """Strategy 0: Classic round-robin - each person does their first song, then second, etc."""
    buckets = {}
    total = 0
    p = re.compile(r'^(\d+).*')
    for f in sorted(files):
        m = p.match(f.decode("utf-8"))
        if m is not None:
            total += 1
            b = int(m.group(1))
            if b in buckets:
                buckets[b].append(f)
            else:
                buckets[b] = [f]
    file_list = []
    while total > 0:
        for i in sorted(buckets.keys()):
            if len(buckets[i]) > 0:
                file_list.append(buckets[i].pop(0))
                total -= 1
    return file_list


def middle_weighted(files):
    """Strategy 2: Middle-weighted - people with fewer songs participate in middle rounds only."""
    buckets = {}
    total = 0
    p = re.compile(r'^(\d+).*')

    # Organize files into buckets by person
    for f in sorted(files):
        m = p.match(f.decode("utf-8"))
        if m is not None:
            total += 1
            b = int(m.group(1))
            if b in buckets:
                buckets[b].append(f)
            else:
                buckets[b] = [f]

    if total == 0:
        return []

    # Find max songs (determines number of rounds)
    max_songs = max(len(songs) for songs in buckets.values())

    # Determine which rounds each person participates in
    person_rounds = {}
    for person_id in sorted(buckets.keys()):
        num_songs = len(buckets[person_id])

        if num_songs == max_songs:
            # Full participation
            person_rounds[person_id] = list(range(1, max_songs + 1))
        else:
            # Center their songs in the middle rounds
            # Skip first (max_songs - num_songs) // 2 rounds
            # and last (max_songs - num_songs) - first_skip rounds
            first_skip = (max_songs - num_songs) // 2
            start_round = first_skip + 1
            end_round = start_round + num_songs - 1
            person_rounds[person_id] = list(range(start_round, end_round + 1))

    # Build the file list round by round
    file_list = []
    song_indices = {person_id: 0 for person_id in buckets.keys()}

    for round_num in range(1, max_songs + 1):
        for person_id in sorted(buckets.keys()):
            if round_num in person_rounds[person_id]:
                idx = song_indices[person_id]
                if idx < len(buckets[person_id]):
                    file_list.append(buckets[person_id][idx])
                    song_indices[person_id] += 1

    return file_list


def proportional_distribution(files):
    """Strategy 1: Proportional distribution - spreads each person's songs by skipping their turns strategically."""
    buckets = {}
    total = 0
    p = re.compile(r'^(\d+).*')

    # First, organize files into buckets by person
    for f in sorted(files):
        m = p.match(f.decode("utf-8"))
        if m is not None:
            total += 1
            b = int(m.group(1))
            if b in buckets:
                buckets[b].append(f)
            else:
                buckets[b] = [f]

    if total == 0:
        return []

    # Calculate ideal spacing for each person
    # This represents how many rounds to wait between songs
    person_info = {}
    for person_id in sorted(buckets.keys()):
        num_songs = len(buckets[person_id])
        # Ideal rounds between songs = total_songs / their_songs
        # e.g., 10 total songs, 2 for this person = every 5 rounds
        ideal_interval = total / num_songs if num_songs > 0 else float('inf')
        person_info[person_id] = {
            'songs': buckets[person_id][:],  # Copy the list
            'ideal_interval': ideal_interval,
            'rounds_since_last': 0,  # Start at 0, will increment each round
        }

    file_list = []
    max_rounds = total * 2  # Safety limit

    # Go round by round
    for round_num in range(max_rounds):
        if len(file_list) >= total:
            break

        # Each round, check each person in order
        for person_id in sorted(buckets.keys()):
            if len(file_list) >= total:
                break

            info = person_info[person_id]
            if len(info['songs']) == 0:
                continue  # This person is out of songs

            # Increment the counter for this person
            info['rounds_since_last'] += 1

            # Should this person play this round?
            # They play if enough rounds have passed since their last song
            if info['rounds_since_last'] >= info['ideal_interval']:
                # Add their next song
                song = info['songs'].pop(0)
                file_list.append(song)
                info['rounds_since_last'] = 0  # Reset counter

    # Safety: add any remaining songs
    if len(file_list) < total:
        for person_id in sorted(buckets.keys()):
            while person_info[person_id]['songs']:
                file_list.append(person_info[person_id]['songs'].pop(0))

    return file_list


def main():
    parser = argparse.ArgumentParser(description='Combine PDF charts with titles into a single packet')
    parser.add_argument('directory', help='Directory containing PDF files')
    parser.add_argument('-s', '--strategy', type=int, default=0, choices=[0, 1, 2],
                        help='Song ordering strategy: 0=round-robin (default), 1=proportional distribution, 2=middle-weighted')

    args = parser.parse_args()

    width, height = letter
    directory = os.fsencode(args.directory)

    output = PdfWriter()

    # Select ordering strategy
    if args.strategy == 1:
        file_list = proportional_distribution(os.listdir(directory))
    elif args.strategy == 2:
        file_list = middle_weighted(os.listdir(directory))
    else:
        file_list = round_robin(os.listdir(directory))

    for file in file_list:
        if not file.endswith(b".pdf") or file == b'output.pdf':
            continue

        full_path = os.path.join(directory, file)
        # read your existing PDF
        existing_pdf = PdfReader(open(full_path, "rb"))
        pagesize = existing_pdf.pages[0].mediabox
        upperLeftY = int(pagesize.upper_left[1])

        title = os.path.splitext(file)[0]

        packet = io.BytesIO()
        can = canvas.Canvas(packet, pagesize=(pagesize.width, pagesize.height))

        can.setFont("Helvetica", 15)
        can.setFillColorRGB(0,0,0)
        can.drawString(3, upperLeftY - 13, title)
        can.showPage()
        can.save()
        new_pdf_landscape = PdfReader(packet)

        # add the "watermark" (which is the new pdf) on the existing page
        for i in range(0, len(existing_pdf.pages)):
            page = existing_pdf.pages[i]
            page.merge_page(new_pdf_landscape.pages[0])
            output.add_page(page)

    # finally, write "output" to a real file
    outputStream = open(os.path.join(directory, b'output.pdf'), "wb")
    output.write(outputStream)
    outputStream.close()


if __name__ == '__main__':
    main()
