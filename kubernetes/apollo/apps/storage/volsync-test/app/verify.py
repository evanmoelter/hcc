import hashlib
from pathlib import Path

root = Path("/data")
expected = {
    "message.txt": hashlib.sha256(b"Apollo VolSync restore verification v1\n").hexdigest(),
    "nested/payload.bin": hashlib.sha256(bytes(range(256)) * 1024).hexdigest(),
}
for name, digest in expected.items():
    path = root / name
    if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
        raise SystemExit("Restored file checksum mismatch.")
    if path.stat().st_uid != 568:
        raise SystemExit("Restored file ownership mismatch.")
if (root / "message.txt").stat().st_mode & 0o777 != 0o600:
    raise SystemExit("Restored file permissions mismatch.")
print("Restore verified: both file checksums, ownership, and private-file permissions match.")
