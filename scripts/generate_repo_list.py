#!/usr/bin/env python3
"""Generate datas/RepoList.json and datas/RepoStar.json for the meta repo."""

import base64
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

API = "https://api.github.com"
TOKEN = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
OWNER = os.environ.get("REPO_OWNER")

DATAS_DIR = Path("datas")
CONFIG_FILE = DATAS_DIR / "star-config.json"

HEADING_RE = re.compile(r"^#\s+(.+?)\s*#*\s*$")


def api_get(url: str):
    req = urllib.request.Request(url)
    if TOKEN:
        req.add_header("Authorization", f"Bearer {TOKEN}")
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    req.add_header("User-Agent", "repo-list-generator")
    try:
        with urllib.request.urlopen(req) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        print(f"[warn] {url} -> HTTP {e.code}", file=sys.stderr)
        return None
    except Exception as e:  # noqa: BLE001
        print(f"[warn] {url} -> {e}", file=sys.stderr)
        return None


def list_user_repos(owner: str):
    repos, page = [], 1
    while True:
        data = api_get(
            f"{API}/users/{owner}/repos?per_page=100&page={page}&sort=updated"
        )
        if not data:
            break
        repos.extend(data)
        if len(data) < 100:
            break
        page += 1
    return repos


def read_readme_title(owner: str, repo_name: str):
    """Return the first level-1 heading of the repo README, or None."""
    data = api_get(f"{API}/repos/{owner}/{repo_name}/readme")
    if not data or "content" not in data:
        return None
    try:
        content = base64.b64decode(data["content"]).decode("utf-8", errors="ignore")
    except Exception:  # noqa: BLE001
        return None

    in_code_block = False
    for raw in content.splitlines():
        line = raw.rstrip()
        if line.lstrip().startswith("```"):
            in_code_block = not in_code_block
            continue
        if in_code_block:
            continue
        m = HEADING_RE.match(line)
        if m:
            return m.group(1).strip()
    return None


def read_languages(owner: str, repo_name: str):
    data = api_get(f"{API}/repos/{owner}/{repo_name}/languages")
    if not data:
        return []
    # Sort by bytes desc so the primary language comes first
    return [k for k, _ in sorted(data.items(), key=lambda kv: kv[1], reverse=True)]


def build_entry(owner: str, repo: dict) -> dict:
    repo_name = repo["name"]
    title = read_readme_title(owner, repo_name)
    langs = read_languages(owner, repo_name)
    return {
        "id": str(repo["id"]),
        "name": title or repo_name,
        "full_name": repo["full_name"],
        "url": repo.get("homepage") or "",
        "repo": repo["html_url"],
        "desc": repo.get("description") or "",
        "stars": repo.get("stargazers_count", 0),
        "tags": langs,
    }


def load_selected():
    """Read datas/star-config.json to know which repos to feature.

    Accepts either:
        ["repo-a", "repo-b"]
    or:
        {"repos": ["owner/repo-a", "repo-b"]}
    Returns a set of repo short names, or None (meaning: feature everything).
    """
    if not CONFIG_FILE.exists():
        return None
    with CONFIG_FILE.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict):
        data = data.get("repos", [])
    if not isinstance(data, list):
        raise ValueError('star-config.json must be a list or {"repos": [...]}')
    return {str(item).split("/")[-1] for item in data}


def main() -> None:
    if not OWNER:
        print("REPO_OWNER is not set", file=sys.stderr)
        sys.exit(1)

    DATAS_DIR.mkdir(parents=True, exist_ok=True)

    repos = [
        r
        for r in list_user_repos(OWNER)
        if not r.get("fork") and not r.get("archived")
    ]

    entries = [build_entry(OWNER, r) for r in repos]
    entries.sort(key=lambda e: (-e["stars"], e["name"].lower()))

    selected = load_selected()
    if selected is None:
        starred = entries
    else:
        starred = [e for e in entries if e["full_name"].split("/")[-1] in selected]

    for fname, payload in (("RepoList.json", entries), ("RepoStar.json", starred)):
        with (DATAS_DIR / fname).open("w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
            f.write("\n")

    print(f"RepoList.json: {len(entries)} repos | RepoStar.json: {len(starred)} repos")


if __name__ == "__main__":
    main()