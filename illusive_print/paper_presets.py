"""Stable paper identities and immutable size snapshots for existing work."""
from dataclasses import dataclass,asdict
import json,math,os,tempfile
from pathlib import Path
from uuid import uuid4


@dataclass(frozen=True)
class PaperPreset:
    identifier:str
    name:str
    width:float
    height:float

    def validate(self):
        if not self.name.strip():raise ValueError('Введите название формата.')
        if any(not math.isfinite(v) or not 1<=v<=2000 for v in (self.width,self.height)):
            raise ValueError('Размеры листа должны быть от 1 до 2000 мм — предел текущего пути вывода.')


class PaperStore:
    def __init__(self,path=None):
        if path is None:
            from .i18n import preferences_path
            path=preferences_path().with_name('paper-formats.json')
        self.path=Path(path);self.presets={}
        try:
            for data in json.loads(self.path.read_text(encoding='utf8')).get('papers',[]):
                p=PaperPreset(**data);p.validate();self.presets[p.identifier]=p
        except FileNotFoundError:pass
        except (ValueError,TypeError,KeyError) as error:
            from .diagnostics import record
            record('paper_presets.invalid',error=str(error))

    def save(self):
        self.path.parent.mkdir(parents=True,exist_ok=True)
        fd,name=tempfile.mkstemp(prefix='.papers-',dir=self.path.parent,suffix='.json')
        try:
            with os.fdopen(fd,'w',encoding='utf8') as stream:
                json.dump({'version':1,'papers':[asdict(p) for p in self.presets.values()]},stream,ensure_ascii=False,indent=2)
            os.replace(name,self.path)
        finally:Path(name).unlink(missing_ok=True)

    def put(self,name,width,height,identifier=None):
        p=PaperPreset(identifier or 'paper:'+uuid4().hex,name.strip(),float(width),float(height));p.validate()
        previous=dict(self.presets);self.presets[p.identifier]=p
        try:self.save()
        except OSError:self.presets=previous;raise
        return p

    def delete(self,identifier):
        previous=dict(self.presets);del self.presets[identifier]
        try:self.save()
        except OSError:self.presets=previous;raise

    def duplicate(self,identifier):
        p=self.presets[identifier]
        return self.put(p.name+' — копия',p.width,p.height)
