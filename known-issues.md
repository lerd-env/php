# Known issues

## ldap is not built

OpenLDAP's `tls_o.c` does not compile against the OpenSSL version static-php-cli
currently resolves: `use of undeclared identifier 'cert'`, seven errors in
`tls_o.lo`. It builds on a machine whose `buildroot` cache holds an older
OpenSSL, which is why this only appeared in CI.

`ldap` is therefore absent from `extensions.txt`, and a project requiring
`ext-ldap` should stay on the container runtime, whose image still ships it.
Lerd's site doctor reports the drift rather than letting it surface at runtime.

Re-add the line once upstream resolves a compatible pair. Nothing else needs to
change.

## Windows: the collector needs lerd's Windows port

`lerd_devtools` builds on Windows only from a lerd tree that carries
`config.w32` and `lerd_devtools_win32.h` beside the source. Until that reaches
lerd's default branch, Windows builds ship without the collector, say so in
`BUILD-INFO.txt`, and the query lens is unavailable there. Point `lerd_ref` at
a branch with the port to build it now.

## Windows: imagick adds ~150ms to every PHP start

ImageMagick initialises when imagick loads, which costs about 150ms per
process against 19ms for every other extension together. php-cgi pays it once
per child, but each CLI run (artisan, composer) pays it again. Not loading
imagick for the CLI would be lerd's call; the build ships it enabled, like the
image does.

## Windows: first load after unpacking is slow

Windows Defender scans the ~200 freshly unpacked DLLs the first time a PHP
loads them, which made the first request after unpacking take about 2.5s. Every
request after that is unaffected.

## 8.6 does not build

See the comment in `prerelease.txt`: static-php-cli patches phpmicro
unconditionally and those patches do not apply to 8.6.0beta2.
