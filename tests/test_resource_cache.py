from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from PIL import Image
from illusive_print.disk_cache import DiskCache
from illusive_print.image_cache import ImageCache
from illusive_print.resources import ResourceManager, Memory, MiB, GiB


class ResourceCacheTests(unittest.TestCase):
    def test_automatic_budgets_pressure_reservations_and_recovery(self):
        manager=ResourceManager();manager.caches=(ImageCache(1),ImageCache(1))
        with patch('illusive_print.resources.memory_snapshot',return_value=Memory(32*GiB,20*GiB,GiB)):
            manager.refresh(True)
            large=sum(c.budget for c in manager.caches)
            self.assertGreater(large,GiB)
            with manager.working(18*GiB):self.assertLess(sum(c.budget for c in manager.caches),large)
            self.assertEqual(manager.reserved,0)
        with patch('illusive_print.resources.memory_snapshot',return_value=Memory(8*GiB,512*MiB,2*GiB)):
            manager.refresh(True);budget=sum(c.budget for c in manager.caches)
            manager.refresh(True);self.assertEqual(sum(c.budget for c in manager.caches),budget)
            self.assertLessEqual(budget,64*MiB)

    def test_disk_commit_corruption_recovery_invalidation_and_eviction(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);cache=DiskCache(root/'cache');source=root/'source';source.write_bytes(b'%PDF-fixture')
            key=cache.key(('source-hash','params','converter','fonts'))
            path=cache.publish(key,'.pdf',source,['notice'])
            result=cache.get(key,'.pdf');self.assertEqual(result,(path,['notice']))
            path.write_bytes(b'bad');self.assertIsNone(cache.get(key,'.pdf'))
            cache.publish(key,'.pdf',source)
            path.with_suffix('.pdf.json').unlink();self.assertIsNone(cache.get(key,'.pdf'))
            cache.publish(key,'.pdf',source)
            other=cache.key(('changed-fonts',));self.assertIsNone(cache.get(other,'.pdf'))
            cache.pinned.clear()
            with patch('illusive_print.disk_cache.disk_budget',return_value=0):cache.prune(True)
            self.assertFalse(path.exists());self.assertGreater(cache.evictions,0)
