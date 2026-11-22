"""Consolidate actual frozen-app reports and verify the Store archive identity."""
from pathlib import Path
import hashlib
import json
import sys
import zipfile
import xml.etree.ElementTree as ET

root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root))
from illusive_print.metadata import VERSION

version=VERSION+'.0'
files={'exe':root/'dist/OttiskPhoto.exe',
       'store_msix':root/f'dist/store/OttiskPhoto_{version}_x64_Store.msix',
       'control_pdf':root/'dist/OttiskPhoto_Duplex_Control.pdf'}
with zipfile.ZipFile(files['store_msix']) as package:
    manifest=ET.fromstring(package.read('AppxManifest.xml'))
    identity=manifest.find('{*}Identity').attrib
    assert identity['Name']=='WeltsOne.605494C5ADEE5'
    assert identity['Publisher']=='CN=B2837D41-24F1-433F-9044-BD76EF8258AD'
    assert identity['Version']==version and identity['ProcessorArchitecture']=='x64'
    assert not any(name.lower()=='appxsignature.p7x' for name in package.namelist())
    assert any(name.endswith('assets/blank-panel.png') for name in package.namelist())
reports={}
for variant in ('portable','installed'):
    fold=root/f'tmp/fold-{variant}-check/fold-check.json'
    reports[variant+'_fold']=json.loads(fold.read_text(encoding='utf-8'))
    for mode,filename in (('project','project-check.json'),('documents','document-check.json'),('smoke','self-check.json')):
        path=root/f'tmp/project-release-check/{variant}/{mode}/{filename}'
        reports[variant+'_'+mode]=json.loads(path.read_text(encoding='utf-8'))
assert all(r['passed'] for r in reports.values())
record={'version':version,'identity':identity,'store_unsigned':True,
        'files':{key:{'path':str(path),'bytes':path.stat().st_size,'sha256':hashlib.sha256(path.read_bytes()).hexdigest()} for key,path in files.items()},
        'unit_tests':117,'reports':reports,
        'manual_checks':{'real_mouse_drag':'not completed','Canon_properties_cancel':'not run','paper_folding':'not run','WACK':'not available at standard path','Store_submission':'not run'}}
target=root/f'dist/store/verification-{VERSION}.json'
target.write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'identity':identity,'passed_reports':len(reports),'fold_checks_per_binary':len(reports['portable_fold']['checks']),'report':str(target)},ensure_ascii=False))
