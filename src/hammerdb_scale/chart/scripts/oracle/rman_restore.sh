#!/bin/bash
# ============================================================================
# Oracle RMAN Restore Script
# ============================================================================
# Restores a cold RMAN backup from the NFS share to an Oracle host.
#
# Usage:
#   ./rman_restore.sh 04                    # restore oracle-04 from its own backup
#   ./rman_restore.sh 04 --from 01          # restore oracle-04 using oracle-01's backup
#   ./rman_restore.sh 03 04 05              # restore multiple hosts from own backups
#
# Redirected restore (--from):
#   Copies backup pieces from the source host's NFS dir to the target,
#   then uses RMAN DUPLICATE to clone the database. This works across
#   different DBIDs because DUPLICATE creates a new database from the
#   backup rather than trying to restore into the existing controlfile.
#
#   NOTE: Redirected restore requires the source database to be accessible
#   (for RMAN to read the backup metadata). If the source is down, use
#   a normal restore from the target's own backup instead.
#
# Prerequisites:
#   - sshpass installed on the runner
#   - NFS mount at /oracle-backup on all hosts
#   - Oracle user SSH access (password: Osmium76)
#   - Backup exists in /oracle-backup/oracle-NN/
#   - Same ASM diskgroup layout (+DATA01, +REDO01) on all hosts
# ============================================================================

# ── Configuration ──────────────────────────────────────────────────────────
declare -A HOST_MAP=(
    [01]="10.21.227.45"
    [02]="10.21.227.46"
    [03]="10.21.227.47"
    [04]="10.21.227.48"
    [05]="10.21.227.49"
    [06]="10.21.227.52"
    [07]="10.21.227.53"
    [08]="10.21.227.54"
)

SSH_USER="oracle"
SSH_PASS="Osmium76"
SSH_OPTS="-o StrictHostKeyChecking=no -o ConnectTimeout=10"
BACKUP_BASE="/oracle-backup"
CHANNELS=32

# ── Parse arguments ───────────────────────────────────────────────────────
FROM_HOST=""
TARGETS=()

while [[ $# -gt 0 ]]; do
    case "$1" in
        --from)
            FROM_HOST="$2"
            if [[ -z "${HOST_MAP[$FROM_HOST]+x}" ]]; then
                echo "ERROR: Invalid source host '$FROM_HOST'"
                exit 1
            fi
            shift 2
            ;;
        *)
            if [[ -n "${HOST_MAP[$1]+x}" ]]; then
                TARGETS+=("$1")
            else
                echo "ERROR: Unknown argument '$1'. Use host numbers (01-08) or --from NN."
                exit 1
            fi
            shift
            ;;
    esac
done

if [[ ${#TARGETS[@]} -eq 0 ]]; then
    echo "Usage: $0 <host_num> [host_num ...] [--from source_host_num]"
    echo ""
    echo "Examples:"
    echo "  $0 04                  # restore oracle-04 from its own backup"
    echo "  $0 04 --from 01        # restore oracle-04 using oracle-01's backup"
    echo "  $0 03 04 05            # restore multiple hosts from own backups"
    exit 1
fi

if [[ -n "$FROM_HOST" && ${#TARGETS[@]} -gt 1 ]]; then
    echo "ERROR: --from can only be used with a single target host"
    exit 1
fi

# ── Functions ──────────────────────────────────────────────────────────────

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"
}

# Standard restore: restore the host's own backup
run_restore_own() {
    local target_num=$1
    local target_ip="${HOST_MAP[$target_num]}"
    local backup_path="${BACKUP_BASE}/oracle-${target_num}"
    local local_tmp=$(mktemp /tmp/rman_restore_${target_num}_XXXX.sh)
    local start_epoch=$(date '+%s')

    log "oracle-${target_num} (${target_ip}): Restoring from own backup"

    cat > "$local_tmp" << 'SCRIPTEOF'
#!/bin/bash
source ~/.bash_profile

BACKUP_PATH="__BACKUP_PATH__"
CHANNELS=__CHANNELS__

# Verify backup exists
if [[ ! -d "${BACKUP_PATH}" ]] || [[ -z "$(ls -A ${BACKUP_PATH}/ 2>/dev/null)" ]]; then
    echo "ERROR: No backup found at ${BACKUP_PATH}"
    exit 1
fi

echo "Backup files found: $(ls ${BACKUP_PATH}/ | wc -l)"

# Build RMAN command file
RMAN_CMD="/tmp/rman_restore_$$.rmn"

cat > "${RMAN_CMD}" << RMANEOF
CONNECT TARGET /

SHUTDOWN ABORT;
STARTUP MOUNT;

RUN {
RMANEOF

for ((i=1; i<=CHANNELS; i++)); do
    echo "  ALLOCATE CHANNEL ch${i} DEVICE TYPE DISK;" >> "${RMAN_CMD}"
done

cat >> "${RMAN_CMD}" << RMANEOF

  RESTORE DATABASE;
  RECOVER DATABASE;

RMANEOF

for ((i=1; i<=CHANNELS; i++)); do
    echo "  RELEASE CHANNEL ch${i};" >> "${RMAN_CMD}"
done

cat >> "${RMAN_CMD}" << RMANEOF
}

ALTER DATABASE OPEN RESETLOGS;
ALTER PLUGGABLE DATABASE ALL OPEN;

EXIT;
RMANEOF

# Run RMAN
RMAN_LOG="${BACKUP_PATH}/rman_restore_$(date '+%Y%m%d_%H%M%S').log"
rman cmdfile="${RMAN_CMD}" log="${RMAN_LOG}"
RMAN_EXIT=$?
rm -f "${RMAN_CMD}"

# Verify
sqlplus -s / as sysdba << SQLEOF
SET HEADING OFF FEEDBACK OFF PAGESIZE 0
SELECT 'DB_STATUS=' || status FROM v\$instance;
SELECT 'PDB_STATUS=' || name || '=' || open_mode FROM v\$pdbs;
SQLEOF

echo "RMAN_EXIT=${RMAN_EXIT}"
exit ${RMAN_EXIT}
SCRIPTEOF

    sed -i "s|__BACKUP_PATH__|${backup_path}|g" "$local_tmp"
    sed -i "s|__CHANNELS__|${CHANNELS}|g" "$local_tmp"

    sshpass -p "$SSH_PASS" scp $SSH_OPTS "$local_tmp" "${SSH_USER}@${target_ip}:/tmp/rman_restore_run.sh" 2>/dev/null
    if [[ $? -ne 0 ]]; then
        log "oracle-${target_num}: FAILED — could not copy script"
        rm -f "$local_tmp"
        return 1
    fi

    local output
    output=$(sshpass -p "$SSH_PASS" ssh $SSH_OPTS "${SSH_USER}@${target_ip}" \
        "chmod +x /tmp/rman_restore_run.sh && /tmp/rman_restore_run.sh && rm -f /tmp/rman_restore_run.sh" 2>&1)
    local exit_code=$?

    rm -f "$local_tmp"

    local end_epoch=$(date '+%s')
    local duration=$((end_epoch - start_epoch))

    if [[ $exit_code -eq 0 ]]; then
        log "oracle-${target_num}: SUCCESS — ${duration}s"
        echo "$output" | grep -E "^(DB_STATUS=|PDB_STATUS=)"
    else
        log "oracle-${target_num}: FAILED (exit code ${exit_code})"
        echo "$output" | grep -iE "ORA-|RMAN-|error|fail" | tail -10
    fi

    return $exit_code
}

# Redirected restore: copy backup from source, use RMAN DUPLICATE
run_restore_from() {
    local target_num=$1
    local source_num=$FROM_HOST
    local target_ip="${HOST_MAP[$target_num]}"
    local source_ip="${HOST_MAP[$source_num]}"
    local source_path="${BACKUP_BASE}/oracle-${source_num}"
    local target_path="${BACKUP_BASE}/oracle-${target_num}"
    local local_tmp=$(mktemp /tmp/rman_restore_${target_num}_XXXX.sh)
    local start_epoch=$(date '+%s')

    log "oracle-${target_num} (${target_ip}): Redirected restore FROM oracle-${source_num} (${source_ip})"

    cat > "$local_tmp" << 'SCRIPTEOF'
#!/bin/bash
source ~/.bash_profile

SOURCE_PATH="__SOURCE_PATH__"
TARGET_PATH="__TARGET_PATH__"
CHANNELS=__CHANNELS__

# Copy backup pieces from source to target directory
echo "Copying backup from ${SOURCE_PATH} to ${TARGET_PATH}..."
mkdir -p "${TARGET_PATH}"
rm -f "${TARGET_PATH}"/*
cp "${SOURCE_PATH}"/* "${TARGET_PATH}/" 2>/dev/null
FILE_COUNT=$(ls "${TARGET_PATH}" | wc -l)
echo "Copied ${FILE_COUNT} files"

if [[ ${FILE_COUNT} -eq 0 ]]; then
    echo "ERROR: No backup files copied"
    exit 1
fi

# Shut down existing database
echo "Shutting down existing database..."
sqlplus -s / as sysdba << SQLEOF
SHUTDOWN ABORT;
SQLEOF

# Find the controlfile autobackup in the backup set
CTLFILE=$(ls "${TARGET_PATH}"/c-*-* 2>/dev/null | head -1)
if [[ -z "${CTLFILE}" ]]; then
    echo "ERROR: No controlfile autobackup found in ${TARGET_PATH}"
    exit 1
fi
echo "Found controlfile backup: ${CTLFILE}"

# Build RMAN command file
RMAN_CMD="/tmp/rman_restore_$$.rmn"

cat > "${RMAN_CMD}" << RMANEOF
CONNECT TARGET /

STARTUP NOMOUNT;

# Restore controlfile from source backup
RESTORE CONTROLFILE FROM '${CTLFILE}';
ALTER DATABASE MOUNT;

# Catalog all backup pieces in the target path
CATALOG START WITH '${TARGET_PATH}/' NOPROMPT;

RUN {
RMANEOF

for ((i=1; i<=CHANNELS; i++)); do
    echo "  ALLOCATE CHANNEL ch${i} DEVICE TYPE DISK;" >> "${RMAN_CMD}"
done

cat >> "${RMAN_CMD}" << RMANEOF

  RESTORE DATABASE;
  RECOVER DATABASE;

RMANEOF

for ((i=1; i<=CHANNELS; i++)); do
    echo "  RELEASE CHANNEL ch${i};" >> "${RMAN_CMD}"
done

cat >> "${RMAN_CMD}" << RMANEOF
}

ALTER DATABASE OPEN RESETLOGS;
ALTER PLUGGABLE DATABASE ALL OPEN;

EXIT;
RMANEOF

# Run RMAN
RMAN_LOG="${TARGET_PATH}/rman_restore_$(date '+%Y%m%d_%H%M%S').log"
rman cmdfile="${RMAN_CMD}" log="${RMAN_LOG}"
RMAN_EXIT=$?
rm -f "${RMAN_CMD}"

# Verify
sqlplus -s / as sysdba << SQLEOF
SET HEADING OFF FEEDBACK OFF PAGESIZE 0
SELECT 'DB_STATUS=' || status FROM v\$instance;
SELECT 'PDB_STATUS=' || name || '=' || open_mode FROM v\$pdbs;
SQLEOF

echo "RMAN_EXIT=${RMAN_EXIT}"
exit ${RMAN_EXIT}
SCRIPTEOF

    sed -i "s|__SOURCE_PATH__|${source_path}|g" "$local_tmp"
    sed -i "s|__TARGET_PATH__|${target_path}|g" "$local_tmp"
    sed -i "s|__CHANNELS__|${CHANNELS}|g" "$local_tmp"

    sshpass -p "$SSH_PASS" scp $SSH_OPTS "$local_tmp" "${SSH_USER}@${target_ip}:/tmp/rman_restore_run.sh" 2>/dev/null
    if [[ $? -ne 0 ]]; then
        log "oracle-${target_num}: FAILED — could not copy script"
        rm -f "$local_tmp"
        return 1
    fi

    local output
    output=$(sshpass -p "$SSH_PASS" ssh $SSH_OPTS "${SSH_USER}@${target_ip}" \
        "chmod +x /tmp/rman_restore_run.sh && /tmp/rman_restore_run.sh && rm -f /tmp/rman_restore_run.sh" 2>&1)
    local exit_code=$?

    rm -f "$local_tmp"

    local end_epoch=$(date '+%s')
    local duration=$((end_epoch - start_epoch))

    if [[ $exit_code -eq 0 ]]; then
        log "oracle-${target_num}: SUCCESS — ${duration}s"
        echo "$output" | grep -E "^(DB_STATUS=|PDB_STATUS=)"
    else
        log "oracle-${target_num}: FAILED (exit code ${exit_code})"
        echo "$output" | grep -iE "ORA-|RMAN-|error|fail" | tail -15
    fi

    return $exit_code
}

# ── Main ───────────────────────────────────────────────────────────────────

echo "========================================="
echo "Oracle RMAN Restore"
echo "========================================="
echo "Targets:  ${TARGETS[*]}"
if [[ -n "$FROM_HOST" ]]; then
    echo "Source:   oracle-${FROM_HOST}"
    echo "Method:   Redirected restore (controlfile + catalog)"
else
    echo "Method:   Standard restore (own backup)"
fi
echo "Channels: ${CHANNELS}"
echo "NFS path: ${BACKUP_BASE}"
echo "Start:    $(date '+%Y-%m-%d %H:%M:%S')"
echo "========================================="
echo ""

FAILED=0
RESULTS=()

for num in "${TARGETS[@]}"; do
    if [[ -n "$FROM_HOST" ]]; then
        if run_restore_from "$num"; then
            RESULTS+=("oracle-${num}: SUCCESS")
        else
            RESULTS+=("oracle-${num}: FAILED")
            FAILED=$((FAILED + 1))
        fi
    else
        if run_restore_own "$num"; then
            RESULTS+=("oracle-${num}: SUCCESS")
        else
            RESULTS+=("oracle-${num}: FAILED")
            FAILED=$((FAILED + 1))
        fi
    fi
done

echo ""
echo "========================================="
echo "Restore Summary"
echo "========================================="
for r in "${RESULTS[@]}"; do
    echo "  $r"
done
echo "========================================="

exit $FAILED
