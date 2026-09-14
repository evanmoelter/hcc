import html
import re
import sys
from pathlib import Path


def summarize_diff(diff: str) -> dict[str, list[int]]:
    resources = {}
    resource = None
    old_header = None
    remaining_old = remaining_new = 0

    for line in diff.splitlines():
        if line == r"\ No newline at end of file":
            continue
        if remaining_old or remaining_new:
            if line.startswith("+"):
                resources[resource][0] += 1
                remaining_new -= 1
            elif line.startswith("-"):
                resources[resource][1] += 1
                remaining_old -= 1
            elif line.startswith(" "):
                remaining_old -= 1
                remaining_new -= 1
            else:
                raise ValueError(f"Invalid diff hunk line: {line!r}")
            if remaining_old < 0 or remaining_new < 0:
                raise ValueError("Diff hunk exceeds its declared line counts")
        elif line.startswith("--- "):
            old_header = line[4:]
            resource = None
        elif line.startswith("+++ ") and old_header is not None:
            resource = old_header if line[4:] == "/dev/null" else line[4:]
            resources.setdefault(resource, [0, 0])
            old_header = None
        elif match := re.fullmatch(r"@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@.*", line):
            if resource is None:
                raise ValueError("Diff hunk has no resource header")
            remaining_old = int(match[2] or 1)
            remaining_new = int(match[4] or 1)
        elif line.strip():
            raise ValueError(f"Unrecognized diff line: {line!r}")

    if remaining_old or remaining_new or old_header is not None:
        raise ValueError("Incomplete diff")
    return resources


def format_diff(diff: str) -> str:
    resources = summarize_diff(diff)
    lines = ["### apollo changes", ""]
    if not resources:
        return "\n".join([*lines, "No rendered resource changes.", ""])

    lines.extend(["| Resource | Added | Removed |", "| --- | ---: | ---: |"])
    for resource, (added, removed) in resources.items():
        label = html.escape(resource).replace("|", "&#124;")
        lines.append(f"| {label} | +{added} | −{removed} |")
    added = sum(counts[0] for counts in resources.values())
    removed = sum(counts[1] for counts in resources.values())
    lines.append(f"| **Total ({len(resources)} resources)** | **+{added}** | **−{removed}** |")
    fence = "`" * max(3, 1 + max((len(run) for run in re.findall(r"`+", diff)), default=0))
    lines.extend(["", "<details>", "<summary>Show full diff</summary>", "", f"{fence}diff"])
    return "\n".join(lines) + "\n" + diff.rstrip("\n") + f"\n{fence}\n\n</details>\n"


if __name__ == "__main__":
    print(format_diff(Path(sys.argv[1]).read_text()), end="")
