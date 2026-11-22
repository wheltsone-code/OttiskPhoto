# Share analysis, dependencies, icon and version with the portable build.
from pathlib import Path

source = Path(SPECPATH, 'OttiskPhoto.spec').read_text(encoding='utf-8')
source = source[:source.index('exe = EXE(')]
exec(compile(source, 'OttiskPhoto.spec', 'exec'))
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='OttiskPhoto',
          console=False, icon=['assets/logo.ico'], version='tools/version_info.txt')
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='OttiskPhoto')
