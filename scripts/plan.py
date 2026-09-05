#!/usr/bin/env python3
"""Decide which PHP builds are missing and need making.

    scripts/plan.py <owner/repo> [--only 8.4] [--force]

Asks php.net for the newest patch of every minor in versions.txt, then drops
the ones already published here. Prints the build matrix as JSON. PHP patches
land on a schedule nobody here controls, so the build is driven by what is
released rather than by someone remembering to tag.
"""
import json, os, pathlib, sys, urllib.error, urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
API = "https://www.php.net/releases/index.php?json&version=%s&max=1"


def latest_patch(minor):
    """The newest published patch of a minor, or None if php.net has none."""
    with urllib.request.urlopen(API % minor, timeout=30) as r:
        data = json.load(r)
    # Keyed by the full version; a minor with no GA release answers with {}.
    return next(iter(data), None)


def already_published(repo, tag, token):
    req = urllib.request.Request(
        "https://api.github.com/repos/%s/releases/tags/%s" % (repo, tag),
        headers={"Accept": "application/vnd.github+json",
                 **({"Authorization": "Bearer " + token} if token else {})})
    try:
        urllib.request.urlopen(req, timeout=30).read()
        return True
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return False
        raise


def main():
    repo = sys.argv[1]
    only = None
    force = "--force" in sys.argv
    if "--only" in sys.argv:
        only = sys.argv[sys.argv.index("--only") + 1]

    minors = [l.strip() for l in (ROOT / "versions.txt").read_text().splitlines()
              if l.strip() and not l.startswith("#")]
    if only:
        if only not in minors:
            sys.exit("plan.py: %s is not in versions.txt" % only)
        minors = [only]

    token = os.environ.get("GITHUB_TOKEN", "")
    builds = []
    for minor in minors:
        patch = latest_patch(minor)
        if not patch:
            print("plan.py: php.net publishes no release for %s" % minor, file=sys.stderr)
            continue
        tag = "php-" + patch
        if not force and already_published(repo, tag, token):
            print("plan.py: %s already published" % tag, file=sys.stderr)
            continue
        builds.append({"minor": minor, "patch": patch, "tag": tag})
    print(json.dumps(builds))


if __name__ == "__main__":
    main()
