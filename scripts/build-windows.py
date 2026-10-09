#!/usr/bin/env python3
"""Assemble the Windows build of one PHP minor for lerd's native runtime.

    scripts/build-windows.py 8.4 out/ [8.4.26]

Windows has no PHP-FPM and static-php-cli cannot load DLL extensions, so this
does not compile PHP. It takes the official windows.php.net NTS build, adds the
PECL and Xdebug DLLs extensions.txt asks for, compiles lerd_devtools against
the matching devel pack, and lays the result out the way lerd unpacks it:

    php-native-<minor>/   the official build: php.exe, php-cgi.exe, ext/, DLLs
    modules/              loadable on demand: xdebug.dll, pcov.dll, lerd_devtools-<minor>.dll
    conf.d/               10-lerd-extensions.ini, which enables the static set
    BUILD-INFO.txt        every source, its version and digest, and the toolset
    THIRD-PARTY-NOTICES.txt

php-cgi.exe is the FastCGI server lerd runs in place of FPM; PHP_FCGI_CHILDREN
gives it a pool. extension_dir is left to lerd, which knows where it installed
the tree; the ini only names the extensions.

LERD_DEVTOOLS_SRC points at lerd's internal/podman/devtools. Without it, or
without a config.w32 there, the build ships no collector and says so, the same
as the macOS build.
"""
import hashlib, io, json, os, pathlib, re, shutil, struct, subprocess, sys, tempfile, urllib.request, zipfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
RELEASES = "https://downloads.php.net/~windows/releases/"
PECL = "https://downloads.php.net/~windows/pecl/releases/"
XDEBUG = "https://xdebug.org/files/"
# php.net's own build tooling; configure.js needs its bison and re2c even for an
# extension. Cloned by tag, since GitHub's archive zips are not byte-stable.
PHP_SDK_REPO = "https://github.com/php/php-sdk-binary-tools.git"
PHP_SDK_TAG = "php-sdk-2.8.4"
# windows.php.net refuses requests without a browser-like user agent.
UA = {"User-Agent": "Mozilla/5.0 (lerd-env/php build)"}

# spc names a few extensions differently from PHP, and some are part of another.
ALIASES = {"mbregex": "mbstring"}
# Loaded with zend_extension= rather than extension=.
ZEND_EXTENSIONS = {"opcache", "xdebug"}
# What build.sh refuses to publish without; a framework does not run otherwise.
REQUIRED = ["dom", "simplexml", "xml", "intl", "mbstring", "opcache"]


def die(msg):
    sys.exit("build-windows.py: " + msg)


def fetch(url, dest=None):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=300) as r:
        data = r.read()
    if dest:
        pathlib.Path(dest).write_bytes(data)
    return data


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def read_list(name):
    path = ROOT / name
    if not path.exists():
        return []
    return [l.split("#")[0].strip() for l in path.read_text().splitlines()
            if l.split("#")[0].strip()]


def official_build(minor, patch):
    """The releases.json entry for this patch, or a clear refusal.

    windows.php.net lists only the newest patch of each minor, and publishes it
    some hours after php.net announces the source. Building anything else would
    mean an unverified download from the archive, so a lagging minor is refused
    here and picked up by the next run.
    """
    releases = json.loads(fetch(RELEASES + "releases.json"))
    entry = releases.get(minor)
    if not entry:
        die("windows.php.net lists no %s release" % minor)
    if entry["version"] != patch:
        die("windows.php.net lists %s for %s, not %s; it has not published this patch yet"
            % (entry["version"], minor, patch))
    keys = [k for k in entry if re.fullmatch(r"nts-vs\d+-x64", k)]
    if len(keys) != 1:
        die("expected one NTS x64 build for %s, found %s" % (patch, keys or "none"))
    build = entry[keys[0]]
    return keys[0].split("-")[1], build  # ("vs17", {...})


def fetch_verified(item, dest):
    data = fetch(RELEASES + item["path"])
    got = sha256(data)
    if got != item["sha256"]:
        die("%s: sha256 %s, releases.json says %s" % (item["path"], got, item["sha256"]))
    pathlib.Path(dest).write_bytes(data)
    return got


def linker_version(exe):
    """The MSVC linker version in a PE header, as (major, minor)."""
    with open(exe, "rb") as f:
        head = f.read(4096)
    pe = struct.unpack_from("<I", head, 0x3C)[0]
    if head[pe:pe + 4] != b"PE\0\0":
        die("%s is not a PE image" % exe)
    # The optional header follows the 4-byte signature and 20-byte COFF header;
    # its linker version sits right after the 2-byte magic.
    return head[pe + 26], head[pe + 27]


def pe_imports(path):
    """The DLL names a PE image imports, ordinary and delay-loaded, lowercased."""
    data = pathlib.Path(path).read_bytes()
    pe = struct.unpack_from("<I", data, 0x3C)[0]
    nsections, optsize = struct.unpack_from("<H", data, pe + 6)[0], struct.unpack_from("<H", data, pe + 20)[0]
    opt = pe + 24
    # PE32+ keeps its data directories 112 bytes into the optional header.
    dirs = opt + (112 if struct.unpack_from("<H", data, opt)[0] == 0x20B else 96)
    sections = []
    for i in range(nsections):
        s = opt + optsize + 40 * i
        vsize, va, rawsize, raw = struct.unpack_from("<IIII", data, s + 8)
        sections.append((va, max(vsize, rawsize), raw))

    def offset(rva):
        for va, size, raw in sections:
            if va <= rva < va + size:
                return rva - va + raw
        return None

    def name(rva):
        o = offset(rva)
        return data[o:data.index(b"\0", o)].decode("ascii").lower() if o is not None else None

    names = set()
    # Directory 1 is the import table (name RVA at +12 of 20-byte entries),
    # 13 the delay-load table (name RVA at +4 of 32-byte entries).
    for index, size, at in ((1, 20, 12), (13, 32, 4)):
        rva = struct.unpack_from("<I", data, dirs + 8 * index)[0]
        o = offset(rva) if rva else None
        while o is not None and any(data[o:o + size]):
            n = name(struct.unpack_from("<I", data, o + at)[0])
            if n:
                names.add(n)
            o += size
    return names


# The Visual C++ runtime the official build and the PECL DLLs are linked
# against. Windows does not ship it, and only machines that happen to have the
# redistributable installed (as every CI runner does) can load PHP without it.
VC_RUNTIME = re.compile(r"(vcruntime140(_\d+)?|msvcp140(_\w+)?|concrt140|vccorlib140|vcomp140)\.dll")


def vc_redist():
    """The newest x64 Visual C++ redist directory any Visual Studio carries.

    The v14 runtime is backward compatible, so the newest one serves cores and
    modules linked with VS 2019 as well as VS 2022.
    """
    vswhere = pathlib.Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) \
        / "Microsoft Visual Studio" / "Installer" / "vswhere.exe"
    if not vswhere.exists():
        die("no Visual Studio installation found (vswhere.exe is missing)")
    out = subprocess.run([str(vswhere), "-all", "-products", "*", "-property", "installationPath"],
                         capture_output=True, text=True, check=True).stdout
    best = None
    for install in filter(None, (l.strip() for l in out.splitlines())):
        root = pathlib.Path(install) / "VC" / "Redist" / "MSVC"
        if not root.is_dir():
            continue
        for d in root.iterdir():
            if not re.fullmatch(r"\d+\.\d+\.\d+", d.name) or not (d / "x64").is_dir():
                continue
            key = tuple(int(p) for p in d.name.split("."))
            if best is None or key > best[0]:
                best = (key, d / "x64")
    if not best:
        die("no Visual C++ redist found under any Visual Studio install; "
            "the C++ workload carries it in VC\\Redist\\MSVC")
    return best[1]


def bundle_vc_runtime(outdir, phpdir, redist):
    """Copy every VC runtime DLL anything shipped imports next to php.exe.

    Windows looks in the executable's directory before System32, so these are
    what php.exe and php-cgi.exe load whether or not the machine has the
    redistributable. Repeats until closed, since msvcp140 itself imports
    vcruntime140.
    """
    available = {p.name.lower(): p for p in redist.rglob("*.dll")}
    bundled = set()
    while True:
        wanted = set()
        for image in list(outdir.rglob("*.dll")) + list(outdir.rglob("*.exe")):
            wanted |= {n for n in pe_imports(image) if VC_RUNTIME.fullmatch(n)}
        missing = wanted - {p.name.lower() for p in phpdir.glob("*.dll")}
        if not missing:
            return sorted(bundled)
        for n in sorted(missing):
            if n not in available:
                die("the build imports %s, which %s does not carry" % (n, redist))
            shutil.copy2(available[n], phpdir / available[n].name)
            bundled.add(available[n].name)


def pick_toolset(core):
    """The newest installed MSVC toolset PHP will accept a module from.

    PHP compares the tens digit of the linker's minor version and refuses a
    module linked with a newer one than its core (win32/winutil.c), so a VS 2019
    core (14.2x) needs v142 even where VS 2022 is the default.
    """
    vswhere = pathlib.Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) \
        / "Microsoft Visual Studio" / "Installer" / "vswhere.exe"
    if not vswhere.exists():
        die("no Visual Studio installation found (vswhere.exe is missing)")
    out = subprocess.run([str(vswhere), "-all", "-products", "*", "-property", "installationPath"],
                         capture_output=True, text=True, check=True).stdout
    best = None
    for install in filter(None, (l.strip() for l in out.splitlines())):
        vcvars = pathlib.Path(install) / "VC" / "Auxiliary" / "Build" / "vcvars64.bat"
        tools = pathlib.Path(install) / "VC" / "Tools" / "MSVC"
        if not vcvars.exists() or not tools.is_dir():
            continue
        for d in tools.iterdir():
            parts = d.name.split(".")
            if len(parts) < 2 or not parts[0].isdigit() or not parts[1].isdigit():
                continue
            major, minor = int(parts[0]), int(parts[1])
            if major != core[0] or minor // 10 > core[1] // 10:
                continue
            key = tuple(int(p) for p in parts if p.isdigit())
            if best is None or key > best[0]:
                best = (key, "%d.%d" % (major, minor), vcvars)
    if not best:
        die("no MSVC toolset %d.%dx or older is installed; this core needs one "
            "(for a VS 2019 core add Microsoft.VisualStudio.Component.VC.14.29.16.11.x86.x64)"
            % (core[0], core[1] // 10))
    return best[1], best[2]


def unzip(data, dest):
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        z.extractall(dest)


def licence_files(root):
    # Matched case-insensitively: the official zip says license.txt, PECL
    # packages LICENSE, and Windows would otherwise hand back the same file twice.
    return sorted(p for p in root.iterdir()
                  if p.is_file() and p.name.lower().startswith(("license", "copying")))


def php(phpdir, args, env=None):
    return subprocess.run([str(phpdir / "php.exe")] + args, capture_output=True, text=True,
                          env={**os.environ, **(env or {})})


def loaded_modules(phpdir, ini, scan):
    r = php(phpdir, ["-c", str(ini), "-m"], {"PHP_INI_SCAN_DIR": str(scan)})
    if r.returncode != 0 or "Warning" in r.stdout + r.stderr:
        die("php -m with the generated ini failed:\n" + r.stdout + r.stderr)
    mods = set()
    for line in r.stdout.splitlines():
        line = line.strip()
        if line and not line.startswith("["):
            mods.add("opcache" if line == "Zend OPcache" else line.lower())
    return mods


def main():
    if len(sys.argv) < 3:
        die("usage: build-windows.py <php-minor> <outdir> [patch]")
    minor, outdir = sys.argv[1], pathlib.Path(sys.argv[2]).resolve()
    patch = sys.argv[3] if len(sys.argv) > 3 else None

    if patch is None:
        patch = json.loads(fetch(RELEASES + "releases.json"))[minor]["version"]
    vs, build = official_build(minor, patch)
    print("building PHP %s for windows/amd64 from the official %s build" % (patch, vs))

    if outdir.exists():
        shutil.rmtree(outdir)
    phpdir = outdir / ("php-native-" + minor)
    modules, confd = outdir / "modules", outdir / "conf.d"
    for d in (phpdir, modules, confd):
        d.mkdir(parents=True)
    work = pathlib.Path(tempfile.mkdtemp(prefix="lerd-php-win-"))
    info = ["lerd native PHP %s, windows/amd64" % patch, ""]
    notices = []

    # The official build, verified against the digest windows.php.net publishes.
    zip_path = work / build["zip"]["path"]
    digest = fetch_verified(build["zip"], zip_path)
    unzip(zip_path.read_bytes(), phpdir)
    info.append("php: %s%s sha256:%s" % (RELEASES, build["zip"]["path"], digest))
    notices += licence_files(phpdir)

    unavailable = set(read_list("windows-unavailable.txt"))
    shared = set(read_list("shared-extensions.txt"))
    wanted = [e for e in read_list("extensions.txt") if e not in unavailable]

    # PECL and Xdebug DLLs, for this minor and compiler. Neither source
    # publishes digests, so each is recorded here and the release pin covers
    # the tarball that carries them.
    for line in read_list("windows-extensions.txt"):
        ext, version, source = line.split()
        if source == "pecl":
            name = "php_%s-%s-%s-nts-%s-x64.zip" % (ext, version.lower(), minor, vs)
            url = "%s%s/%s/%s" % (PECL, ext, version, name)
            data = fetch(url)
            staged = work / ("pecl-" + ext)
            unzip(data, staged)
            dll = staged / ("php_%s.dll" % ext)
            if not dll.exists():
                die("%s carries no php_%s.dll" % (name, ext))
            shutil.copy2(dll, (modules / (ext + ".dll")) if ext in shared else (phpdir / "ext" / dll.name))
            # imagick ships ImageMagick as DLLs beside its own; Windows only
            # finds them next to the executable that loads the module.
            for dep in staged.glob("*.dll"):
                if dep.name != dll.name:
                    shutil.copy2(dep, phpdir / dep.name)
            notices += licence_files(staged)
        elif source == "xdebug":
            name = "php_xdebug-%s-%s-nts-%s-x86_64.dll" % (version, minor, vs)
            url = XDEBUG + name
            data = fetch(url)
            (modules / "xdebug.dll").write_bytes(data)
        else:
            die("windows-extensions.txt: unknown source %r for %s" % (source, ext))
        info.append("%s %s: %s sha256:%s" % (ext, version, url, sha256(data)))

    # Bundled before the checks below, so they load the copies that ship.
    redist = vc_redist()
    runtime = bundle_vc_runtime(outdir, phpdir, redist)

    # Turn on the static set the macOS build compiles in. Built-in modules need
    # no line; everything else must be a DLL by now, or the build stops rather
    # than ship a PHP missing an extension the container image has.
    with tempfile.TemporaryDirectory() as empty:
        none = pathlib.Path(empty) / "none.ini"
        none.write_text("")
        builtin = loaded_modules(phpdir, none, pathlib.Path(empty))
    lines, seen = [], set()
    for ext in wanted:
        ext = ALIASES.get(ext, ext)
        if ext in seen or ext in builtin:
            continue
        seen.add(ext)
        if not (phpdir / "ext" / ("php_%s.dll" % ext)).exists():
            die("extensions.txt asks for %s and the Windows build has no DLL for it; "
                "add it to windows-extensions.txt or windows-unavailable.txt" % ext)
        lines.append("%s=%s" % ("zend_extension" if ext in ZEND_EXTENSIONS else "extension", ext))
    (confd / "10-lerd-extensions.ini").write_text(
        "; Generated by lerd-env/php: the extensions lerd's PHP image compiles in.\n"
        "; extension_dir is set by lerd, which knows where this tree was unpacked.\n"
        + "\n".join(lines) + "\n")

    # Check the result the way lerd will run it.
    ini = work / "verify.ini"
    ini.write_text('extension_dir="%s"\n' % (phpdir / "ext"))
    mods = loaded_modules(phpdir, ini, confd)
    missing = [e for e in {ALIASES.get(e, e) for e in wanted} if e not in mods]
    if missing:
        die("enabled but not loaded: " + ", ".join(sorted(missing)))
    for required in REQUIRED:
        if required not in mods:
            die("php %s is missing %s; refusing to publish it" % (patch, required))
    for ext in sorted(shared - unavailable):
        dll = modules / (ext + ".dll")
        kind = "zend_extension" if ext in ZEND_EXTENSIONS else "extension"
        r = php(phpdir, ["-n", "-d", "%s=%s" % (kind, dll), "-r",
                         "exit(extension_loaded(%r) ? 0 : 1);" % ext])
        if r.returncode != 0 or "Warning" in r.stdout + r.stderr:
            die("%s.dll does not load:\n%s%s" % (ext, r.stdout, r.stderr))

    # The query-capture collector. Optional, like on macOS: a PHP without it
    # still works and lerd's doctor reports the lens as unavailable.
    core = linker_version(phpdir / "php.exe")
    info.append("core linker: %d.%d" % core)
    src = os.environ.get("LERD_DEVTOOLS_SRC")
    if src and (pathlib.Path(src) / "config.w32").exists():
        toolset, vcvars = pick_toolset(core)
        devel_zip = work / build["devel_pack"]["path"]
        devel_digest = fetch_verified(build["devel_pack"], devel_zip)
        unzip(devel_zip.read_bytes(), work / "devel")
        devel = next((work / "devel").iterdir())
        sdk = os.environ.get("PHP_SDK")
        if not sdk:
            sdk = str(work / "php-sdk")
            subprocess.run(["git", "clone", "-q", "--depth", "1", "--branch", PHP_SDK_TAG,
                            PHP_SDK_REPO, sdk], check=True)
        staging = work / "devtools"
        r = subprocess.run(["cmd", "/c", str(ROOT / "scripts" / "build-devtools-windows.cmd"),
                            str(vcvars), toolset, str(devel), str(pathlib.Path(src).resolve()), str(staging), sdk],
                           capture_output=True, text=True)
        dll = staging / "x64" / "Release" / "php_lerd_devtools.dll"
        if r.returncode != 0 or not dll.exists():
            print(r.stdout[-4000:] + r.stderr[-4000:], file=sys.stderr)
            die("lerd_devtools did not build with MSVC %s" % toolset)
        target = modules / ("lerd_devtools-%s.dll" % minor)
        shutil.copy2(dll, target)
        r = php(phpdir, ["-n", "-d", "extension=%s" % target, "-r",
                         "exit(extension_loaded('lerd_devtools') ? 0 : 1);"])
        if r.returncode != 0 or "Warning" in r.stdout + r.stderr:
            die("lerd_devtools built with MSVC %s but will not load:\n%s%s" % (toolset, r.stdout, r.stderr))
        info.append("devel pack: %s%s sha256:%s" % (RELEASES, build["devel_pack"]["path"], devel_digest))
        info.append("php-sdk-binary-tools: %s" % (PHP_SDK_TAG if not os.environ.get("PHP_SDK") else os.environ["PHP_SDK"]))
        info.append("lerd_devtools: built with MSVC %s, linker %d.%d" % ((toolset,) + linker_version(target)))
        print("lerd_devtools-%s.dll built with MSVC %s and loads" % (minor, toolset))
    else:
        print("build-windows.py: no lerd_devtools source with a config.w32, "
              "skipping the query-capture collector", file=sys.stderr)
        info.append("lerd_devtools: not built")

    # The collector may link against a runtime DLL nothing else used.
    runtime = sorted(set(runtime) | set(bundle_vc_runtime(outdir, phpdir, redist)))
    info.append("vc runtime: %s from %s" % (", ".join(runtime), redist.parent.name))

    info += ["", "not available on Windows: " + ", ".join(sorted(unavailable))]
    (outdir / "BUILD-INFO.txt").write_text("\n".join(info) + "\n")

    with open(outdir / "THIRD-PARTY-NOTICES.txt", "w", encoding="utf-8") as out:
        out.write("Third-party licences for the lerd native PHP build (Windows)\n\n"
                  "This build redistributes the official windows.php.net PHP and the\n"
                  "extension DLLs listed in BUILD-INFO.txt. Each licence text shipped\n"
                  "with them is reproduced below. Xdebug is distributed under the\n"
                  "Xdebug License: https://xdebug.org/license\n\n"
                  "The Visual C++ runtime DLLs beside php.exe, listed in BUILD-INFO.txt,\n"
                  "are Microsoft Visual C++ Redistributable files, distributed under the\n"
                  "Visual Studio licence terms for Distributable Code:\n"
                  "https://learn.microsoft.com/visualstudio/releases/2022/redistribution\n\n")
        for f in notices:
            out.write("=" * 64 + "\n%s (%s)\n" % (f.parent.name, f.name) + "=" * 64 + "\n")
            out.write(f.read_text(encoding="utf-8", errors="replace") + "\n")

    shutil.rmtree(work, ignore_errors=True)
    print(php(phpdir, ["-n", "-v"]).stdout.strip())


if __name__ == "__main__":
    main()
