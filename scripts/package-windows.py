#!/usr/bin/env python3
"""Turn a Windows build into the release asset lerd downloads, plus its pin.

    scripts/package-windows.py 8.4 out/ dist/ [expected-patch]

The Windows counterpart of package.sh: same asset naming, same pin schema, so
manifest.py and lerd treat windows/amd64 like any other platform. A tar.gz
rather than a zip because that is the format lerd already extracts, and
Windows 10 and later ship a tar that reads it.
"""
import datetime, hashlib, json, pathlib, subprocess, sys, tarfile


def die(msg):
    sys.exit("package-windows.py: " + msg)


def main():
    if len(sys.argv) < 4:
        die("usage: package-windows.py <php-minor> <outdir> <distdir> [expected-patch]")
    minor, outdir, distdir = sys.argv[1], pathlib.Path(sys.argv[2]), pathlib.Path(sys.argv[3])
    expected = sys.argv[4] if len(sys.argv) > 4 else ""

    phpdir = outdir / ("php-native-" + minor)
    patch = subprocess.run([str(phpdir / "php.exe"), "-n", "-r", "echo PHP_VERSION;"],
                           capture_output=True, text=True, check=True).stdout.strip()
    if not patch.startswith(minor + "."):
        die("built binary reports %s, which is not a %s release" % (patch, minor))
    # The plan chose the patch and the release is tagged for it; an asset whose
    # name disagrees with the binary inside it is worse than no asset.
    if expected and patch != expected:
        die("asked for %s but the binary reports %s" % (expected, patch))

    distdir.mkdir(parents=True, exist_ok=True)
    base = "lerd-php-%s-windows-x86_64" % patch
    asset = distdir / (base + ".tar.gz")
    members = [phpdir.name, "modules", "conf.d", "THIRD-PARTY-NOTICES.txt", "BUILD-INFO.txt"]
    with tarfile.open(asset, "w:gz") as tar:
        for name in members:
            path = outdir / name
            if not path.exists():
                die("%s is missing from %s" % (name, outdir))
            tar.add(path, arcname=name)

    digest = hashlib.sha256(asset.read_bytes()).hexdigest()
    (distdir / (base + ".tar.gz.sha256")).write_text(digest + "\n")
    pin = {
        "minor": minor,
        "version": patch,
        # A rebuild of a published patch keeps its version; the date is what
        # tells lerd it is a different build.
        "published": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "platform": "windows/amd64",
        "asset": asset.name,
        "sha256": digest,
        "size": asset.stat().st_size,
    }
    (distdir / ("pin-%s-windows-amd64.json" % minor)).write_text(json.dumps(pin, separators=(",", ":")) + "\n")
    print(asset)
    print(json.dumps(pin))


if __name__ == "__main__":
    main()
