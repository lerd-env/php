#!/usr/bin/env python3
"""Decide which PHP builds are missing and need making.

    scripts/plan.py <owner/repo> [--only 8.4] [--force] [--skip-windows]

Asks php.net for the newest patch of every minor in versions.txt, then drops
the ones already published here. PHP patches land on a schedule nobody here
controls, so the build is driven by what is released rather than by someone
remembering to tag.

Prints {"macos": [...], "windows": [...], "releases": [...]}: the builds each
platform still needs, and every release tag either of them will publish to.
They are planned apart because windows.php.net publishes its build hours after
php.net announces a patch: a run that catches the gap ships macOS alone, and a
later run adds the Windows asset to the same release.
"""
import json, os, pathlib, sys, time, urllib.error, urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
API = "https://www.php.net/releases/index.php?json&version=%s&max=1"
WINDOWS_RELEASES = "https://downloads.php.net/~windows/releases/releases.json"


def latest_patch(minor):
    """The newest published patch of a minor, or None.

    None also covers php.net being unreachable. This runs unattended every
    week, and one slow answer used to abort the whole run, so a minor nobody
    could ask about is left at whatever is already published rather than
    taking the other four down with it.
    """
    for attempt in range(3):
        try:
            with urllib.request.urlopen(API % minor, timeout=30) as r:
                data = json.load(r)
            # Keyed by the full version; a minor with no GA release gives {}.
            return next(iter(data), None)
        except Exception as e:  # network, timeout, or a body that is not JSON
            if attempt == 2:
                print("plan.py: php.net did not answer for %s (%s)" % (minor, e), file=sys.stderr)
                return None
            time.sleep(3)
    return None


def version_key(v):
    return tuple(int(n) for n in v.split("."))


def newest_published(repo, minor, token):
    """The highest patch of a minor already released here, or None.

    php.net has been observed answering with an older patch than the one it
    served an hour earlier. Without this the plan would happily build it,
    publish it, and repoint the manifest at a downgrade for every install.
    """
    req = urllib.request.Request(
        "https://api.github.com/repos/%s/releases?per_page=100" % repo,
        headers={"Accept": "application/vnd.github+json",
                 **({"Authorization": "Bearer " + token} if token else {})})
    best = None
    for rel in json.load(urllib.request.urlopen(req, timeout=30)):
        tag = rel.get("tag_name", "")
        if not tag.startswith("php-"):
            continue
        v = tag[4:]
        if not v.startswith(minor + "."):
            continue
        try:
            if best is None or version_key(v) > version_key(best):
                best = v
        except ValueError:
            continue
    return best


def published_assets(repo, tag, token):
    """The asset names of a release here, or None when the tag has none."""
    req = urllib.request.Request(
        "https://api.github.com/repos/%s/releases/tags/%s" % (repo, tag),
        headers={"Accept": "application/vnd.github+json",
                 **({"Authorization": "Bearer " + token} if token else {})})
    try:
        rel = json.load(urllib.request.urlopen(req, timeout=30))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise
    return [a.get("name", "") for a in rel.get("assets", [])]


def windows_patches():
    """The patch windows.php.net offers for each minor, or {} if unreachable.

    It lists only the newest patch per minor, and only once its build is up.
    Unreachable reads as "nothing yet": the macOS builds go ahead and Windows
    is picked up by a later run.
    """
    try:
        req = urllib.request.Request(WINDOWS_RELEASES, headers={"User-Agent": "Mozilla/5.0 (lerd-env/php plan)"})
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.load(r)
        return {minor: entry.get("version") for minor, entry in data.items() if isinstance(entry, dict)}
    except Exception as e:
        print("plan.py: windows.php.net did not answer (%s); planning no Windows builds" % e, file=sys.stderr)
        return {}


def main():
    repo = sys.argv[1]
    only = None
    force = "--force" in sys.argv
    skip_windows = "--skip-windows" in sys.argv
    if "--only" in sys.argv:
        only = sys.argv[sys.argv.index("--only") + 1]

    minors = [l.strip() for l in (ROOT / "versions.txt").read_text().splitlines()
              if l.strip() and not l.startswith("#")]
    if only:
        if only not in minors:
            sys.exit("plan.py: %s is not in versions.txt" % only)
        minors = [only]

    token = os.environ.get("GITHUB_TOKEN", "")
    on_windows = {} if skip_windows else windows_patches()
    macos, windows = [], []
    for minor in minors:
        patch = latest_patch(minor)
        if not patch:
            print("plan.py: php.net publishes no release for %s" % minor, file=sys.stderr)
            continue
        # Never plan a patch older than one already shipped for this minor.
        shipped = newest_published(repo, minor, token)
        if shipped and version_key(shipped) > version_key(patch):
            print("plan.py: php.net offers %s for %s but %s is already published; keeping %s"
                  % (patch, minor, shipped, shipped), file=sys.stderr)
            patch = shipped
        tag = "php-" + patch
        build = {"minor": minor, "patch": patch, "tag": tag}
        assets = published_assets(repo, tag, token)
        if force or assets is None or not any("-darwin-" in a for a in assets):
            macos.append(build)
        else:
            print("plan.py: %s already published for macOS" % tag, file=sys.stderr)
        if skip_windows:
            continue
        if not force and assets is not None and any("-windows-" in a for a in assets):
            print("plan.py: %s already published for Windows" % tag, file=sys.stderr)
        elif on_windows.get(minor) != patch:
            print("plan.py: windows.php.net offers %s for %s, not %s yet; Windows waits for a later run"
                  % (on_windows.get(minor) or "nothing", minor, patch), file=sys.stderr)
        else:
            windows.append(build)
    releases = sorted({b["tag"]: b for b in macos + windows}.values(), key=lambda b: b["tag"])
    print(json.dumps({"macos": macos, "windows": windows, "releases": releases}))


if __name__ == "__main__":
    main()
