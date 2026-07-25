# Oracle Scale Test Environment

Hi Ganesh — this document describes the 8-node Oracle environment set up for HammerDB-Scale testing. Everything is pre-built and ready to go. You have 8 identical Oracle 26ai databases, each loaded with a 1TB TPC-C dataset, RMAN backups on a shared NFS mount, and YAML configs for running scale tests from 1 to 8 targets.


## Environment at a Glance

- **8x Oracle 26ai** (23.26.1.0.0) single-instance databases
- **10,000 TPC-C warehouses** per database (~1TB each)
- **RMAN cold backups** on NFS (~804GB per host, ~6.4TB total)
- **Kubernetes namespace:** `hammerdb-xl190`
- **FlashArray metrics:** enabled (10.21.158.130)


## Connecting to the Databases

All 8 databases are identical in layout. SSH in as the `oracle` user, or connect from HammerDB via the service name.

| Host | IP Address | Listener Port |
|------|------------|---------------|
| oracle-01 | 10.21.227.45 | 1521 |
| oracle-02 | 10.21.227.46 | 1521 |
| oracle-03 | 10.21.227.47 | 1521 |
| oracle-04 | 10.21.227.48 | 1521 |
| oracle-05 | 10.21.227.49 | 1521 |
| oracle-06 | 10.21.227.52 | 1521 |
| oracle-07 | 10.21.227.53 | 1521 |
| oracle-08 | 10.21.227.54 | 1521 |

**Credentials:**

| User | Password | Where |
|------|----------|-------|
| oracle (OS) | Osmium76 | SSH to any host |
| system | Osmium76 | CDB admin (sqlplus) |
| TPCC | Osmium76 | TPC-C schema owner (TPCC PDB) |

**Database structure on each host:**

```
CDB:  orcl
 └── PDB:  TPCC   (service: tpcc.puretec.purestorage.com)
      └── Schema: TPCC  (9 tables, 10K warehouses, ~1TB)
```

**Storage:**

| Diskgroup | Size | Contents |
|-----------|------|----------|
| +DATA01 | 1.6 TB | Datafiles, controlfiles |
| +REDO01 | 400 GB | 12 redo groups x 3 members x 4GB |
| +DATA02 | 1.6 TB | Unused (available) |
| +REDO02 | 400 GB | Unused (available) |

All databases are in **NOARCHIVELOG** mode.


## YAML Config Files

There are 8 config files, one for each scale point. They progressively add targets:

| Config File | Targets |
|-------------|---------|
| `oracle-scale-1.yaml` | oracle-01 |
| `oracle-scale-2.yaml` | oracle-01, 02 |
| `oracle-scale-3.yaml` | oracle-01, 02, 03 |
| `oracle-scale-4.yaml` | oracle-01, 02, 03, 04 |
| `oracle-scale-5.yaml` | oracle-01 through 05 |
| `oracle-scale-6.yaml` | oracle-01 through 06 |
| `oracle-scale-7.yaml` | oracle-01 through 07 |
| `oracle-scale-8.yaml` | oracle-01 through 08 |

All configs use the same benchmark parameters: 10,000 warehouses, 200 virtual users, timed driver with 5-minute rampup and 10-minute duration. Pure FlashArray storage metrics collection is enabled.


## Running a Scale Test

The schemas are already built on all 8 hosts — you do **not** need `--build` unless you want to rebuild from scratch.

```bash
# Step 1: Validate connectivity
hammerdb-scale validate -c oracle-scale-1.yaml

# Step 2: Run the benchmark
hammerdb-scale run -c oracle-scale-1.yaml --wait

# Step 3: Collect results
hammerdb-scale results -c oracle-scale-1.yaml

# Step 4: Generate HTML scorecard
hammerdb-scale report -c oracle-scale-1.yaml --open
```

Then move on to the next scale point (`oracle-scale-2.yaml`, etc.).


## Backup and Restore

RMAN cold backups already exist for all 8 hosts on a shared NFS mount at `/oracle-backup`. Use the scripts in `scripts/oracle/` to manage them.

### Taking a Backup

The backup script shuts down each database, backs up in MOUNT mode, then reopens it. By default it runs all hosts in parallel and takes about 12 minutes.

```bash
# Backup all 8 hosts in parallel
./scripts/oracle/rman_backup.sh

# Backup only specific hosts
./scripts/oracle/rman_backup.sh 01 04

# Backup one at a time instead of parallel
./scripts/oracle/rman_backup.sh --sequential
```

### Restoring from Backup

```bash
# Restore a host from its own backup
./scripts/oracle/rman_restore.sh 04

# Restore multiple hosts
./scripts/oracle/rman_restore.sh 03 04 05

# Restore oracle-04 using oracle-01's backup (redirected restore)
./scripts/oracle/rman_restore.sh 04 --from 01
```

The restore script shuts down the database, restores from the NFS backup, recovers, and opens with RESETLOGS. It verifies the CDB and PDB are open when done.

### When Should You Restore?

- **Between benchmark runs** if you need the data in a clean, pre-test state
- **After a crash or issue** to get a host back to a known good state
- **To clone a host** — use `--from` to restore one host's backup onto another

### When Should You Re-backup?

- After rebuilding schemas with `hammerdb-scale run --build`
- The backup overwrites the previous one, so just run `./scripts/oracle/rman_backup.sh`


## Suggested Workflow: Full Scale Run (1 through 8)

```
For each scale point (1, 2, 3, ... 8):
  1. Restore the databases that will be used  →  ./scripts/oracle/rman_restore.sh 01 02 ...
  2. Validate                                 →  hammerdb-scale validate -c oracle-scale-N.yaml
  3. Run                                      →  hammerdb-scale run -c oracle-scale-N.yaml --wait
  4. Collect results                          →  hammerdb-scale results -c oracle-scale-N.yaml
  5. Generate report                          →  hammerdb-scale report -c oracle-scale-N.yaml
```

If you don't need a clean restore between runs, you can skip step 1.


## Things to Know

**Service name must be the FQDN.** The databases have `db_domain=puretec.purestorage.com`, so the listener registers the service as `tpcc.puretec.purestorage.com`. All YAML configs already have this set correctly. If you create new configs, make sure to use the full name — bare `tpcc` will fail with ORA-12514.

**Listeners don't auto-start after reboot.** They're not managed by CRS. If a host gets rebooted, SSH in as `oracle` and run `lsnrctl start`.

**NFS mount for RMAN.** All hosts mount the backup NFS share at `/oracle-backup` with options `noac,nconnect=8`. Oracle 26ai has a strict NFS validation check — event 10298 level 32 is set in the SPFILE on all hosts to bypass it. Don't remove this event or RMAN writes to NFS will fail with ORA-27054.

**Redo log layout.** Each host has 12 redo groups x 3 members x 4GB, all on +REDO01. If you ever need to rebuild this layout, use `sqlplus / as sysdba @scripts/oracle/setup_redo.sql` on the host.

**Oracle-04 had a crash.** It was terminated by LMHB (ORA-484, hung process) during an earlier schema build. It has been rebuilt and is now healthy with a complete dataset and backup. If it acts up again, restore it: `./scripts/oracle/rman_restore.sh 04`
