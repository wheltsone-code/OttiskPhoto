"""Stage the existing onedir app and resize existing branding for MSIX."""
from pathlib import Path
import shutil
import struct
import xml.etree.ElementTree as ET
from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parent.parent
stage = ROOT / 'build' / 'msix-stage'
stage.mkdir(parents=True, exist_ok=True)
app = ROOT / 'dist' / 'OttiskPhoto'
exe = app / 'OttiskPhoto.exe'
with exe.open('rb') as stream:
    stream.seek(0x3c)
    offset = struct.unpack('<I', stream.read(4))[0]
    stream.seek(offset + 4)
    machine = struct.unpack('<H', stream.read(2))[0]
if machine != 0x8664:
    raise SystemExit(f'Expected x64 PE; got {machine:#x}. Update manifest explicitly.')
shutil.copytree(app, stage / 'App', dirs_exist_ok=True)
shutil.copy2(ROOT / 'tools' / 'AppxManifest.xml', stage / 'AppxManifest.xml')
assets = stage / 'Assets'
assets.mkdir(exist_ok=True)
logo = Image.open(ROOT / 'assets' / 'logo.png').convert('RGBA')
for name, size in [('StoreLogo', 50), ('Square44x44Logo', 44), ('Square150x150Logo', 150)]:
    ImageOps.contain(logo, (size, size)).save(assets / f'{name}.png')
manifest = ET.parse(stage / 'AppxManifest.xml')
ns = {'m': 'http://schemas.microsoft.com/appx/manifest/foundation/windows10'}
identity = manifest.find('m:Identity', ns).attrib
assert identity['Name'] == 'WeltsOne.605494C5ADEE5'
assert identity['Publisher'] == 'CN=B2837D41-24F1-433F-9044-BD76EF8258AD'
assert identity['Version'].split('.')[-1] == '0'
print(stage)
