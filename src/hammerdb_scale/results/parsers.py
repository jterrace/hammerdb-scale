"""Database-specific HammerDB output parsers."""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class TproccResult:
    tpm: int
    nopm: int


@dataclass
class TprochQueryResult:
    query_number: int
    time_seconds: float


@dataclass
class TprochResult:
    qphh: float
    queries: list[TprochQueryResult]


class OutputParser(ABC):
    @abstractmethod
    def parse_tprocc(self, log_text: str) -> TproccResult | None:
        """Extract TPM and NOPM from log output. Returns None if not found."""

    @abstractmethod
    def parse_tproch(self, log_text: str) -> TprochResult | None:
        """Extract QphH and per-query timing. Returns None if not found."""

    @abstractmethod
    def detect_error(self, log_text: str) -> str | None:
        """Extract error message if job failed. Returns None if no error."""


class OracleParser(OutputParser):
    # Matches "123456 Oracle TPM" or just "123456 TPM"
    TPM_PATTERN = re.compile(r"(\d+)\s+(?:Oracle\s+)?TPM")
    NOPM_PATTERN = re.compile(r"(\d+)\s+(?:Oracle\s+)?NOPM")

    # TPC-H patterns
    QPHH_PATTERN = re.compile(r"QphH(?:@\d+)?[:\s]+([0-9]+\.?[0-9]*)")
    QUERY_PATTERN = re.compile(r"Query\s+(\d+)[:\s]+([0-9]+\.?[0-9]*)\s+seconds?")

    def parse_tprocc(self, log_text: str) -> TproccResult | None:
        tpm_matches = self.TPM_PATTERN.findall(log_text)
        nopm_matches = self.NOPM_PATTERN.findall(log_text)
        if tpm_matches and nopm_matches:
            # Take the LAST match (matching v1 bash `tail -1` behavior)
            return TproccResult(
                tpm=int(tpm_matches[-1]),
                nopm=int(nopm_matches[-1]),
            )
        return None

    def parse_tproch(self, log_text: str) -> TprochResult | None:
        qphh_matches = self.QPHH_PATTERN.findall(log_text)
        if not qphh_matches:
            return None

        qphh = float(qphh_matches[-1])

        query_matches = self.QUERY_PATTERN.findall(log_text)
        # Deduplicate (HammerDB sometimes outputs query times twice)
        seen = {}
        queries = []
        for qnum, qtime in query_matches:
            qn = int(qnum)
            qt = float(qtime)
            seen[qn] = qt  # Last occurrence wins
        for qn in sorted(seen):
            queries.append(TprochQueryResult(query_number=qn, time_seconds=seen[qn]))

        return TprochResult(qphh=qphh, queries=queries)

    def detect_error(self, log_text: str) -> str | None:
        if "ORA-" in log_text:
            match = re.search(r"(ORA-\d+:.*?)(?:\n|$)", log_text)
            return match.group(1) if match else "Oracle error (ORA-)"
        return _detect_generic_error(log_text)


class MssqlParser(OutputParser):
    # Matches "123456 SQL Server TPM" or just "123456 TPM"
    TPM_PATTERN = re.compile(r"(\d+)\s+(?:SQL Server\s+)?TPM")
    NOPM_PATTERN = re.compile(r"(\d+)\s+(?:SQL Server\s+)?NOPM")

    # Also check "System achieved" pattern
    SYSTEM_TPM_PATTERN = re.compile(
        r"System achieved\s+(\d+)\s+(?:SQL Server\s+)?NOPM\s+from\s+(\d+)\s+(?:SQL Server\s+)?TPM"
    )

    # TPC-H patterns (same as Oracle)
    QPHH_PATTERN = re.compile(r"QphH(?:@\d+)?[:\s]+([0-9]+\.?[0-9]*)")
    QUERY_PATTERN = re.compile(r"Query\s+(\d+)[:\s]+([0-9]+\.?[0-9]*)\s+seconds?")

    def parse_tprocc(self, log_text: str) -> TproccResult | None:
        # Try "System achieved" pattern first (more specific)
        sys_matches = self.SYSTEM_TPM_PATTERN.findall(log_text)
        if sys_matches:
            nopm, tpm = sys_matches[-1]
            return TproccResult(tpm=int(tpm), nopm=int(nopm))

        tpm_matches = self.TPM_PATTERN.findall(log_text)
        nopm_matches = self.NOPM_PATTERN.findall(log_text)
        if tpm_matches and nopm_matches:
            return TproccResult(
                tpm=int(tpm_matches[-1]),
                nopm=int(nopm_matches[-1]),
            )
        return None

    def parse_tproch(self, log_text: str) -> TprochResult | None:
        qphh_matches = self.QPHH_PATTERN.findall(log_text)
        if not qphh_matches:
            return None

        qphh = float(qphh_matches[-1])

        query_matches = self.QUERY_PATTERN.findall(log_text)
        seen = {}
        queries = []
        for qnum, qtime in query_matches:
            qn = int(qnum)
            qt = float(qtime)
            seen[qn] = qt
        for qn in sorted(seen):
            queries.append(TprochQueryResult(query_number=qn, time_seconds=seen[qn]))

        return TprochResult(qphh=qphh, queries=queries)

    def detect_error(self, log_text: str) -> str | None:
        if "Msg " in log_text:
            match = re.search(r"(Msg \d+,.*?)(?:\n|$)", log_text)
            return match.group(1) if match else "SQL Server error"
        return _detect_generic_error(log_text)


class PostgresParser(OutputParser):
    # HammerDB reports "System achieved N NOPM from M PostgreSQL TPM".
    TPM_PATTERN = re.compile(r"(\d+)\s+(?:PostgreSQL\s+)?TPM")
    NOPM_PATTERN = re.compile(r"(\d+)\s+(?:PostgreSQL\s+)?NOPM")
    SYSTEM_TPM_PATTERN = re.compile(
        r"System achieved\s+(\d+)\s+(?:PostgreSQL\s+)?NOPM\s+from\s+"
        r"(\d+)\s+(?:PostgreSQL\s+)?TPM"
    )

    QPHH_PATTERN = re.compile(r"QphH(?:@\d+)?[:\s]+([0-9]+\.?[0-9]*)")
    QUERY_PATTERN = re.compile(r"Query\s+(\d+)[:\s]+([0-9]+\.?[0-9]*)\s+seconds?")

    def parse_tprocc(self, log_text: str) -> TproccResult | None:
        sys_matches = self.SYSTEM_TPM_PATTERN.findall(log_text)
        if sys_matches:
            nopm, tpm = sys_matches[-1]
            return TproccResult(tpm=int(tpm), nopm=int(nopm))

        tpm_matches = self.TPM_PATTERN.findall(log_text)
        nopm_matches = self.NOPM_PATTERN.findall(log_text)
        if tpm_matches and nopm_matches:
            return TproccResult(
                tpm=int(tpm_matches[-1]),
                nopm=int(nopm_matches[-1]),
            )
        return None

    def parse_tproch(self, log_text: str) -> TprochResult | None:
        qphh_matches = self.QPHH_PATTERN.findall(log_text)
        if not qphh_matches:
            return None

        qphh = float(qphh_matches[-1])
        seen: dict[int, float] = {}
        for qnum, qtime in self.QUERY_PATTERN.findall(log_text):
            seen[int(qnum)] = float(qtime)
        queries = [
            TprochQueryResult(query_number=qn, time_seconds=seen[qn])
            for qn in sorted(seen)
        ]
        return TprochResult(qphh=qphh, queries=queries)

    def detect_error(self, log_text: str) -> str | None:
        # PostgreSQL errors carry a five-character SQLSTATE, e.g.
        # "ERROR:  relation "warehouse" does not exist".
        match = re.search(r"(?:FATAL|PANIC|ERROR):\s+.*?(?:\n|$)", log_text)
        if match:
            return match.group(0).strip()
        return _detect_generic_error(log_text)


def _detect_generic_error(log_text: str) -> str | None:
    """Generic error detection shared across parsers."""
    if "Error" in log_text or "FATAL" in log_text:
        match = re.search(r"(?:Error|FATAL).*?(?:\n|$)", log_text)
        return match.group(0).strip() if match else "Unknown error"
    return None


# Parser registry
PARSERS: dict[str, OutputParser] = {
    "oracle": OracleParser(),
    "mssql": MssqlParser(),
    "postgres": PostgresParser(),
}


def get_parser(database_type: str) -> OutputParser:
    """Get the parser for a given database type."""
    parser = PARSERS.get(database_type)
    if not parser:
        raise ValueError(f"No parser for database type: {database_type}")
    return parser
