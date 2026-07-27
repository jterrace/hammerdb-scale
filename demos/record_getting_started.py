#!/usr/bin/env python3.11
"""Record the 'Getting Started' asciinema demo for hammerdb-scale.

Drives the interactive wizard via pexpect with realistic typing delays,
all inside an asciinema recording session.
"""

import os
import sys
import time

import pexpect

# ── Config ──────────────────────────────────────────────────────────────
CAST_FILE = os.path.join(os.path.dirname(__file__), "getting-started.cast")
YAML_OUTPUT = "/tmp/hammerdb-scale-demo.yaml"

# Typing speed (seconds per character)
FAST = 0.04
NORMAL = 0.06
PAUSE = 0.8  # pause between commands
LONG_PAUSE = 1.5

HOSTS = [
    ("sql-bench-01", "sql-bench-01.soln.local"),
    ("sql-bench-02", "sql-bench-02.soln.local"),
    ("sql-bench-03", "sql-bench-03.soln.local"),
    ("sql-bench-04", "sql-bench-04.soln.local"),
    ("sql-bench-05", "sql-bench-05.soln.local"),
    ("sql-bench-06", "sql-bench-06.soln.local"),
    ("sql-bench-07", "sql-bench-07.soln.local"),
    ("sql-bench-08", "sql-bench-08.soln.local"),
]


def typed(child, text, speed=NORMAL):
    """Send text character by character with delay."""
    for ch in text:
        child.send(ch)
        time.sleep(speed)
    time.sleep(0.15)


def enter(child):
    """Press Enter."""
    child.send("\r")
    time.sleep(0.3)


def type_and_enter(child, text, speed=NORMAL):
    """Type text then press Enter."""
    typed(child, text, speed)
    enter(child)


def wait_for(child, pattern, timeout=30):
    """Wait for a pattern in output."""
    child.expect(pattern, timeout=timeout)
    time.sleep(0.2)


def main():
    # Clean up any previous output
    if os.path.exists(YAML_OUTPUT):
        os.remove(YAML_OUTPUT)

    # Set terminal size for clean recording
    os.environ["COLUMNS"] = "100"
    os.environ["LINES"] = "30"

    # Start asciinema recording wrapping a bash shell
    child = pexpect.spawn(
        f"asciinema rec --cols 100 --rows 30 --idle-time-limit 2 "
        f"--title 'hammerdb-scale: Getting Started' "
        f"--overwrite {CAST_FILE}",
        encoding="utf-8",
        timeout=60,
    )
    child.setwinsize(30, 100)

    # Wait for shell prompt
    wait_for(child, r"[\$#]")
    time.sleep(PAUSE)

    # ── Step 0: pip install (quick show) ────────────────────────────────
    type_and_enter(child, "pip install hammerdb-scale", FAST)
    wait_for(child, r"[\$#]", timeout=60)
    time.sleep(PAUSE)

    # ── Step 1: init wizard ─────────────────────────────────────────────
    type_and_enter(
        child,
        f"hammerdb-scale init -i -o {YAML_OUTPUT} --force",
        FAST,
    )

    # Step 1: Deployment name
    wait_for(child, r"Deployment name")
    time.sleep(0.5)
    type_and_enter(child, "mssql-8-tprocc-demo", FAST)

    # Step 2: Database type — select 2 for MSSQL
    wait_for(child, r"Database type")
    time.sleep(0.4)
    type_and_enter(child, "2", FAST)

    # Benchmark — select 1 for TPC-C
    wait_for(child, r"Benchmark")
    time.sleep(0.4)
    type_and_enter(child, "1", FAST)

    # Step 3: Number of targets
    wait_for(child, r"Number of database targets")
    time.sleep(0.4)
    type_and_enter(child, "8", FAST)

    # Enter all 8 hosts
    for i, (name, host) in enumerate(HOSTS):
        wait_for(child, r"Name")
        time.sleep(0.2)
        type_and_enter(child, name, FAST)
        wait_for(child, r"Hostname or IP")
        time.sleep(0.2)
        type_and_enter(child, host, FAST)

    # Step 4: Credentials
    wait_for(child, r"Database username")
    time.sleep(0.4)
    # Accept default "sa"
    enter(child)

    wait_for(child, r"Database password")
    time.sleep(0.3)
    type_and_enter(child, "Osmium76", FAST)

    # Step 5: Warehouses
    wait_for(child, r"Warehouses per target")
    time.sleep(0.4)
    type_and_enter(child, "10", FAST)

    # Step 6: Namespace
    wait_for(child, r"Kubernetes namespace")
    time.sleep(0.4)
    # Accept default "hammerdb"
    enter(child)

    # Pure Storage metrics
    wait_for(child, r"Pure Storage")
    time.sleep(0.3)
    # Default is No
    enter(child)

    # Advanced options — YES, to set fast timing for demo
    wait_for(child, r"advanced options")
    time.sleep(0.3)
    type_and_enter(child, "y", FAST)

    # Build VUs — accept default 4
    wait_for(child, r"Build virtual users")
    time.sleep(0.2)
    enter(child)

    # Load VUs — set to 8
    wait_for(child, r"Load virtual users")
    time.sleep(0.2)
    type_and_enter(child, "8", FAST)

    # Rampup — 1 minute (fast demo)
    wait_for(child, r"Rampup")
    time.sleep(0.2)
    type_and_enter(child, "1", FAST)

    # Duration — 1 minute (fast demo)
    wait_for(child, r"Duration")
    time.sleep(0.2)
    type_and_enter(child, "1", FAST)

    # Pod resources — accept all defaults
    wait_for(child, r"Request memory")
    time.sleep(0.2)
    enter(child)

    wait_for(child, r"Request CPU")
    time.sleep(0.2)
    enter(child)

    wait_for(child, r"Limit memory")
    time.sleep(0.2)
    enter(child)

    wait_for(child, r"Limit CPU")
    time.sleep(0.2)
    enter(child)

    # Confirm write
    wait_for(child, r"Write configuration")
    time.sleep(LONG_PAUSE)  # Let viewer read the summary
    enter(child)  # Yes (default)

    # Wait for file written confirmation
    wait_for(child, r"Config written")
    time.sleep(LONG_PAUSE)

    # ── Step 2: Show the YAML ───────────────────────────────────────────
    wait_for(child, r"[\$#]")
    time.sleep(PAUSE)
    type_and_enter(child, f"cat {YAML_OUTPUT}", FAST)
    wait_for(child, r"[\$#]", timeout=10)
    time.sleep(LONG_PAUSE)

    # ── Step 3: Validate ────────────────────────────────────────────────
    type_and_enter(child, f"hammerdb-scale validate -f {YAML_OUTPUT}", FAST)
    wait_for(child, r"[\$#]", timeout=30)
    time.sleep(LONG_PAUSE)

    # ── Done: exit the shell to stop recording ──────────────────────────
    type_and_enter(child, "exit", FAST)
    child.expect(pexpect.EOF, timeout=10)
    child.close()

    print(f"\nRecording saved to: {CAST_FILE}")
    print(f"Convert to GIF:  agg {CAST_FILE} getting-started.gif")
    print(f"Upload:          asciinema upload {CAST_FILE}")


if __name__ == "__main__":
    main()
