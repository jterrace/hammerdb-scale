#!/bin/bash
# Provision a PostgreSQL benchmark host for HammerDB TPROC-C / TPROC-H.
#
# Idempotent: safe to re-run. With --force it wipes any existing cluster and
# rebuilds from scratch, which is what makes a fleet provably identical rather
# than "whatever was there before".
#
# Target hardware (the PostgreSQL-Bench fleet):
#   RHEL 9.x, 48 cores, 125GB RAM, dedicated volume mounted at /var/lib/pgsql
#
# Usage:
#   ./provision_postgres.sh [--force] [--version 18] [--password PW]

set -euo pipefail

PG_VERSION="${PG_VERSION:-18}"
PG_PASSWORD="${PG_PASSWORD:-Osmium76}"
FORCE=0

while [[ $# -gt 0 ]]; do
    case "$1" in
        --force)    FORCE=1; shift ;;
        --version)  PG_VERSION="$2"; shift 2 ;;
        --password) PG_PASSWORD="$2"; shift 2 ;;
        *) echo "Unknown option: $1" >&2; exit 1 ;;
    esac
done

PGBIN="/usr/pgsql-${PG_VERSION}/bin"
PGDATA="/var/lib/pgsql/${PG_VERSION}/data"
SERVICE="postgresql-${PG_VERSION}"

log() { echo "[$(date +'%H:%M:%S')] $*"; }

# --- Sizing, derived from the actual host ---------------------------------
TOTAL_MB=$(free -m | awk '/^Mem:/{print $2}')
CPUS=$(nproc)

# PostgreSQL guidance: shared_buffers ~25% of RAM, effective_cache_size ~75%.
SHARED_BUFFERS_MB=$(( TOTAL_MB / 4 ))
EFFECTIVE_CACHE_MB=$(( TOTAL_MB * 3 / 4 ))
MAINTENANCE_WORK_MEM_MB=2048
# TPROC-C is short OLTP transactions, so work_mem stays modest; a large value
# here multiplies per sort node across hundreds of connections.
WORK_MEM_MB=64

MAX_PARALLEL=$(( CPUS * 5 / 6 ))
PARALLEL_PER_GATHER=$(( CPUS / 6 ))
[ "$PARALLEL_PER_GATHER" -lt 2 ] && PARALLEL_PER_GATHER=2

log "Host: ${CPUS} cores, ${TOTAL_MB}MB RAM"
log "Sizing: shared_buffers=${SHARED_BUFFERS_MB}MB effective_cache_size=${EFFECTIVE_CACHE_MB}MB"

# --- Install ---------------------------------------------------------------
if ! rpm -q "postgresql${PG_VERSION}-server" >/dev/null 2>&1; then
    log "Installing PostgreSQL ${PG_VERSION} from PGDG"
    dnf install -y \
        "https://download.postgresql.org/pub/repos/yum/reporpms/EL-9-x86_64/pgdg-redhat-repo-latest.noarch.rpm" \
        >/dev/null 2>&1 || true
    # The PGDG repo ships its own libpq; RHEL's AppStream module would shadow it.
    dnf -qy module disable postgresql >/dev/null 2>&1 || true
    dnf install -y \
        "postgresql${PG_VERSION}-server" \
        "postgresql${PG_VERSION}-contrib" >/dev/null
    log "Installed $(rpm -q postgresql${PG_VERSION}-server)"
else
    log "Already installed: $(rpm -q postgresql${PG_VERSION}-server)"
fi

# --- Cluster ---------------------------------------------------------------
if [ -s "${PGDATA}/PG_VERSION" ] && [ "$FORCE" -eq 1 ]; then
    log "--force: removing existing cluster at ${PGDATA}"
    systemctl stop "$SERVICE" 2>/dev/null || true
    rm -rf "${PGDATA:?}"/*
fi

if [ ! -s "${PGDATA}/PG_VERSION" ]; then
    log "Initialising cluster"
    # Checksums cost a little CPU but make silent storage corruption visible,
    # which matters when the point of the exercise is testing storage.
    PGSETUP_INITDB_OPTIONS="--data-checksums" \
        "${PGBIN}/postgresql-${PG_VERSION}-setup" initdb >/dev/null
else
    log "Cluster already initialised"
fi

# --- Configuration ---------------------------------------------------------
# Written as a conf.d drop-in rather than ALTER SYSTEM so the settings are
# visible in the repo, reproducible, and easy to diff across the fleet.
log "Writing tuning configuration"
mkdir -p "${PGDATA}/conf.d"
cat > "${PGDATA}/conf.d/hammerdb.conf" <<EOF
# Managed by provision_postgres.sh. Do not edit by hand.
# Tuned for HammerDB TPROC-C on ${CPUS} cores / ${TOTAL_MB}MB RAM.

listen_addresses = '*'
max_connections = 500                  # headroom above the benchmark's VU count

# Memory
shared_buffers = ${SHARED_BUFFERS_MB}MB
effective_cache_size = ${EFFECTIVE_CACHE_MB}MB
maintenance_work_mem = ${MAINTENANCE_WORK_MEM_MB}MB
work_mem = ${WORK_MEM_MB}MB

# WAL and checkpoints. TPROC-C is write-heavy: small max_wal_size forces
# constant checkpoints, which shows up as latency spikes rather than as a
# property of the storage under test.
wal_buffers = 64MB
min_wal_size = 4GB
max_wal_size = 32GB
checkpoint_timeout = 15min
checkpoint_completion_target = 0.9
synchronous_commit = on                # keep durability honest for a storage test

# Storage assumptions: flash array, so random access is not penalised and
# deep queues are useful.
random_page_cost = 1.1
effective_io_concurrency = 200
maintenance_io_concurrency = 200

# Parallelism
max_worker_processes = ${CPUS}
max_parallel_workers = ${MAX_PARALLEL}
max_parallel_workers_per_gather = ${PARALLEL_PER_GATHER}
max_parallel_maintenance_workers = 4

# Autovacuum: TPROC-C generates heavy row churn, so the default single-worker
# pace falls behind and bloat distorts later results.
autovacuum_max_workers = 8
autovacuum_naptime = 15s
autovacuum_vacuum_cost_limit = 3000

# Logging
logging_collector = on
log_directory = 'log'
log_filename = 'postgresql-%a.log'
log_truncate_on_rotation = on
log_checkpoints = on
log_autovacuum_min_duration = 0
EOF

# Ensure the drop-in is actually read; a stock postgresql.conf does not include it.
if ! grep -q "include_dir = 'conf.d'" "${PGDATA}/postgresql.conf"; then
    echo "include_dir = 'conf.d'" >> "${PGDATA}/postgresql.conf"
fi

# --- Authentication --------------------------------------------------------
log "Configuring pg_hba.conf for remote benchmark clients"
if ! grep -q "hammerdb-scale" "${PGDATA}/pg_hba.conf"; then
    cat >> "${PGDATA}/pg_hba.conf" <<'EOF'

# hammerdb-scale: allow benchmark clients from the lab network.
host    all             all             10.0.0.0/8              scram-sha-256
EOF
fi

# --- Firewall --------------------------------------------------------------
# RHEL runs firewalld by default with only ssh open, so PostgreSQL listening on
# 0.0.0.0 is still unreachable from the benchmark clients without this.
if systemctl is-active --quiet firewalld 2>/dev/null; then
    if ! firewall-cmd --list-ports 2>/dev/null | grep -q "5432/tcp"; then
        log "Opening 5432/tcp in firewalld"
        firewall-cmd --permanent --add-port=5432/tcp >/dev/null
        firewall-cmd --reload >/dev/null
    else
        log "firewalld already allows 5432/tcp"
    fi
else
    log "firewalld inactive; no firewall change needed"
fi

# --- Start -----------------------------------------------------------------
log "Starting ${SERVICE}"
systemctl enable "$SERVICE" >/dev/null 2>&1
systemctl restart "$SERVICE"

for _ in $(seq 1 30); do
    "${PGBIN}/pg_isready" -q && break
    sleep 2
done
"${PGBIN}/pg_isready" >/dev/null || { log "ERROR: server did not become ready"; exit 1; }

# --- Benchmark role --------------------------------------------------------
# HammerDB creates the tpcc schema itself but needs a superuser to do so.
log "Ensuring benchmark role exists"
sudo -u postgres "${PGBIN}/psql" -qtAc \
    "DO \$\$ BEGIN
       IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'postgres') THEN
         CREATE ROLE postgres SUPERUSER LOGIN;
       END IF;
     END \$\$;" >/dev/null

sudo -u postgres "${PGBIN}/psql" -qtAc \
    "ALTER ROLE postgres WITH PASSWORD '${PG_PASSWORD}'" >/dev/null

log "Ready: $(sudo -u postgres ${PGBIN}/psql -tAc 'select version()' | cut -c1-40)"
log "shared_buffers=$(sudo -u postgres ${PGBIN}/psql -tAc 'show shared_buffers')"
