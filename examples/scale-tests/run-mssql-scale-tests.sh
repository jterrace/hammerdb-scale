#!/bin/bash
# MSSQL 1,2,4,8 Scale Tests with per-scale reports
# Usage: ./run-mssql-scale-tests.sh

set -e

for scale in 1 2 4 6 8; do
  echo ""
  echo "============================================================"
  echo "  MSSQL SCALE TEST ${scale} — $(date)"
  echo "============================================================"

  CONFIG="mssql-scale-${scale}.yaml"

  echo ">>> Running benchmark..."
  hammerdb-scale run -f "$CONFIG" --wait --timeout 3600

  echo ">>> Collecting results..."
  hammerdb-scale results -f "$CONFIG"

  echo ">>> Generating report..."
  hammerdb-scale report -f "$CONFIG" -o "mssql-report-scale-${scale}.html"

  echo ">>> Scale ${scale} complete."
  echo ""
done

echo "============================================================"
echo "  ALL MSSQL SCALE TESTS COMPLETE — $(date)"
echo "============================================================"
echo ""
echo "Reports:"
ls -la mssql-report-scale-*.html
