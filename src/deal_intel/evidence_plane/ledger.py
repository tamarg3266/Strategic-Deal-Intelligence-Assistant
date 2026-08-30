from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from deal_intel.contracts.schemas import EvidenceRecord
from deal_intel.control_plane.capabilities import EvidenceCapability


class EvidenceLedger:
    """SQLite evidence index with metadata filtering ahead of ranking."""

    _fts_token_pattern = re.compile(r"[\w]+", re.UNICODE)

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path

    def connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        return conn

    def initialize(self) -> None:
        with self.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS evidence_records (
                    evidence_id TEXT PRIMARY KEY,
                    source_file TEXT NOT NULL,
                    source_record_id TEXT NOT NULL,
                    record_kind TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    source_access_level TEXT NOT NULL,
                    account_id TEXT NOT NULL,
                    opportunity_id TEXT NOT NULL,
                    source_date TEXT,
                    text TEXT NOT NULL,
                    metadata_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_evidence_scope ON evidence_records(
                    account_id, opportunity_id, source_type, source_access_level
                );
                CREATE VIRTUAL TABLE IF NOT EXISTS evidence_fts
                    USING fts5(evidence_id UNINDEXED, text);
                CREATE TABLE IF NOT EXISTS evidence_index_state (
                    singleton_id INTEGER PRIMARY KEY CHECK(singleton_id = 1),
                    source_fingerprint TEXT NOT NULL,
                    record_count INTEGER NOT NULL,
                    indexed_at TEXT NOT NULL
                );
                """
            )

    def replace_index(self, records: list[EvidenceRecord]) -> None:
        self._replace_index(records, source_fingerprint=None, skip_if_current=False)

    def refresh_index_if_changed(
        self,
        records: list[EvidenceRecord],
        source_fingerprint: str,
    ) -> bool:
        return self._replace_index(
            records,
            source_fingerprint=source_fingerprint,
            skip_if_current=True,
        )

    def is_index_current(self, source_fingerprint: str) -> tuple[bool, int]:
        self.initialize()
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT source_fingerprint, record_count
                FROM evidence_index_state
                WHERE singleton_id = 1
                """
            ).fetchone()
            actual_count = conn.execute(
                "SELECT COUNT(*) AS count FROM evidence_records"
            ).fetchone()["count"]
        if row is None:
            return False, actual_count
        current = (
            row["source_fingerprint"] == source_fingerprint
            and row["record_count"] == actual_count
        )
        return current, actual_count

    def _replace_index(
        self,
        records: list[EvidenceRecord],
        *,
        source_fingerprint: str | None,
        skip_if_current: bool,
    ) -> bool:
        self.initialize()
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            if skip_if_current and source_fingerprint is not None:
                row = conn.execute(
                    """
                    SELECT source_fingerprint, record_count
                    FROM evidence_index_state
                    WHERE singleton_id = 1
                    """
                ).fetchone()
                actual_count = conn.execute(
                    "SELECT COUNT(*) AS count FROM evidence_records"
                ).fetchone()["count"]
                if (
                    row is not None
                    and row["source_fingerprint"] == source_fingerprint
                    and row["record_count"] == actual_count
                ):
                    return False
            conn.execute("DELETE FROM evidence_fts")
            conn.execute("DELETE FROM evidence_records")
            conn.executemany(
                """
                INSERT INTO evidence_records(
                    evidence_id, source_file, source_record_id, record_kind, source_type,
                    source_access_level, account_id, opportunity_id, source_date, text,
                    metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        record.evidence_id,
                        record.source_file,
                        record.source_record_id,
                        record.record_kind,
                        record.source_type,
                        record.source_access_level,
                        record.account_id,
                        record.opportunity_id,
                        record.source_date,
                        record.text,
                        json.dumps(record.metadata, sort_keys=True),
                    )
                    for record in records
                ],
            )
            conn.executemany(
                "INSERT INTO evidence_fts(evidence_id, text) VALUES (?, ?)",
                [(record.evidence_id, record.text) for record in records],
            )
            if source_fingerprint is not None:
                conn.execute(
                    """
                    INSERT INTO evidence_index_state(
                        singleton_id, source_fingerprint, record_count, indexed_at
                    ) VALUES (1, ?, ?, ?)
                    ON CONFLICT(singleton_id) DO UPDATE SET
                        source_fingerprint=excluded.source_fingerprint,
                        record_count=excluded.record_count,
                        indexed_at=excluded.indexed_at
                    """,
                    (
                        source_fingerprint,
                        len(records),
                        datetime.now(timezone.utc).isoformat(),
                    ),
                )
            else:
                conn.execute("DELETE FROM evidence_index_state")
        return True

    def scoped_candidates(self, capability: EvidenceCapability) -> list[EvidenceRecord]:
        return self.scoped_search(capability, "", limit=None)

    def scoped_search(
        self,
        capability: EvidenceCapability,
        query_text: str,
        limit: int | None,
    ) -> list[EvidenceRecord]:
        """Return capability-scoped rows, prioritizing lexical FTS5 matches.

        FTS5 ranks matching rows first. Non-matching scoped rows then fill any
        remaining capacity so a narrow lexical query cannot silently remove
        authorized context needed for a comprehensive analyst brief.
        """
        if not capability.allowed_source_types:
            return []
        source_types = sorted(capability.allowed_source_types)
        placeholders = ",".join("?" for _ in source_types)
        access_levels = ["standard"]
        if capability.can_view_sensitive_pricing:
            access_levels.append("sensitive_pricing")
        if capability.can_view_restricted_account:
            access_levels.append("restricted")
        access_placeholders = ",".join("?" for _ in access_levels)
        fts_query = self._fts_query(query_text)
        match_cte = """
            SELECT evidence_id, bm25(evidence_fts) AS fts_rank
            FROM evidence_fts
            WHERE evidence_fts MATCH ?
        """ if fts_query else """
            SELECT evidence_id, NULL AS fts_rank
            FROM evidence_fts
            WHERE 0
        """
        query = f"""
            WITH fts_matches AS ({match_cte})
            SELECT evidence_records.*
            FROM evidence_records
            LEFT JOIN fts_matches USING (evidence_id)
            WHERE account_id = ?
              AND opportunity_id = ?
              AND source_type IN ({placeholders})
              AND source_access_level IN ({access_placeholders})
            ORDER BY
                fts_matches.fts_rank IS NULL,
                fts_matches.fts_rank,
                evidence_records.source_date DESC,
                evidence_records.evidence_id DESC
        """
        params: list[object] = []
        if fts_query:
            params.append(fts_query)
        params.extend([
            capability.account_id,
            capability.opportunity_id,
            *source_types,
            *access_levels,
        ])
        if limit is not None:
            query += " LIMIT ?"
            params.append(limit)
        with self.connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [self._from_row(row) for row in rows]

    @classmethod
    def _fts_query(cls, query_text: str) -> str:
        tokens = list(
            dict.fromkeys(
                token.casefold()
                for token in cls._fts_token_pattern.findall(query_text)
            )
        )
        return " OR ".join(f'"{token.replace(chr(34), chr(34) * 2)}"' for token in tokens)

    @staticmethod
    def _from_row(row: sqlite3.Row) -> EvidenceRecord:
        return EvidenceRecord(
            evidence_id=row["evidence_id"],
            source_file=row["source_file"],
            source_record_id=row["source_record_id"],
            record_kind=row["record_kind"],
            source_type=row["source_type"],
            source_access_level=row["source_access_level"],
            account_id=row["account_id"],
            opportunity_id=row["opportunity_id"],
            source_date=row["source_date"],
            text=row["text"],
            metadata=json.loads(row["metadata_json"]),
        )
