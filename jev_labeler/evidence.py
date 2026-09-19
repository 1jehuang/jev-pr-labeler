"""Bounded Jev evidence classification, with lossless excerpts and lossy reduction.

Hierarchical decisions are intentionally conservative. Callers MUST disable all
label removals when metadata['strategy'] == 'hierarchical'. Limits are safety
budgets, never evidence of semantic PR size. Offsets count Python characters,
not bytes, and index the original patch with an exclusive end.
"""

import hashlib
import json
import math

from .classifier import MODEL, build_request, parse_response
from .transport import request_json

STATE_LIMIT = 40_000
REQUEST_LIMIT = 80_000
MAX_CHUNKS = 64
ENDPOINT = "https://openrouter.ai/api/alpha/decisions"


class EvidenceBudgetError(ValueError):
    """Local evidence exceeds a state, wire, or chunk-count safety budget."""

_EXCERPT = (
    " This is a partial PR excerpt. Classify this excerpt only, not the whole PR. "
    "Title and description are context, not proof of changes absent from this excerpt. "
    "For type and size describe only the excerpt's semantic purpose and complexity, "
    "never guess whole PR size from partial evidence. Partial patches may lack context: "
    "choose unknown rather than assuming omitted code. Never infer size from byte, "
    "character, line, file or chunk counts."
)
_REDUCTION = (
    " This is explicitly lossy hierarchical evidence, not the original full diff. "
    "Every chunk's complete typed decision summary and file provenance is supplied. "
    "Reason about semantic scope and complexity, never byte, character, line, file "
    "or chunk counts. Unknown or non-decisive excerpts remain uncertain, not negative. "
    "Binary yes requires at least one decisive yes for that question in a chunk. "
    "Do not make negative/removal claims from mixed or unknown chunks. Primary type "
    "requires at least one decisive matching excerpt; supporting docs/tests may differ. "
    "Estimate whole-PR size only when every excerpt has a decisive semantic-size "
    "result and the evidence supports reasoning about combined semantic interactions. "
    "Choose unknown when interactions cannot be inferred from these lossy summaries. "
    "Never sum, maximize, vote on or count excerpt sizes to determine global size. "
    "The size is a lossy informational estimate, not calibrated global correctness. "
    "Title, description and review cannot replace missing affirmative diff evidence."
)


def _wire_size(request):
    # Match transport.request_json's serialization, including nested-state escaping.
    return len(json.dumps(request, allow_nan=False).encode())


def _request(state, instructions=""):
    request = build_request(state)
    for question in request["questions"].values():
        question["instructions"] += instructions
    return request


def _fits(request):
    return len(request["state"].encode("utf-8")) <= STATE_LIMIT and _wire_size(request) <= REQUEST_LIMIT


def _check(request):
    if not _fits(request):
        raise EvidenceBudgetError("Evidence exceeds state or request safety budget")


def _unknown_response(request):
    return {"answers": {
        key: {"type": "choice", "choice": "unknown", "confidence": 1.0,
              "probabilities": {choice: float(choice == "unknown")
                                for choice in question["criteria"]}}
        for key, question in request["questions"].items()
    }}


def _chunks(state):
    allowed = {"title", "description", "files", "completed_greptile_review"}
    if state.keys() - allowed:
        raise ValueError("Unsupported hierarchical evidence fields")
    if not all(isinstance(state.get(key), str) for key in ("title", "description")):
        raise ValueError("Hierarchical title and description must be strings")
    if not isinstance(state.get("files"), list):
        raise ValueError("Hierarchical files must be a list")
    base = {"title": state["title"], "description": state["description"],
            "evidence_context": "partial PR excerpt; offsets are original patch characters"}
    chunks = []
    current = []

    def request(files):
        return _request({**base, "files": files}, _EXCERPT)

    def flush():
        if len(chunks) >= MAX_CHUNKS:
            raise EvidenceBudgetError("Evidence exceeds maximum chunk count")
        body = request(current)
        _check(body)
        chunks.append(body)
        current.clear()

    _check(request([]))
    for index, file in enumerate(state["files"]):
        if (not isinstance(file, dict)
                or file.keys() - {"filename", "previous_filename", "status", "patch", "note"}
                or not all(isinstance(file.get(key), str) for key in ("filename", "status"))
                or not ("patch" in file or "note" in file)
                or any(not isinstance(file[key], str)
                       for key in ("patch", "note", "previous_filename") if key in file)):
            raise ValueError("Invalid hierarchical file evidence")
        patch = file.get("patch")

        def fragment(start, end):
            item = dict(file)
            provenance = {"file_index": index}
            if patch is not None:
                item["patch"] = patch[start:end]
                provenance.update({"patch_start": start, "patch_end": end,
                                   "patch_length": len(patch), "offset_unit": "unicode_characters",
                                   "partial": start != 0 or end != len(patch),
                                   "starts_mid_line": start > 0 and patch[start - 1] != "\n",
                                   "ends_mid_line": end < len(patch) and end > 0 and patch[end - 1] != "\n"})
            item["provenance"] = provenance
            return item

        end = len(patch) if patch is not None else 0
        whole = fragment(0, end)
        if _fits(request(current + [whole])):
            current.append(whole)
            continue
        if current:
            flush()
        if _fits(request([whole])):
            current.append(whole)
            continue
        if not patch:
            raise EvidenceBudgetError("File metadata exceeds evidence budget")
        start = 0
        while start < len(patch):
            # Binary search on actual serialized sizes handles unicode and escaping.
            low, high = start, len(patch)
            while low < high:
                middle = (low + high + 1) // 2
                if _fits(request([fragment(start, middle)])):
                    low = middle
                else:
                    high = middle - 1
            end = low
            if end == start:
                raise EvidenceBudgetError("File metadata exceeds evidence budget")
            if end < len(patch):
                newline = patch.rfind("\n", start, end)
                if newline >= start:
                    end = newline + 1
            current.append(fragment(start, end))
            flush()
            start = end
    if current or not chunks:
        flush()
    return chunks


def _provenance(request):
    return [{key: file[key] for key in ("filename", "previous_filename", "status", "provenance")
             if key in file}
            for file in json.loads(request["state"])["files"]]


def _summary(decisions):
    return {key: {"type": "choice", "choice": value["choice"],
                  "confidence": value["confidence"], "decisive": value["decisive"]}
            for key, value in decisions.items()}


def _reduction(state, chunks, summaries):
    evidence = {"title": state["title"], "description": state["description"],
                "lossy_hierarchical_evidence": True,
                "chunks": [{"chunk_index": index, "files": _provenance(chunk),
                            "decisions": summary}
                           for index, (chunk, summary) in enumerate(zip(chunks, summaries))]}
    if "completed_greptile_review" in state:
        evidence["completed_greptile_review"] = state["completed_greptile_review"]
    return _request(evidence, _REDUCTION)


def _usage(responses):
    """Sum finite numeric usage leaves, ignoring provider nonnumeric annotations."""
    result = {}

    def merge(target, source):
        if not isinstance(source, dict):
            return
        for key, value in source.items():
            if isinstance(value, dict):
                if key not in target:
                    target[key] = {}
                if isinstance(target[key], dict):
                    merge(target[key], value)
            elif isinstance(value, (int, float)) and not isinstance(value, bool):
                try:
                    finite = math.isfinite(value)
                except OverflowError:
                    finite = False
                if not finite or value < 0:
                    raise ValueError("Invalid provider usage")
                if not isinstance(target.get(key), dict):
                    total = target.get(key, 0) + value
                    if not math.isfinite(total):
                        raise ValueError("Invalid aggregate usage")
                    target[key] = total

    for response in responses:
        merge(result, response.get("usage"))
    return result


def classify(state, key, threshold=0.75):
    """Return (parsed decisions, metadata), or raise ValueError without partial results.

    Small states (build_request's JSON state <=40,000 UTF-8 bytes) use the original
    request unchanged, subject to the 80,000-byte ASCII JSON wire budget. Large
    states are preflighted before network access, including a conservative upper
    bound on reduction size. Hierarchical size requires all excerpt sizes decisive
    plus a decisive semantic reduction. It is a lossy informational estimate, not
    calibrated global correctness. Primary type and binary yes need at least one
    decisive matching excerpt. All final confidences are capped by their support.
    Metadata contains strategy, chunks (count), model, aggregated usage, lossy,
    and source_content_hash (SHA-256 of build_request's original JSON state).
    """
    original = build_request(state)
    # Reuse the existing finite/unit interval validator before any network calls.
    parse_response(_unknown_response(original), original, threshold)
    content_hash = hashlib.sha256(original["state"].encode()).hexdigest()
    responses = []

    def call(request):
        _check(request)
        response = request_json(ENDPOINT, key, "POST", request, limit=256_000)
        decisions = parse_response(response, request, threshold)
        responses.append(response)
        return decisions

    hierarchical = len(original["state"].encode("utf-8")) > STATE_LIMIT
    if not hierarchical:
        decisions = call(original)
        count = 1
    else:
        chunks = _chunks(state)
        # Every normalized field has a known bound. A 32-character string is
        # longer on the wire than any finite 0..1 float's JSON representation.
        worst = {name: {"type": "choice", "choice": max(q["criteria"], key=len),
                        "confidence": "9" * 32, "decisive": False}
                 for name, q in original["questions"].items()}
        _check(_reduction(state, chunks, [worst] * len(chunks)))
        results = [call(chunk) for chunk in chunks]
        reduction = _reduction(state, chunks, [_summary(result) for result in results])
        decisions = call(reduction)
        for name, decision in decisions.items():
            supporting = [result[name] for result in results]
            if name == "size":
                supported = decision["decisive"] and all(item["decisive"] for item in supporting)
            elif name == "type":
                supported = decision["decisive"] and any(
                    item["decisive"] and item["choice"] == decision["choice"] for item in supporting)
            else:
                # No hierarchical negative can authorize removal, even unanimous.
                supported = decision["choice"] == "yes" and any(
                    item["decisive"] and item["choice"] == "yes" for item in supporting)
            if not supported:
                decisions[name] = {"choice": "unknown", "confidence": 0.0,
                                   "labels": [], "decisive": False}
            else:
                if name == "size":
                    # Include ALL excerpt sizes, not just choices matching the reducer.
                    support_confidence = min(item["confidence"] for item in supporting)
                else:
                    support_confidence = max(item["confidence"] for item in supporting
                                             if item["decisive"] and item["choice"] == decision["choice"])
                decision["confidence"] = min(decision["confidence"], support_confidence)
        count = len(chunks)
    return decisions, {"strategy": "hierarchical" if hierarchical else "direct",
                       "chunks": count, "model": responses[-1].get("model", MODEL),
                       "usage": _usage(responses), "lossy": hierarchical,
                       "source_content_hash": content_hash}
