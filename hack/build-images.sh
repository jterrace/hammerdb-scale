#!/usr/bin/env bash
# Build and verify the hammerdb-scale container images.
#
# Builds the base image, then the Oracle extension FROM that base, then runs
# verification against both. Nothing is pushed and no moving tag is applied
# until every check passes.
#
# The ordering is not incidental: Dockerfile.oracle defaults to
# BASE_IMAGE=sillidata/hammerdb-scale:latest, so a careless build produces an
# "Oracle 6.0" image containing whatever the published base happens to be.
# This script always wires BASE_IMAGE explicitly and then verifies the result.
#
# USAGE
#   hack/build-images.sh                        # local build, localhost/
#   hack/build-images.sh -r docker.io/sillidata # tag for a registry
#   hack/build-images.sh -r docker.io/sillidata --push
#
# OPTIONS
#   -r, --registry REG   registry/namespace prefix (default: localhost)
#   -v, --version VER    HammerDB version to build (default: from Dockerfile)
#   -t, --tag TAG        primary immutable tag (default: the HammerDB version)
#       --latest         also apply the :latest tag (implied by --push)
#       --push           push all tags after verification
#       --skip-verify    build only; not recommended
#       --base-only      skip the Oracle image
#
# Requires podman or docker. Oracle Instant Client is x86_64 only, so both
# images are x86_64.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

REGISTRY="localhost"
HDB_VERSION=""
PRIMARY_TAG=""
APPLY_LATEST=0
DO_PUSH=0
DO_VERIFY=1
BASE_ONLY=0

while [[ $# -gt 0 ]]; do
    case "$1" in
        -r|--registry) REGISTRY="${2%/}"; shift 2 ;;
        -v|--version)  HDB_VERSION="$2"; shift 2 ;;
        -t|--tag)      PRIMARY_TAG="$2"; shift 2 ;;
        --latest)      APPLY_LATEST=1; shift ;;
        --push)        DO_PUSH=1; APPLY_LATEST=1; shift ;;
        --skip-verify) DO_VERIFY=0; shift ;;
        --base-only)   BASE_ONLY=1; shift ;;
        -h|--help)     sed -n '2,30p' "$0"; exit 0 ;;
        *) echo "Unknown option: $1" >&2; exit 1 ;;
    esac
done

# --- Runtime ---------------------------------------------------------------
if command -v podman >/dev/null 2>&1; then
    RUNTIME=podman
elif command -v docker >/dev/null 2>&1; then
    RUNTIME=docker
else
    echo "ERROR: neither podman nor docker found" >&2
    exit 1
fi

log()  { echo -e "\033[1m[build]\033[0m $*"; }
fail() { echo -e "\033[31m[FAIL]\033[0m $*" >&2; exit 1; }
ok()   { echo -e "\033[32m  ok\033[0m $*"; }

# --- Version resolution ----------------------------------------------------
# The Dockerfile is the source of truth so the script cannot drift from it.
if [ -z "$HDB_VERSION" ]; then
    HDB_VERSION="$(grep -oP '^ARG HAMMERDB_VERSION=\K\S+' Dockerfile)"
fi
[ -n "$HDB_VERSION" ] || fail "could not determine HAMMERDB_VERSION from Dockerfile"

PRIMARY_TAG="${PRIMARY_TAG:-$HDB_VERSION}"
MAJOR_TAG="${HDB_VERSION%%.*}"

CLI_VERSION="$(grep -oP '^version = "\K[^"]+' pyproject.toml || echo unknown)"
VCS_REF="$(git rev-parse --short HEAD 2>/dev/null || echo unknown)"
BUILD_DATE="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

if ! git diff --quiet HEAD 2>/dev/null; then
    VCS_REF="${VCS_REF}-dirty"
fi

BASE_IMAGE="${REGISTRY}/hammerdb-scale"
ORACLE_IMAGE="${REGISTRY}/hammerdb-scale-oracle"

log "runtime=${RUNTIME} registry=${REGISTRY}"
log "HammerDB=${HDB_VERSION} CLI=${CLI_VERSION} commit=${VCS_REF}"
log "tags: ${PRIMARY_TAG}, ${MAJOR_TAG}, ${CLI_VERSION}-hdb${HDB_VERSION}$([ $APPLY_LATEST -eq 1 ] && echo ', latest')"

COMMON_ARGS=(
    --build-arg "VCS_REF=${VCS_REF}"
    --build-arg "BUILD_DATE=${BUILD_DATE}"
    --build-arg "IMAGE_VERSION=${CLI_VERSION}"
)

# --- Build: base -----------------------------------------------------------
log "building ${BASE_IMAGE}:${PRIMARY_TAG}"
$RUNTIME build \
    -f Dockerfile \
    --build-arg "HAMMERDB_VERSION=${HDB_VERSION}" \
    "${COMMON_ARGS[@]}" \
    -t "${BASE_IMAGE}:${PRIMARY_TAG}" \
    .

# --- Build: Oracle ---------------------------------------------------------
if [ "$BASE_ONLY" -eq 0 ]; then
    log "building ${ORACLE_IMAGE}:${PRIMARY_TAG} FROM ${BASE_IMAGE}:${PRIMARY_TAG}"
    $RUNTIME build \
        -f Dockerfile.oracle \
        --build-arg "BASE_IMAGE=${BASE_IMAGE}:${PRIMARY_TAG}" \
        "${COMMON_ARGS[@]}" \
        -t "${ORACLE_IMAGE}:${PRIMARY_TAG}" \
        .
fi

# --- Verify ----------------------------------------------------------------
verify_image() {
    local image="$1" want_oracle="$2"
    log "verifying ${image}"

    local home
    home="$($RUNTIME run --rm --entrypoint /bin/bash "$image" -c 'echo -n "$HAMMERDB_HOME"')"
    [ "$home" = "/opt/HammerDB-${HDB_VERSION}" ] \
        || fail "${image}: HAMMERDB_HOME is '${home}', expected /opt/HammerDB-${HDB_VERSION}"
    ok "HAMMERDB_HOME=${home}"

    # The single check that catches an Oracle image built on a stale base.
    local reported
    reported="$($RUNTIME run --rm --entrypoint /bin/bash "$image" \
        -c 'cd $HAMMERDB_HOME && printf "" | ./hammerdbcli 2>&1 | head -1')"
    grep -q "v${HDB_VERSION}" <<<"$reported" \
        || fail "${image}: hammerdbcli reports '${reported}', expected v${HDB_VERSION}"
    ok "hammerdbcli: ${reported}"

    # PostgreSQL fails at runtime without the system libpq, which is easy to
    # miss because HammerDB bundles Pgtcl itself.
    $RUNTIME run --rm --entrypoint /bin/bash "$image" \
        -c 'ldconfig -p | grep -q libpq.so.5' \
        || fail "${image}: libpq.so.5 missing; PostgreSQL will fail to load Pgtcl"
    ok "libpq present (PostgreSQL driver can load)"

    $RUNTIME run --rm --entrypoint /bin/bash "$image" \
        -c 'command -v /usr/local/bin/entrypoint.sh >/dev/null' \
        || fail "${image}: entrypoint.sh not at /usr/local/bin"
    ok "entrypoint in place"

    if [ "$want_oracle" -eq 1 ]; then
        $RUNTIME run --rm --entrypoint /bin/bash "$image" -c 'sqlplus -v >/dev/null' \
            || fail "${image}: sqlplus not working"
        ok "Oracle Instant Client working"
    fi
}

if [ "$DO_VERIFY" -eq 1 ]; then
    verify_image "${BASE_IMAGE}:${PRIMARY_TAG}" 0
    [ "$BASE_ONLY" -eq 0 ] && verify_image "${ORACLE_IMAGE}:${PRIMARY_TAG}" 1
else
    log "skipping verification (--skip-verify)"
fi

# --- Tag -------------------------------------------------------------------
# Only after verification, so a broken build never claims :latest.
apply_tags() {
    local image="$1"
    $RUNTIME tag "${image}:${PRIMARY_TAG}" "${image}:${MAJOR_TAG}"
    $RUNTIME tag "${image}:${PRIMARY_TAG}" "${image}:${CLI_VERSION}-hdb${HDB_VERSION}"
    [ "$APPLY_LATEST" -eq 1 ] && $RUNTIME tag "${image}:${PRIMARY_TAG}" "${image}:latest"
    return 0
}

log "applying tags"
apply_tags "${BASE_IMAGE}"
[ "$BASE_ONLY" -eq 0 ] && apply_tags "${ORACLE_IMAGE}"

# --- Push ------------------------------------------------------------------
if [ "$DO_PUSH" -eq 1 ]; then
    [ "$REGISTRY" = "localhost" ] && fail "refusing to push to 'localhost'; pass --registry"
    push_tags() {
        local image="$1"
        for tag in "${PRIMARY_TAG}" "${MAJOR_TAG}" "${CLI_VERSION}-hdb${HDB_VERSION}" latest; do
            log "pushing ${image}:${tag}"
            $RUNTIME push "${image}:${tag}"
        done
    }
    push_tags "${BASE_IMAGE}"
    [ "$BASE_ONLY" -eq 0 ] && push_tags "${ORACLE_IMAGE}"
    log "push complete"
else
    echo
    log "built and verified. Not pushed."
    echo "  To push:  $0 --registry ${REGISTRY} --push"
fi

echo
$RUNTIME images --format "  {{.Repository}}:{{.Tag}}  {{.Size}}" \
    | grep -E "hammerdb-scale(-oracle)?:" | sort -u
