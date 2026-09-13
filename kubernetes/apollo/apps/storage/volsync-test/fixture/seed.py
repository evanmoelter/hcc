from pathlib import Path
import os

root = Path("/data")
(root / "nested").mkdir(exist_ok=True)
(root / "message.txt").write_bytes(b"Apollo VolSync restore verification v1\n")
(root / "nested/payload.bin").write_bytes(bytes(range(256)) * 1024)
(root / "message.txt").chmod(0o600)
os.sync()
print("Test files written and flushed.")
