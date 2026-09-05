# Lerd PHP Binaries

> The static PHP builds that power [Lerd](https://lerd.sh)'s native runtime on
> macOS — run PHP on the host instead of in a container, no image required.

[![Part of Lerd](https://img.shields.io/badge/part%20of-lerd-ff2d20)](https://lerd.sh)
[![Docs](https://img.shields.io/badge/docs-lerd.sh-blue)](https://lerd.sh/features/native-runtime)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

On macOS your project lives on the host and is mounted into the Podman VM, so a containerised PHP crosses that boundary for every file it reads. Measured over 2000 files in one PHP process, a `stat` costs 108ms in a container against 4ms on the host, and an `include` 320ms against 31ms. Lerd's native runtime removes the boundary by running PHP-FPM, the CLI and the workers directly on the host, and this repo is where those binaries come from.

That's the whole point: **the speed comes from where PHP runs, not from what it gives up.** The build carries the same extension set the container image does, so Xdebug, SPX, dumps and the debug bridge keep working.

## What a build produces

A single version build outputs:

- 🐘 **`php-native-<version>`** — the CLI, behind `lerd php`, composer, tinker and every worker
- ⚡ **`php-native-fpm-<version>`** — the FPM nginx fastcgi's to from inside the VM
- 🧩 **`modules/*.so`** — the extensions that can only exist as shared objects, Xdebug and pcov among them
- 🔐 **A sha256** — Lerd verifies every download against the digest pinned in its manifest
- 🏷️ **`Built by lerd`** — what `php -v` reports, so a binary always says where it came from
- 🧾 **`BUILD-INFO.txt`** — the static-php-cli release and digest that produced it
- 📄 **`THIRD-PARTY-NOTICES.txt`** — PHP's licence and every statically linked library's, as those licences require of a binary distribution

Everything is a release asset. Nothing built is ever committed here.

Builds are for **Apple silicon**. Intel is opt-in on a dispatch and on borrowed time: GitHub retired the `macos-13` image in December 2025 and drops x86_64 macOS entirely after August 2027. An Intel Mac keeps using lerd's container runtime, which lerd says plainly rather than offering a switch with no binary behind it.

## Available versions

| PHP | Native runtime | Notes |
|-----|----------------|-------|
| 8.5 | ✅ | |
| 8.4 | ✅ | |
| 8.3 | ✅ | |
| 8.2 | ✅ | |
| 8.1 | ✅ | |
| 8.6 | ⏳ | prerelease; blocked on static-php-cli, whose phpmicro patches do not apply to 8.6.0beta2. The scaffolding is in place, see `prerelease.txt` |
| 8.0 | ❌ | fails against current libxml2 and ICU; builds only with the XML extensions stripped, which no framework survives |
| 7.4 | ❌ | static PHP carries no OPcache below 8.0, and the same libxml2 and ICU walls apply |

Lerd refuses to switch an install to the native runtime while any site runs a version that is not here, and names the sites standing in the way.

## Prereleases

A PHP with no GA release is built from a pinned source tarball listed in `prerelease.txt`, with the extensions that do not compile against it dropped via `unbuildable-prerelease.txt`. That list mirrors lerd's own `prereleaseUnbuildable`, so a prerelease advertises the same extensions whichever runtime serves it.

## Extensions

`extensions.txt` is the static set compiled into the binary, and `shared-extensions.txt` those that can only be built as loadable objects. Together they match what the PHP image ships, including `intl`, `imagick`, `mongodb`, `redis`, `soap`, `xsl` and `spx`.

`ldap` is currently absent; see [known issues](known-issues.md).

The set is fixed at build time, so `lerd php:ext` and `lerd php:pkg` refuse under the native runtime. A project needing something outside it stays on container mode, and Lerd's site doctor reports the drift before it surfaces at runtime.

## Usage

You never fetch these by hand. Lerd downloads the build matching a project's PHP version the first time it needs one, verifies the digest, and stores it in `~/.local/share/lerd/bin`:

```bash
lerd php:runtime native      # move PHP onto the host
lerd php:runtime container   # back to the containers
lerd php:runtime             # show the current runtime
lerd php:list                # the versions installed for the active runtime
```

The same binaries back NativePHP Jump, whose websocket bridge needs `posix` and `pcntl` that NativePHP's bundled PHP does not carry.

## Built with static-php-cli

Every binary here is produced by [static-php-cli](https://github.com/crazywhalecc/static-php-cli) (MIT), and this repository is the thin layer that drives it: which extensions to compile, how to name and package the result, and which licences to ship alongside it. The compiler toolchain, the patch sets, the dependency graph and the library versions are all its work, not ours.

That dependency shapes what is possible here, so it is worth being explicit about:

- **Extension names are spc's**, not PHP's. `mbregex` is a separate entry from `mbstring`, for instance, and a list written from `php -m` output silently loses it.
- **spc chooses the library versions.** PHP 7.4 and 8.0 fail against the libxml2 and ICU it builds, which is why they are absent above.
- **spc patches phpmicro unconditionally**, even for a build that produces only CLI and FPM, which is what currently blocks 8.6.
- **The build provider string** is set on spc's own configure line, so `Built by lerd` is achieved by patching `configure.ac` in the source tarball before spc extracts it.

Builds track the **newest stable** static-php-cli release, resolved at build time rather than pinned, so PHP support and fixes arrive without a bump here. Nightly is deliberately avoided: it changes the build tooling underneath a release with no way to tell afterwards. The version and digest that produced a given binary are recorded in `BUILD-INFO.txt` and shipped inside its tarball, so any artifact can be traced back to its toolchain.

If you are packaging static PHP for your own project, use static-php-cli directly. This repo exists for the parts specific to lerd.

## Building locally

```bash
scripts/build.sh 8.4 out/      # fetches static-php-cli itself
scripts/package.sh 8.4 out/ dist/
```

A cold build takes about fourteen minutes and needs roughly 6 GB of scratch. The libraries dominate that and are shared across versions, so each additional version costs about three minutes once `buildroot/` and `downloads/` are warm.

`scripts/build.sh` refuses to publish a binary missing `dom`, `simplexml`, `xml`, `intl`, `mbstring` or `opcache`. That guard is why 7.4 and 8.0 are not here: both can be made to compile, and neither can run a real application afterwards.

## License

The scripts and manifests in this repository are MIT, as is [static-php-cli](https://github.com/crazywhalecc/static-php-cli), the tool that builds the binaries.

The binaries they produce are not: PHP is distributed under the [PHP License 3.01](https://www.php.net/license/), and the build statically links OpenSSL, ICU, ImageMagick, libxml2, curl, libsodium, the PostgreSQL client and others, each under its own terms. Every release tarball ships a `THIRD-PARTY-NOTICES.txt` reproducing those licences in full, which is what those licences require of anyone redistributing a binary.
