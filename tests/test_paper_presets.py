import tempfile,unittest
from pathlib import Path
from illusive_print.paper_presets import PaperStore


class PaperPresetTests(unittest.TestCase):
    def test_persistence_identity_and_size_snapshot(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'papers.json';store=PaperStore(path)
            p=store.put('Меловка',330,488);snapshot=(p.width,p.height)
            p2=store.put('Другой тираж',320,450,p.identifier)
            self.assertEqual(PaperStore(path).presets[p.identifier],p2)
            self.assertEqual(snapshot,(330,488))
            duplicate=store.duplicate(p.identifier)
            self.assertNotEqual(duplicate.identifier,p.identifier)
            store.delete(p.identifier)
            self.assertEqual(snapshot,(330,488))
            self.assertIn(duplicate.identifier,PaperStore(path).presets)

    def test_invalid_format_rejected_before_writing(self):
        with tempfile.TemporaryDirectory() as folder:
            store=PaperStore(Path(folder)/'papers.json')
            for name,w,h in (('',1,1),('x',0,1),('x',1,-2),('x',2001,1),('x',float('nan'),1)):
                with self.assertRaises(ValueError):store.put(name,w,h)
            self.assertFalse(store.presets)
