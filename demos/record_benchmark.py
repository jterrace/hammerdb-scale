#!/usr/bin/env python3.11
"""Record the 'Benchmark Payoff' asciinema demo for hammerdb-scale.

Assumes schemas are already built (pre-build before recording).
Shows: run → wait → results → report → clean
"""

import os
import time

import pexpect

# ── Config ──────────────────────────────────────────────────────────────
CAST_FILE = os.path.join(os.path.dirname(__file__), "benchmark-payoff.cast")
YAML_FILE = "/tmp/hammerdb-scale-demo.yaml"
F = f"-f {YAML_FILE}"

# Specific prompt pattern: [root@august hammerdb-scale]#
PROMPT = r"hammerdb-scale\]#"

FAST = 0.04
NORMAL = 0.06
PAUSE = 1.0
LONG_PAUSE = 2.5


def typed(child, text, speed=NORMAL):
    for ch in text:
        child.send(ch)
        time.sleep(speed)
    time.sleep(0.15)


def enter(child):
    child.send("\r")
    time.sleep(0.3)


def type_and_enter(child, text, speed=NORMAL):
    typed(child, text, speed)
    enter(child)


def wait_for_prompt(child, timeout=600):
    """Wait for the bash prompt."""
    child.expect(PROMPT, timeout=timeout)
    time.sleep(0.5)


def main():
    if not os.path.exists(YAML_FILE):
        print(f"ERROR: {YAML_FILE} not found. Run record_getting_started.py first.")
        return

    os.environ["COLUMNS"] = "100"
    os.environ["LINES"] = "35"

    child = pexpect.spawn(
        f"asciinema rec --cols 100 --rows 35 --idle-time-limit 3 "
        f"--title 'hammerdb-scale: Benchmark Run' "
        f"--overwrite {CAST_FILE}",
        encoding="utf-8",
        timeout=600,
    )
    child.setwinsize(35, 100)

    wait_for_prompt(child)
    time.sleep(PAUSE)

    # ── Run benchmark ───────────────────────────────────────────────────
    type_and_enter(child, f"hammerdb-scale run {F} --wait", FAST)
    # rampup=1 + duration=1 = ~3 min total
    wait_for_prompt(child, timeout=600)
    time.sleep(LONG_PAUSE)

    # ── Results ─────────────────────────────────────────────────────────
    type_and_enter(child, f"hammerdb-scale results {F}", FAST)
    wait_for_prompt(child, timeout=60)
    time.sleep(LONG_PAUSE)

    # ── Report ──────────────────────────────────────────────────────────
    type_and_enter(child, f"hammerdb-scale report {F} -o /tmp/scorecard.html", FAST)
    wait_for_prompt(child, timeout=60)
    time.sleep(LONG_PAUSE)

    # ── Clean ───────────────────────────────────────────────────────────
    type_and_enter(
        child,
        f"hammerdb-scale clean {F} --resources --database "
        f"--benchmark tprocc --everything --force",
        FAST,
    )
    wait_for_prompt(child, timeout=120)
    time.sleep(LONG_PAUSE)

    # ── Exit ────────────────────────────────────────────────────────────
    type_and_enter(child, "exit", FAST)
    child.expect(pexpect.EOF, timeout=10)
    child.close()

    print(f"\nRecording saved to: {CAST_FILE}")
    print(f"Convert to GIF:  agg {CAST_FILE} benchmark-payoff.gif")
    print(f"Upload:          asciinema upload {CAST_FILE}")


if __name__ == "__main__":
    main()
