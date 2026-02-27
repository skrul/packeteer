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


def greedy_spread(files):
    """Strategy 3: Greedy spread - always picks the most overdue person next, no back-to-back."""
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

    if total == 0:
        return []

    state = {}
    for person_id in buckets:
        num_songs = len(buckets[person_id])
        state[person_id] = {
            'songs': buckets[person_id][:],
            'ideal_gap': total / num_songs,
            'slots_since_last': total,  # start high so everyone is eligible immediately
        }

    file_list = []
    last_person = None

    for _ in range(total):
        best_person = None
        best_urgency = -1

        for person_id, info in state.items():
            if not info['songs']:
                continue
            if person_id == last_person:
                continue
            urgency = info['slots_since_last'] / info['ideal_gap']
            if urgency > best_urgency:
                best_urgency = urgency
                best_person = person_id

        # Fallback: if only one person has songs left, allow back-to-back
        if best_person is None:
            for person_id, info in state.items():
                if info['songs']:
                    best_person = person_id
                    break

        if best_person is None:
            break

        file_list.append(state[best_person]['songs'].pop(0))
        for person_id in state:
            state[person_id]['slots_since_last'] += 1
        state[best_person]['slots_since_last'] = 0
        last_person = best_person

    return file_list


def extract_person(filename):
    """Extract person name from filename like '01 - Gary - 01 - Song.pdf'"""
    parts = filename.split(' - ')
    if len(parts) >= 2:
        return parts[1].strip()
    return filename


def grade_ordering(file_list):
    """Grade the ordering based on spacing and back-to-back rules."""
    names = [extract_person(f.decode("utf-8")) for f in file_list
             if f.endswith(b".pdf") and f != b'output.pdf']
    if not names:
        return

    total = len(names)

    # Count songs per person
    song_counts = {}
    for name in names:
        song_counts[name] = song_counts.get(name, 0) + 1

    # Check back-to-back
    back_to_back = 0
    for i in range(1, len(names)):
        if names[i] == names[i - 1]:
            back_to_back += 1

    # Measure spacing quality per person
    # Ideal gap between songs = total / count
    # Score = average deviation from ideal gap (lower is better)
    spacing_scores = {}
    for person, count in song_counts.items():
        if count <= 1:
            continue
        positions = [i for i, n in enumerate(names) if n == person]
        ideal_gap = total / count
        gaps = [positions[i + 1] - positions[i] for i in range(len(positions) - 1)]
        avg_deviation = sum(abs(g - ideal_gap) for g in gaps) / len(gaps)
        spacing_scores[person] = {
            'ideal_gap': ideal_gap,
            'actual_gaps': gaps,
            'avg_deviation': avg_deviation,
        }

    # Print order
    print(f"\nSong order ({total} songs):")
    print("-" * 40)
    for i, name in enumerate(names, 1):
        print(f"  {i:2d}. {name}")

    # Print grade
    print(f"\n{'=' * 40}")
    print("GRADE")
    print(f"{'=' * 40}")

    # Back-to-back
    if back_to_back == 0:
        print(f"  Back-to-back: PASS (none)")
    else:
        print(f"  Back-to-back: FAIL ({back_to_back} occurrence{'s' if back_to_back != 1 else ''})")

    # Spacing per person
    if spacing_scores:
        print(f"\n  Spacing (ideal gap vs actual):")
        total_deviation = 0
        for person in sorted(spacing_scores):
            s = spacing_scores[person]
            gaps_str = ', '.join(str(g) for g in s['actual_gaps'])
            quality = "good" if s['avg_deviation'] <= 1.5 else "fair" if s['avg_deviation'] <= 3 else "poor"
            print(f"    {person}: ideal {s['ideal_gap']:.1f}, actual gaps [{gaps_str}] - {quality}")
            total_deviation += s['avg_deviation']
        avg_total = total_deviation / len(spacing_scores)
        overall = "GOOD" if avg_total <= 1.5 else "FAIR" if avg_total <= 3 else "POOR"
        print(f"\n  Overall spacing: {overall} (avg deviation: {avg_total:.1f})")


def main():
    parser = argparse.ArgumentParser(description='Combine PDF charts with titles into a single packet')
    parser.add_argument('directory', help='Directory containing PDF files')
    parser.add_argument('-s', '--strategy', type=int, default=1, choices=[0, 1, 2, 3],
                        help='Song ordering strategy: 0=round-robin, 1=proportional distribution (default), 2=middle-weighted, 3=greedy spread')
    parser.add_argument('-v', '--verbose', action='store_true',
                        help='Show song ordering and grade the result')

    args = parser.parse_args()

    width, height = letter
    directory = os.fsencode(args.directory)

    output = PdfWriter()

    # Select ordering strategy
    if args.strategy == 1:
        file_list = proportional_distribution(os.listdir(directory))
    elif args.strategy == 2:
        file_list = middle_weighted(os.listdir(directory))
    elif args.strategy == 3:
        file_list = greedy_spread(os.listdir(directory))
    else:
        file_list = round_robin(os.listdir(directory))

    if args.verbose:
        grade_ordering(file_list)
        print()

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
