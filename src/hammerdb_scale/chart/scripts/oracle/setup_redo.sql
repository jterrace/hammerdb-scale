-- ============================================================================
-- Oracle Redo Log Layout Setup
-- ============================================================================
-- Creates a standardized redo log layout:
--   12 groups x 3 members each x 4GB on +REDO01
--
-- Usage:
--   sqlplus / as sysdba @setup_redo.sql
--
-- Prerequisites:
--   - ASM diskgroup +REDO01 must exist
--   - Database must be OPEN
--   - Run as SYSDBA from CDB$ROOT
--
-- The script is idempotent: it will drop and recreate all groups.
-- It handles CURRENT/ACTIVE groups by cycling log switches.
-- ============================================================================

SET SERVEROUTPUT ON SIZE UNLIMITED
SET FEEDBACK OFF
SET ECHO OFF

WHENEVER SQLERROR CONTINUE

-- Configure online log destination
ALTER SYSTEM SET db_create_online_log_dest_1='+REDO01' SCOPE=BOTH;

PROMPT
PROMPT ============================================================
PROMPT  Current redo log layout (BEFORE)
PROMPT ============================================================

SELECT group#, members, bytes/1024/1024 size_mb, status
FROM v$log ORDER BY group#;

PROMPT
PROMPT ============================================================
PROMPT  Rebuilding redo logs: 12 groups x 3 members x 4GB on +REDO01
PROMPT ============================================================

DECLARE
  v_target_groups   CONSTANT PLS_INTEGER := 12;
  v_target_members  CONSTANT PLS_INTEGER := 3;
  v_target_size     CONSTANT VARCHAR2(10) := '4G';
  v_target_dg       CONSTANT VARCHAR2(20) := '+REDO01';
  v_status          VARCHAR2(20);
  v_attempts        PLS_INTEGER;
  v_max_group       PLS_INTEGER;
BEGIN
  -- Phase 1: Drop all existing groups (cycle switches for CURRENT/ACTIVE)
  DBMS_OUTPUT.PUT_LINE('--- Phase 1: Dropping existing groups ---');

  SELECT NVL(MAX(group#), 0) INTO v_max_group FROM v$log;

  FOR g IN 1..GREATEST(v_max_group, v_target_groups) LOOP
    BEGIN
      SELECT status INTO v_status FROM v$log WHERE group# = g;
    EXCEPTION
      WHEN NO_DATA_FOUND THEN
        DBMS_OUTPUT.PUT_LINE('Group ' || g || ': does not exist, skipping');
        CONTINUE;
    END;

    -- If CURRENT or ACTIVE, cycle log switches until it becomes INACTIVE
    IF v_status IN ('CURRENT', 'ACTIVE') THEN
      v_attempts := 0;
      WHILE v_status IN ('CURRENT', 'ACTIVE') AND v_attempts < 20 LOOP
        EXECUTE IMMEDIATE 'ALTER SYSTEM SWITCH LOGFILE';
        EXECUTE IMMEDIATE 'ALTER SYSTEM CHECKPOINT';
        DBMS_LOCK.SLEEP(1);
        SELECT status INTO v_status FROM v$log WHERE group# = g;
        v_attempts := v_attempts + 1;
      END LOOP;

      IF v_status IN ('CURRENT', 'ACTIVE') THEN
        DBMS_OUTPUT.PUT_LINE('ERROR: Group ' || g || ' still ' || v_status || ' after ' || v_attempts || ' switches');
        CONTINUE;
      END IF;
    END IF;

    EXECUTE IMMEDIATE 'ALTER DATABASE DROP LOGFILE GROUP ' || g;
    DBMS_OUTPUT.PUT_LINE('Group ' || g || ': dropped (' || v_status || ')');
  END LOOP;

  -- Phase 2: Create new groups with correct layout
  DBMS_OUTPUT.PUT_LINE('');
  DBMS_OUTPUT.PUT_LINE('--- Phase 2: Creating ' || v_target_groups || ' groups ---');

  FOR g IN 1..v_target_groups LOOP
    -- Create group with 1 member (goes to db_create_online_log_dest_1 = +REDO01)
    EXECUTE IMMEDIATE 'ALTER DATABASE ADD LOGFILE GROUP ' || g || ' SIZE ' || v_target_size;

    -- Add remaining members
    FOR m IN 2..v_target_members LOOP
      EXECUTE IMMEDIATE 'ALTER DATABASE ADD LOGFILE MEMBER ''' || v_target_dg || ''' TO GROUP ' || g;
    END LOOP;

    DBMS_OUTPUT.PUT_LINE('Group ' || g || ': created with ' || v_target_members || ' members');
  END LOOP;

  DBMS_OUTPUT.PUT_LINE('');
  DBMS_OUTPUT.PUT_LINE('--- Done ---');
END;
/

PROMPT
PROMPT ============================================================
PROMPT  Final redo log layout (AFTER)
PROMPT ============================================================

SELECT group#, members, bytes/1024/1024 size_mb, status
FROM v$log ORDER BY group#;

COL member FORMAT A70
SELECT group#, member FROM v$logfile ORDER BY group#, member;

EXIT;
