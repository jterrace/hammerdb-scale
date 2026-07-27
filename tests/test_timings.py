"""Tests for HammerDB 6.0 transaction response time capture.

Time profiling is optional, so every layer must treat missing timing data as
normal rather than as an error: a run with profiling off must still parse,
aggregate and render cleanly.
"""

from __future__ import annotations

from hammerdb_scale.reports.generator import (
    _aggregate_timings,
    _latency_section_html,
    generate_scorecard,
)
from hammerdb_scale.results.parsers import parse_transaction_timings

PROFILED = """
TRANSACTION RESPONSE TIMES
{
  "NEWORD": {
    "elapsed_ms": "238147.5", "calls": "173647", "min_ms": "1.942",
    "avg_ms": "7.083", "max_ms": "133.943", "total_ms": "1229911.98",
    "p99_ms": "11.522", "p95_ms": "10.272", "p75_ms": "8.516",
    "p50_ms": "6.993", "p25_ms": "5.551", "sd": "1.961", "ratio_pct": "64.556"
  },
  "PAYMENT": {
    "elapsed_ms": "238147.5", "calls": "174104", "min_ms": "0.782",
    "avg_ms": "1.895", "max_ms": "49.163", "total_ms": "329840.155",
    "p99_ms": "3.131", "p95_ms": "2.502", "p75_ms": "2.180",
    "p50_ms": "1.950", "p25_ms": "1.520", "sd": "0.9", "ratio_pct": "17.31"
  }
}

TRANSACTION COUNT
"""

# What HammerDB emits when the run had profiling disabled.
UNPROFILED = """
TRANSACTION RESPONSE TIMES
{"6A653C6E3D5C03E283238343": {
    "Jobid": "has",
    "no": "timing",
    "data": ""
  }}

TRANSACTION COUNT
"""


class TestParsing:
    def test_extracts_every_transaction(self):
        timings = parse_transaction_timings(PROFILED)
        assert {t.name for t in timings} == {"NEWORD", "PAYMENT"}

    def test_sorted_by_call_count(self):
        timings = parse_transaction_timings(PROFILED)
        assert timings[0].name == "PAYMENT"  # 174104 > 173647

    def test_numeric_conversion(self):
        neword = next(
            t for t in parse_transaction_timings(PROFILED) if t.name == "NEWORD"
        )
        assert neword.calls == 173647
        assert neword.p99_ms == 11.522
        assert neword.max_ms == 133.943

    def test_placeholder_yields_nothing(self):
        """Profiling off must look identical to absent, not produce a row."""
        assert parse_transaction_timings(UNPROFILED) == []

    def test_absent_block(self):
        assert parse_transaction_timings("no timing section here") == []

    def test_malformed_json_does_not_raise(self):
        assert parse_transaction_timings("TRANSACTION RESPONSE TIMES\n{broken") == []


class TestAggregation:
    def _target(self, calls, p99, max_ms):
        return {
            "tprocc": {
                "timings": [
                    {
                        "name": "NEWORD",
                        "calls": calls,
                        "avg_ms": 5.0,
                        "p50_ms": 4.0,
                        "p95_ms": p99 - 1,
                        "p99_ms": p99,
                        "max_ms": max_ms,
                    }
                ]
            }
        }

    def test_percentiles_are_call_weighted(self):
        rows = _aggregate_timings(
            [self._target(100, 10.0, 50.0), self._target(900, 20.0, 60.0)]
        )
        # 900 calls at p99=20 must dominate 100 calls at p99=10.
        assert rows[0]["p99_ms"] == 19.0

    def test_max_is_worst_seen_not_averaged(self):
        """A single stall on one target is the finding, so it must survive."""
        rows = _aggregate_timings(
            [self._target(100, 10.0, 50.0), self._target(100, 10.0, 12638.98)]
        )
        assert rows[0]["max_ms"] == 12638.98

    def test_calls_sum_across_targets(self):
        rows = _aggregate_timings(
            [self._target(100, 10.0, 1.0), self._target(250, 10.0, 1.0)]
        )
        assert rows[0]["calls"] == 350

    def test_no_timings_yields_no_rows(self):
        assert _aggregate_timings([{"tprocc": {"tpm": 1, "nopm": 1}}]) == []

    def test_zero_call_entries_ignored(self):
        assert _aggregate_timings([self._target(0, 10.0, 1.0)]) == []


class TestReportDegradation:
    """The section must vanish when there is no data, never render empty."""

    def _summary(self, timings=None):
        target = {
            "name": "sql-01",
            "host": "10.0.0.1",
            "status": "completed",
            "duration_seconds": 245,
            "tprocc": {"tpm": 98575, "nopm": 42457},
        }
        if timings:
            target["tprocc"]["timings"] = timings
        return {
            "test_id": "t1",
            "benchmark": "tprocc",
            "config": {"database_type": "mssql", "target_count": 1},
            "targets": [target],
            "aggregate": {
                "total_tpm": 98575,
                "total_nopm": 42457,
                "targets_completed": 1,
                "avg_tpm": 98575,
            },
        }

    ROW = [
        {
            "name": "NEWORD",
            "calls": 1000,
            "avg_ms": 7.0,
            "p50_ms": 6.9,
            "p95_ms": 10.2,
            "p99_ms": 11.5,
            "max_ms": 133.9,
        }
    ]

    def test_section_omitted_without_timings(self):
        assert _latency_section_html([{"tprocc": {"tpm": 1}}]) == ""

    def test_section_present_with_timings(self):
        html = _latency_section_html([{"tprocc": {"timings": self.ROW}}])
        assert "Transaction Response Times" in html
        assert "NEWORD" in html

    def test_report_renders_without_timings_or_array(self):
        html = generate_scorecard(self._summary(), pure_metrics=None)
        assert "Transaction Response Times" not in html
        assert "Storage Performance" not in html

    def test_report_renders_with_timings_only(self):
        """Latency data must be usable even when no array was polled."""
        html = generate_scorecard(self._summary(self.ROW), pure_metrics=None)
        assert "Transaction Response Times" in html
        assert "Storage Performance" not in html

    def test_report_renders_with_both(self):
        pure = {
            "raw_metrics": [
                {
                    "timestamp": "t",
                    "read_latency_us": 300,
                    "write_latency_us": 400,
                    "read_iops": 10,
                    "write_iops": 5,
                    "read_bandwidth_mbps": 1,
                    "write_bandwidth_mbps": 1,
                }
            ],
            "summary": {},
        }
        html = generate_scorecard(self._summary(self.ROW), pure_metrics=pure)
        assert "Transaction Response Times" in html
        assert "Storage Performance" in html
