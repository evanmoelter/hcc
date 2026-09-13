import json
import re
import subprocess
import sys


def main():
    try:
        result = subprocess.run(
            [
                "restic", "--no-lock", "--no-cache", "snapshots", "--json",
                "--host", "volsync", "--path", "/data",
            ],
            check=True, capture_output=True, text=True, timeout=240,
        )
        snapshots = json.loads(result.stdout)
        if not isinstance(snapshots, list) or not any(
            isinstance(snapshot, dict)
            and re.fullmatch(r"[0-9a-f]{64}", snapshot.get("id", ""))
            and snapshot.get("hostname") == "volsync"
            and "/data" in snapshot.get("paths", [])
            for snapshot in snapshots
        ):
            raise ValueError("No compatible backup")
    except (OSError, subprocess.SubprocessError, ValueError, TypeError):
        print("Restore blocked: could not confirm an existing VolSync backup.", file=sys.stderr)
        return 1
    print("Existing VolSync backup confirmed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
