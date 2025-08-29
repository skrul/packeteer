import os
import sys
from PyPDF2 import PdfWriter, PdfReader
import io
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
import re
from reportlab.lib.pagesizes import A4


def round_robin(files):
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


def main():
    width, height = letter
    directory = os.fsencode(sys.argv[1])

    output = PdfWriter()

    #file_list = sorted(os.listdir(directory))
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
