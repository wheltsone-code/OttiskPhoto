"""Authored regression documents, deliberately labelled synthetic."""
import base64
from io import BytesIO
from pathlib import Path
from PIL import Image
from reportlab.pdfgen import canvas


def make_vectors(folder):
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    png=BytesIO();Image.new('RGBA',(20,20),(255,0,100,130)).save(png,format='PNG')
    embedded=base64.b64encode(png.getvalue()).decode()
    svg=f'''<svg xmlns="http://www.w3.org/2000/svg" xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape"
 xmlns:sodipodi="http://sodipodi.sourceforge.net/DTD/sodipodi-0.dtd" width="70mm" height="45mm" viewBox="0 0 700 450">
 <defs><linearGradient id="g"><stop stop-color="#FD3977"/><stop offset="1" stop-color="#0044aa"/></linearGradient>
 <clipPath id="clip"><circle cx="320" cy="220" r="100"/></clipPath></defs>
 <rect width="700" height="450" fill="url(#g)" opacity=".6"/>
 <g clip-path="url(#clip)"><rect x="200" y="80" width="300" height="300" fill="#FD3977"/>
 <image x="230" y="110" width="230" height="230" href="data:image/png;base64,{embedded}"/></g>
 <text x="20" y="410" font-family="Arial" font-size="40">VECTOR text 123</text>
 <path d="M10 10L680 430" stroke="black" stroke-width=".8"/></svg>'''
    (folder/'features.svg').write_text(svg,'utf-8')
    # Inkscape's real namespace, multipage document, second page outside first.
    multi=svg.replace('http://www.inkscape.org/namespaces/inkscape','http://www.inkscape.org/namespaces/inkscape')
    multi=multi.replace('<defs>','<sodipodi:namedview><inkscape:page x="0" y="0" width="700" height="450"/>'
                       '<inkscape:page x="750" y="0" width="700" height="450"/></sodipodi:namedview><defs>')
    multi=multi.replace('</svg>','<text x="780" y="100" font-family="Arial" font-size="40">PAGE TWO</text></svg>')
    (folder/'multipage.svg').write_text(multi,'utf-8')
    ps='''%!PS-Adobe-3.0 EPSF-3.0
%%Creator: Adobe Illustrator(TM) synthetic regression fixture
%%BoundingBox: 0 0 200 100
%%HiResBoundingBox: 0 0 200 100
%%Pages: 1
%%EndComments
/Helvetica findfont 14 scalefont setfont
1 0 0 setrgbcolor 0 0 100 100 rectfill
0 0 1 setrgbcolor 100 0 100 100 rectfill
0 0 0 setrgbcolor 10 40 moveto (POSTSCRIPT text) show
newpath 10 10 moveto 190 90 lineto .5 setlinewidth stroke
showpage
%%EOF
'''
    (folder/'features.eps').write_text(ps,'ascii')
    (folder/'postscript.ai').write_text(ps,'ascii')
    pdf=canvas.Canvas(str(folder/'pdf-compatible.ai'),pagesize=(200,100))
    pdf.drawString(10,30,'AI PDF PAGE ONE');pdf.showPage();pdf.drawString(10,30,'AI PDF PAGE TWO');pdf.save()
    (folder/'false.ai').write_text('not Illustrator','utf-8')
    return folder
