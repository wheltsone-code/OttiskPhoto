"""Render the supplied control PDF with the application's existing PDFium."""
from pathlib import Path
import sys
import pypdfium2 as pdfium
from PIL import Image,ImageDraw

source=Path(sys.argv[1])
target=Path(sys.argv[2]); target.mkdir(parents=True,exist_ok=True)
doc=pdfium.PdfDocument(source)
sheet=Image.new('RGB',(1000,250*((len(doc)+1)//2)),'#dddddd')
draw=ImageDraw.Draw(sheet)
for i in range(len(doc)):
    page=doc[i].render(scale=.8).to_pil().convert('RGB')
    page.save(target/f'page-{i+1:02}.png')
    page.thumbnail((490,225))
    x,y=(i%2)*500,(i//2)*250
    sheet.paste(page,(x,y+20))
    draw.text((x+8,y+4),f'PDF {i+1}: '+('front' if i%2==0 else 'back'),fill='black')
sheet.save(target/'contact.png')
doc.close()
