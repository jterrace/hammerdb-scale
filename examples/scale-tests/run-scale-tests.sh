#!/bin/bash
# Oracle 1-8 Scale Tests with per-scale reports
# Usage: ./run-scale-tests.sh

set -e

for scale in 1 2 3 4 5 6 7 8; do
  echo ""
  echo "============================================================"
  echo "  ORACLE SCALE TEST ${scale} of 8 — $(date)"
  echo "============================================================"

  CONFIG="oracle-scale-${scale}.yaml"

  echo ">>> Running benchmark..."
  hammerdb-scale run -f "$CONFIG" --wait --timeout 3600

  echo ">>> Collecting results..."
  hammerdb-scale results -f "$CONFIG"

  echo ">>> Generating report..."
  hammerdb-scale report -f "$CONFIG" -o "oracle-report-scale-${scale}.html"

  echo ">>> Scale ${scale} complete."
  echo ""
done

echo "============================================================"
echo "  ALL 8 SCALE TESTS COMPLETE — $(date)"
echo "============================================================"
echo ""
echo "Reports:"
ls -la oracle-report-scale-*.html
