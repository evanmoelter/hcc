import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "kubernetes/apollo/apps/default/paperless/consume-monitor/monitor.py"
SPEC = importlib.util.spec_from_file_location("consume_monitor", SCRIPT)
monitor = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(monitor)


class ConsumeMonitorTest(unittest.TestCase):
    def test_empty_seeded_volume_does_not_alert(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / '._volsync').touch()
            (root / 'receipt').mkdir()
            (root / 'lost+found').mkdir()
            (root / 'lost+found/ignored').touch()
            self.assertEqual(monitor.consume_status(root, now=10000),
                             {'files': 0, 'oldest_age_seconds': 0})

    def test_recursive_oldest_file_and_recovery_after_consumption(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'receipt').mkdir()
            old = root / 'receipt/stuck.pdf'
            new = root / 'new.pdf'
            old.touch()
            new.touch()
            os.utime(old, (5000, 5000))
            os.utime(new, (9990, 9990))
            self.assertEqual(monitor.consume_status(root, now=10000),
                             {'files': 2, 'oldest_age_seconds': 5000})
            old.unlink()
            self.assertEqual(monitor.consume_status(root, now=10000),
                             {'files': 1, 'oldest_age_seconds': 10})

    def test_symlinks_do_not_escape_the_consume_mount(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'loop').symlink_to(root, target_is_directory=True)
            (root / 'outside').symlink_to(SCRIPT)
            self.assertEqual(monitor.consume_status(root, now=10000)['files'], 0)

    def test_missing_mount_is_an_error(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(FileNotFoundError):
                monitor.consume_status(Path(directory) / 'missing')

    def request(self, path):
        handler = object.__new__(monitor.Handler)
        handler.path = path
        handler.wfile = io.BytesIO()
        statuses = []
        handler.send_response = statuses.append
        handler.send_header = lambda *args: None
        handler.end_headers = lambda: None
        handler.do_GET()
        return statuses[0], json.loads(handler.wfile.getvalue())

    def test_permission_failure_returns_failure_without_private_paths(self):
        with patch.object(monitor, 'consume_status', side_effect=PermissionError('private filename')):
            self.assertEqual(self.request('/status'), (503, {'error': 'consume scan failed'}))
            self.assertEqual(self.request('/healthz'), (200, {'healthy': True}))

    def test_success_returns_only_aggregate_values(self):
        status = {'files': 2, 'oldest_age_seconds': 5000}
        with patch.object(monitor, 'consume_status', return_value=status):
            self.assertEqual(self.request('/status'), (200, status))
        self.assertEqual(self.request('/other'), (404, {'error': 'not found'}))


if __name__ == '__main__':
    unittest.main()
