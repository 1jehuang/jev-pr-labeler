"""GitHub metadata only: no cloning, PR code execution, or PR-controlled URLs."""
import re
from urllib.parse import quote
from .transport import request_json


class GitHub:
    def __init__(self, repository, token):
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
            raise ValueError("Repository must be owner/name.")
        self.repository, self.token = repository, token
        self.root = f"https://api.github.com/repos/{repository}"

    def request(self, path, method="GET", body=None):
        return request_json(self.root + path, self.token, method, body)

    def pages(self, path, max_pages=30):
        result = []
        for page in range(1, max_pages + 1):
            batch = self.request(f"{path}?per_page=100&page={page}")
            if not isinstance(batch, list):
                raise RuntimeError("Expected a GitHub list response.")
            result.extend(batch)
            if len(batch) < 100:
                return result
        raise RuntimeError("GitHub pagination limit reached; refusing a partial snapshot.")

    def pull(self, number):
        if isinstance(number, bool) or not isinstance(number, int) or number <= 0:
            raise ValueError("PR number must be a positive integer.")
        return self.request(f"/pulls/{number}")

    def files(self, number):
        return self.pages(f"/pulls/{number}/files")

    def owned_labels(self, number, actor):
        # The latest event for a current label records who last applied it.
        owners = {}
        for event in self.pages(f"/issues/{number}/events"):
            name = (event.get("label") or {}).get("name")
            if event.get("event") == "labeled":
                owners[name] = (event.get("actor") or {}).get("login")
            elif event.get("event") == "unlabeled":
                owners.pop(name, None)
        return {name for name, login in owners.items() if login == actor}

    def ensure_labels(self, labels):
        existing = {item["name"].casefold() for item in self.pages("/labels")}
        for name, properties in labels.items():
            if name.casefold() not in existing:
                self.request("/labels", "POST", {"name": name, **properties})

    def apply(self, number, additions, removals):
        if additions:
            self.request(f"/issues/{number}/labels", "POST", {"labels": sorted(additions)})
        for label in sorted(removals):
            self.request(f"/issues/{number}/labels/{quote(label, safe='')}", "DELETE")


def fingerprint(pr):
    return (pr["head"]["sha"], pr["base"]["sha"], pr["title"], pr.get("body"),
            pr["state"], tuple(sorted(label["name"] for label in pr["labels"])))
