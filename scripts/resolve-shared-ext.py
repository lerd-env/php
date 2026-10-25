#!/usr/bin/env python3
"""Pick the newest stable release of a PIE package that supports a PHP version.

    scripts/resolve-shared-ext.py xdebug/xdebug 8.1.34

Prints "<tag> <git-url>". spc's own PIE source takes the first Packagist entry,
prereleases included, which is how 8.1 got an xdebug alpha that refuses it.
PIE cannot do the resolving: it reads the platform by running the target php,
and that binary only exists after spc has built it from these sources.
"""
import json
import re
import sys
import urllib.request


def parse_version(text):
    parts = text.strip().lstrip("v").split(".")
    if not all(p.isdigit() for p in parts):
        sys.exit(f"resolve-shared-ext.py: cannot compare version {text!r}")
    return tuple(int(p) for p in (parts + ["0", "0", "0"])[:3])


def matches_one(php, term):
    m = re.fullmatch(r"(>=|<=|>|<|==|=|!=|\^|~)?\s*v?([0-9][0-9.]*)", term)
    if not m:
        sys.exit(f"resolve-shared-ext.py: unsupported constraint {term!r}")
    op, raw = m.group(1) or "=", m.group(2)
    v = parse_version(raw)
    if op == "^":
        upper = (v[0] + 1, 0, 0) if v[0] else (0, v[1] + 1, 0)
        return v <= php < upper
    if op == "~":
        # Composer: ~8.1 means >=8.1,<9 and ~8.1.2 means >=8.1.2,<8.2.
        upper = (v[0] + 1, 0, 0) if raw.count(".") < 2 else (v[0], v[1] + 1, 0)
        return v <= php < upper
    return {
        ">=": php >= v, "<=": php <= v, ">": php > v, "<": php < v,
        "=": php == v, "==": php == v, "!=": php != v,
    }[op]


def satisfies(php, constraint):
    if constraint.strip() == "*":
        return True
    for alternative in re.split(r"\s*\|\|?\s*", constraint.strip()):
        # Glue "op version" back together before splitting on AND separators.
        terms = re.sub(r"(>=|<=|>|<|==|=|!=|\^|~)\s+", r"\1", alternative)
        if all(matches_one(php, t) for t in re.split(r"[\s,]+", terms.strip())):
            return True
    return False


def expand(minified):
    # Packagist's p2 files list each release as a diff against the one before.
    out, current = [], {}
    for entry in minified:
        for key, value in entry.items():
            if value == "__unset":
                current.pop(key, None)
            else:
                current[key] = value
        out.append(dict(current))
    return out


def main():
    if len(sys.argv) != 3:
        sys.exit("usage: resolve-shared-ext.py <vendor/package> <php-version>")
    package, php = sys.argv[1], parse_version(sys.argv[2])
    url = f"https://repo.packagist.org/p2/{package}.json"
    with urllib.request.urlopen(url, timeout=30) as resp:
        releases = expand(json.load(resp)["packages"][package])

    stable = [r for r in releases if "-" not in r["version_normalized"]]
    stable.sort(key=lambda r: tuple(int(p) for p in r["version_normalized"].split(".")), reverse=True)
    for release in stable:
        if satisfies(php, release.get("require", {}).get("php", "*")):
            print(release["version"], release["source"]["url"])
            return
    sys.exit(f"resolve-shared-ext.py: no stable {package} release supports PHP {sys.argv[2]}")


if __name__ == "__main__":
    main()
