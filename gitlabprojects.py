#!/usr/bin/env python3
import sys, os, requests
from concurrent.futures import ThreadPoolExecutor, as_completed

if len(sys.argv) != 3:
    print(f"Usage: {sys.argv[0]} <token> <username>")
    sys.exit(1)

token, username = sys.argv[1], sys.argv[2]
base = f"{os.environ.get('GITLAB_URL', 'https://gitlab.com')}/api/v4"
headers = {"PRIVATE-TOKEN": token}
session = requests.Session()
session.headers.update(headers)


def fetch_page(url, params, page):
    p = {**params, "page": page}
    r = session.get(url, params=p, timeout=30)
    r.raise_for_status()
    return page, r.json()


def get_all_pages(url, params):
    MAX_PAGES = 200  # speculative upper bound
    results = []
    with ThreadPoolExecutor(max_workers=20) as pool:
        futures = {pool.submit(fetch_page, url, params, p): p for p in range(1, MAX_PAGES + 1)}
        for future in as_completed(futures):
            pg, data = future.result()
            if data:
                print(f"  page {pg} ({len(data)} items)", file=sys.stderr)
                results.extend(data)
    return results


def has_user_commits(project_id):
    """Check if the user has any commits in this project."""
    r = session.get(f"{base}/projects/{project_id}/repository/commits",
                    params={"author": username, "per_page": 1}, timeout=10)
    if r.status_code == 200 and r.json():
        return True
    # Also try with email-style matching
    r = session.get(f"{base}/projects/{project_id}/repository/commits",
                    params={"all": "true", "per_page": 1, "author": username}, timeout=10)
    return r.status_code == 200 and bool(r.json())


# Step 1: Get all projects user is a member of (includes owned)
print("Fetching membership projects...", file=sys.stderr)
all_projects = get_all_pages(f"{base}/projects", {"membership": "true", "per_page": 100, "simple": "true"})
print(f"\nTotal membership projects: {len(all_projects)}", file=sys.stderr)

# Step 2: Check each project for user's commits (parallel)
print("Checking for your commits (this may take a while)...", file=sys.stderr)
committed = []
checked = 0
with ThreadPoolExecutor(max_workers=20) as pool:
    futures = {pool.submit(has_user_commits, p["id"]): p for p in all_projects}
    for future in as_completed(futures):
        checked += 1
        p = futures[future]
        try:
            if future.result():
                committed.append(p)
                print(f"  [{checked}/{len(all_projects)}] ✓ {p['path_with_namespace']}", file=sys.stderr)
            else:
                print(f"  [{checked}/{len(all_projects)}]   {p['path_with_namespace']}", file=sys.stderr)
        except Exception as e:
            print(f"  [{checked}/{len(all_projects)}] ! {p['path_with_namespace']}: {e}", file=sys.stderr)

print(f"\nProjects you've committed to: {len(committed)}", file=sys.stderr)

committed.sort(key=lambda p: p.get("last_activity_at", ""), reverse=True)

import csv
outfile = f"gitlab_committed_{username}.csv"
with open(outfile, "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["last_activity", "project", "url"])
    for p in committed:
        w.writerow([p["last_activity_at"], p["path_with_namespace"], p["web_url"]])

print(f"Saved to {outfile}", file=sys.stderr)
