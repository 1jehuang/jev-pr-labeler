"""Conservative policy separate from model inference."""
import json
from pathlib import PurePosixPath

MAX_STATE_BYTES = 40_000


def incidental(path):
    parts = PurePosixPath(path).parts
    name = PurePosixPath(path).name
    return (name in {"Cargo.lock", "package-lock.json", "yarn.lock", "pnpm-lock.yaml",
                     "uv.lock", "poetry.lock", "bun.lock", "bun.lockb"}
            or any(p in {"vendor", "vendored", "node_modules", "generated"} for p in parts)
            or name.endswith((".min.js", ".min.css", ".generated.rs", ".generated.ts")))


def snapshot(pr, files):
    if pr["state"] != "open":
        raise ValueError("PR is not open; no classification performed.")
    if len(files) != pr["changed_files"]:
        raise ValueError("Incomplete GitHub file list; no labels changed.")
    state = {"title": pr["title"], "description": pr.get("body") or "", "files": []}
    for file in files:
        item = {key: file[key] for key in ("filename", "previous_filename", "status") if key in file}
        if incidental(file["filename"]) and incidental(file.get("previous_filename", file["filename"])):
            item["note"] = "Lockfile/generated/vendor patch omitted; do not infer large scope from its volume."
        else:
            patch = file.get("patch")
            if not patch and (file.get("additions", 0) or file.get("deletions", 0)):
                raise ValueError("A substantive patch is unavailable (binary/large diff); manual labeling required.")
            # GitHub can silently truncate a patch. Hunk headers/context do not count.
            if patch:
                added = sum(line.startswith("+") for line in patch.splitlines())
                deleted = sum(line.startswith("-") for line in patch.splitlines())
                if added != file.get("additions", 0) or deleted != file.get("deletions", 0):
                    raise ValueError("GitHub returned a truncated patch; manual labeling required.")
            item["patch"] = patch or "No textual content changed (rename, mode change, or binary metadata)."
        state["files"].append(item)
    if len(json.dumps(state, ensure_ascii=True).encode()) > MAX_STATE_BYTES:
        raise ValueError("PR exceeds bounded model context; manual labeling required, not a size guess.")
    return state


def plan_labels(decisions, current, owned):
    """Replace only this bot's labels. Human-applied exclusive labels win."""
    additions, removals = set(), set()
    for question, decision in decisions.items():
        if not decision["decisive"]:
            continue
        desired = set(decision["labels"])
        if question in {"type", "size"}:
            group = {label for label in current if label.startswith(question + ": ")}
            if group - owned:
                continue
            additions.update(desired - current)
            removals.update((group & owned) - desired)
        else:
            additions.update(desired - current)
            if question not in {"security", "breaking-change"} and not desired and question in owned:
                removals.add(question)
    return sorted(additions), sorted(removals)
