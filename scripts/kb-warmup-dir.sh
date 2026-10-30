#!/usr/bin/env bash
# Create knowledge-worker's /warmup bind source and prove the worker can write it.
# Usage: kb-warmup-dir.sh [DIR]  (DIR overrides KB_WARMUP_DIR). COMPOSE: the compose command.
# Only when the probe fails, on Linux Docker, an ACL grants uid 10001; that needs setfacl,
# an ACL-capable filesystem and a dir the current user owns. A second probe stops the rest.
set -euo pipefail

compose=${COMPOSE:-docker compose}
fail() { echo "kb-warmup-dir: $*" >&2; exit 1; }

for tool in docker jq; do
  command -v "$tool" >/dev/null || fail "$tool not found on PATH; install it"
done
if [ $# -gt 0 ]; then export KB_WARMUP_DIR=$1; fi

config=$($compose config --format json) || fail "'$compose config' failed"
dir=$(jq -er '.services["knowledge-worker"].volumes[]?
  | select(.target == "/warmup" and .type == "bind").source' <<<"$config") ||
  fail "knowledge-worker has no bind mount at /warmup in '$compose config'"
echo "warm-up dir: $dir"
mkdir -p "$dir" || fail "cannot create $dir"

# The image's own USER, not --user 10001: a Dockerfile uid change must fail here, so
# the probe runs the image as built from the current Dockerfile, not a stale one.
$compose build knowledge-worker || fail "'$compose build knowledge-worker' failed"
$compose run --rm --no-deps --entrypoint true knowledge-worker ||
  fail "knowledge-worker does not start; fix its build or image before probing $dir"
probe() {
  $compose run --rm --no-deps --entrypoint sh knowledge-worker \
    -c 'touch /warmup/.kb-probe && rm /warmup/.kb-probe'
}
probe && exit 0

# Docker Desktop's file sharing maps every container uid onto the host user.
os=$(docker info --format '{{.OperatingSystem}}') || fail "docker info failed; is the daemon running?"
if [[ $os != *"Docker Desktop"* ]]; then
  command -v setfacl >/dev/null ||
    fail "setfacl not found; install the acl package, or chown $dir to 10001"
  # The default entries let the host user edit and delete what the worker writes.
  setfacl -m "u:10001:rwX,d:u:10001:rwX,d:u:$(id -u):rwX" "$dir" ||
    fail "setfacl on $dir failed: the dir must be yours, on a filesystem with ACLs"
  probe && exit 0
fi

fail "knowledge-worker cannot write $dir. Likely: rootless or userns-remapped Docker
(uid 10001 is not 10001 on the host), SELinux (add :z to the mount), a filesystem
without ACLs, or a dir owned by another user."
