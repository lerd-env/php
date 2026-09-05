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

## 8.6 does not build

See the comment in `prerelease.txt`: static-php-cli patches phpmicro
unconditionally and those patches do not apply to 8.6.0beta2.
