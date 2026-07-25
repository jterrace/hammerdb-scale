#!/bin/bash
# ============================================================================
# Oracle RMAN Backup Script
# ============================================================================
# Performs a cold (NOARCHIVELOG) RMAN backup across multiple Oracle hosts.
# Shuts down each database, backs up in MOUNT mode, then reopens.
#
# Usage:
#   ./rman_backup.sh                    # backup all 8 hosts in parallel
#   ./rman_backup.sh 01 04              # backup only oracle-01 and oracle-04
#   ./rman_backup.sh --sequential       # backup all hosts one at a time
#   ./rman_backup.sh --sequential 01 04 # sequential backup of specific hosts
#
# Prerequisites:
#   - sshpass installed on the runner
#   - NFS mount at /oracle-backup on all hosts
#   - Oracle user SSH access (password: Osmium76)
#   - Database in NOARCHIVELOG mode
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
SECTION_SIZE="4G"
FILESPERSET=1

# ── Parse arguments ───────────────────────────────────────────────────────
SEQUENTIAL=false
TARGETS=()

for arg in "$@"; do
    if [[ "$arg" == "--sequential" ]]; then
        SEQUENTIAL=true
    elif [[ -n "${HOST_MAP[$arg]+x}" ]]; then
        TARGETS+=("$arg")
    else
        echo "ERROR: Unknown argument '$arg'. Use host numbers (01-08) or --sequential."
        exit 1
    fi
done

if [[ ${#TARGETS[@]} -eq 0 ]]; then
    TARGETS=(01 02 03 04 05 06 07 08)
fi

# ── Functions ──────────────────────────────────────────────────────────────

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"
}

# Write the remote backup script to a local temp file, scp it, execute it.
# This avoids all heredoc/quoting issues over SSH.
run_backup() {
    local host_num=$1
    local ip="${HOST_MAP[$host_num]}"
    local backup_path="${BACKUP_BASE}/oracle-${host_num}"
    local local_tmp=$(mktemp /tmp/rman_backup_${host_num}_XXXX.sh)
    local start_epoch=$(date '+%s')

    log "oracle-${host_num} (${ip}): Starting backup"

    # ── Build the remote script ──
    cat > "$local_tmp" << 'SCRIPTEOF'
#!/bin/bash
source ~/.bash_profile

BACKUP_PATH="__BACKUP_PATH__"
CHANNELS=__CHANNELS__
SECTION_SIZE="__SECTION_SIZE__"
FILESPERSET=__FILESPERSET__

# Clean and prepare backup directory on NFS
mkdir -p "${BACKUP_PATH}"
rm -rf "${BACKUP_PATH}"/*

# Build RMAN command file
RMAN_CMD="/tmp/rman_backup_$$.rmn"

cat > "${RMAN_CMD}" << RMANEOF
CONNECT TARGET /

SHUTDOWN IMMEDIATE;
STARTUP MOUNT;

CONFIGURE CONTROLFILE AUTOBACKUP ON;
CONFIGURE CONTROLFILE AUTOBACKUP FORMAT FOR DEVICE TYPE DISK TO '${BACKUP_PATH}/%F';

RUN {
RMANEOF

# Allocate channels
for ((i=1; i<=CHANNELS; i++)); do
    echo "  ALLOCATE CHANNEL ch${i} DEVICE TYPE DISK FORMAT '${BACKUP_PATH}/%U';" >> "${RMAN_CMD}"
done

cat >> "${RMAN_CMD}" << RMANEOF

  BACKUP
    SECTION SIZE ${SECTION_SIZE}
    FILESPERSET ${FILESPERSET}
    DATABASE
    TAG 'FULL_DB_BACKUP';

  BACKUP CURRENT CONTROLFILE TAG 'CONTROLFILE_BACKUP';
  BACKUP SPFILE TAG 'SPFILE_BACKUP';

RMANEOF

# Release channels
for ((i=1; i<=CHANNELS; i++)); do
    echo "  RELEASE CHANNEL ch${i};" >> "${RMAN_CMD}"
done

cat >> "${RMAN_CMD}" << RMANEOF
}

ALTER DATABASE OPEN;
ALTER PLUGGABLE DATABASE ALL OPEN;

EXIT;
RMANEOF

# Run RMAN
RMAN_LOG="${BACKUP_PATH}/rman_backup_$(date '+%Y%m%d_%H%M%S').log"

echo "START_EPOCH=$(date '+%s')"

rman cmdfile="${RMAN_CMD}" log="${RMAN_LOG}"
RMAN_EXIT=$?

rm -f "${RMAN_CMD}"

# Report backup size
BACKUP_BYTES=$(du -sb "${BACKUP_PATH}" 2>/dev/null | awk '{print $1}')
echo "BACKUP_BYTES=${BACKUP_BYTES:-0}"

echo "END_EPOCH=$(date '+%s')"
echo "RMAN_EXIT=${RMAN_EXIT}"

exit ${RMAN_EXIT}
SCRIPTEOF

    # Substitute placeholders
    sed -i "s|__BACKUP_PATH__|${backup_path}|g" "$local_tmp"
    sed -i "s|__CHANNELS__|${CHANNELS}|g" "$local_tmp"
    sed -i "s|__SECTION_SIZE__|${SECTION_SIZE}|g" "$local_tmp"
    sed -i "s|__FILESPERSET__|${FILESPERSET}|g" "$local_tmp"

    # Copy script to remote host
    sshpass -p "$SSH_PASS" scp $SSH_OPTS "$local_tmp" "${SSH_USER}@${ip}:/tmp/rman_backup_run.sh" 2>/dev/null
    if [[ $? -ne 0 ]]; then
        log "oracle-${host_num} (${ip}): FAILED — could not copy script"
        rm -f "$local_tmp"
        return 1
    fi

    # Execute on remote host
    local output
    output=$(sshpass -p "$SSH_PASS" ssh $SSH_OPTS "${SSH_USER}@${ip}" \
        "chmod +x /tmp/rman_backup_run.sh && /tmp/rman_backup_run.sh && rm -f /tmp/rman_backup_run.sh" 2>&1)
    local exit_code=$?

    rm -f "$local_tmp"

    local end_epoch=$(date '+%s')
    local duration=$((end_epoch - start_epoch))

    # Parse metrics from output
    local backup_bytes=$(echo "$output" | grep '^BACKUP_BYTES=' | tail -1 | cut -d= -f2)
    local size_gb="0"
    if [[ -n "$backup_bytes" && "$backup_bytes" -gt 0 ]] 2>/dev/null; then
        size_gb=$(echo "scale=2; ${backup_bytes} / 1073741824" | bc 2>/dev/null || echo "0")
    fi

    local throughput="N/A"
    if [[ "$duration" -gt 0 && "$size_gb" != "0" ]]; then
        throughput=$(echo "scale=2; (${size_gb} * 1024) / ${duration}" | bc 2>/dev/null || echo "N/A")
    fi

    if [[ $exit_code -eq 0 ]]; then
        log "oracle-${host_num} (${ip}): SUCCESS — ${duration}s, ${size_gb} GB, ${throughput} MB/s"
    else
        log "oracle-${host_num} (${ip}): FAILED (exit code ${exit_code})"
        echo "$output" | grep -iE "ORA-|RMAN-|error|fail" | tail -10
    fi

    return $exit_code
}

# ── Main ───────────────────────────────────────────────────────────────────

echo "========================================="
echo "Oracle RMAN Backup"
echo "========================================="
echo "Mode:     $(if $SEQUENTIAL; then echo Sequential; else echo Parallel; fi)"
echo "Targets:  ${TARGETS[*]}"
echo "Channels: ${CHANNELS}"
echo "NFS path: ${BACKUP_BASE}"
echo "Start:    $(date '+%Y-%m-%d %H:%M:%S')"
echo "========================================="
echo ""

OVERALL_START=$(date '+%s')
PIDS=()
RESULTS=()
FAILED=0

if $SEQUENTIAL; then
    for num in "${TARGETS[@]}"; do
        if run_backup "$num"; then
            RESULTS+=("oracle-${num}: SUCCESS")
        else
            RESULTS+=("oracle-${num}: FAILED")
            FAILED=$((FAILED + 1))
        fi
    done
else
    for num in "${TARGETS[@]}"; do
        run_backup "$num" &
        PIDS+=("$!:${num}")
    done

    for entry in "${PIDS[@]}"; do
        pid="${entry%%:*}"
        num="${entry##*:}"
        if wait "$pid"; then
            RESULTS+=("oracle-${num}: SUCCESS")
        else
            RESULTS+=("oracle-${num}: FAILED")
            FAILED=$((FAILED + 1))
        fi
    done
fi

OVERALL_END=$(date '+%s')
OVERALL_DURATION=$((OVERALL_END - OVERALL_START))

echo ""
echo "========================================="
echo "Backup Summary"
echo "========================================="
printf "Total time: %ds (%s)\n" "$OVERALL_DURATION" "$(date -d@${OVERALL_DURATION} -u +%H:%M:%S 2>/dev/null || echo "${OVERALL_DURATION}s")"
echo "Targets:    ${#TARGETS[@]}"
echo "Succeeded:  $((${#TARGETS[@]} - FAILED))"
echo "Failed:     ${FAILED}"
echo ""
for r in "${RESULTS[@]}"; do
    echo "  $r"
done
echo "========================================="

exit $FAILED
