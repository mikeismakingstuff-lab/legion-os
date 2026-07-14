"""
src/compression_engine.py
Legion OS — Headroom Context Compression Engine

Environment Audit:
1. Local System Check: Checked for existing headroom binaries or local python packages. None found.
2. Open-Source Check: Identified `headroom-ai` as the mature open-source library for context compression in AI agents.
3. Conclusion: Proceeding with native programmatic integration of `headroom-ai`.
"""

from __future__ import annotations

import sqlite3
import json
from pathlib import Path
from typing import Optional

# pyrefly: ignore [missing-import]
try:
    # pyrefly: ignore [missing-import]
    from headroom import HeadroomCompressor
except ImportError:
    # Fallback dummy compressor if headroom is not installed
    class HeadroomCompressor:
        def compress(self, text: str) -> str:
            return text
        def decompress(self, text: str) -> str:
            return text

from src.db import get_connection


class CompressionEngine:
    """Wraps the Headroom compressor to provide programmatic text compression

    and database-backed Content-Addressable Retrieval (CAR).
    """

    def __init__(self):
        self.compressor = HeadroomCompressor()

    def compress_record(
        self,
        ingest_id: str,
        raw_text: str,
        db_path: Optional[Path] = None,
    ) -> dict:
        """Compress raw text and store the BLOB in the compressed_content table.

        Parameters
        ----------
        ingest_id : Unique identifier for the ingest record.
        raw_text : The uncompressed text content.
        db_path : Path to the SQLite database.

        Returns
        -------
        dict
            Compression metrics (ratio, lengths).
        """
        if not ingest_id or not raw_text:
            return {
                "ingest_id": ingest_id,
                "compression_ratio": 1.0,
                "compressed_length": len(raw_text) if raw_text else 0,
                "uncompressed_length": len(raw_text) if raw_text else 0,
            }

        try:
            compressed_text = self.compressor.compress(raw_text)
            uncompressed_length = len(raw_text)
            compressed_length = len(compressed_text)
            compression_ratio = (
                compressed_length / uncompressed_length
                if uncompressed_length > 0
                else 1.0
            )

            if db_path:
                self._store_compressed_data(
                    ingest_id=ingest_id,
                    compressed_data=compressed_text,
                    uncompressed_length=uncompressed_length,
                    compressed_length=compressed_length,
                    compression_ratio=compression_ratio,
                    db_path=db_path,
                )

            return {
                "ingest_id": ingest_id,
                "compression_ratio": compression_ratio,
                "compressed_length": compressed_length,
                "uncompressed_length": uncompressed_length,
            }
        except Exception as e:
            # Fallback gracefully to uncompressed metrics
            print(f"[COMPRESSION] Failed for {ingest_id}: {e}")
            return {
                "ingest_id": ingest_id,
                "compression_ratio": 1.0,
                "compressed_length": len(raw_text),
                "uncompressed_length": len(raw_text),
            }

    def retrieve_uncompressed(
        self,
        ingest_id: str,
        db_path: Optional[Path] = None,
    ) -> str:
        """Perform Content-Addressable Retrieval (CAR) lookup.

        Retrieves compressed data from the database and decompresses it.
        Falls back to raw_content in ingest_records if not found in compressed_content.
        """
        if not ingest_id:
            return ""

        # 1. Try to fetch and decompress from compressed_content
        compressed_data = self._fetch_compressed_data(ingest_id, db_path)
        if compressed_data:
            try:
                # Headroom compressor expects bytes or string depending on version;
                # decompress returns the original string.
                return self.compressor.decompress(compressed_data)
            except Exception as e:
                print(f"[COMPRESSION] Decompression failed for {ingest_id}: {e}")

        # 2. Fallback to raw_content in ingest_records (zero-amnesia fallback)
        conn = get_connection(db_path)
        try:
            row = conn.execute(
                "SELECT raw_content FROM ingest_records WHERE ingest_id = ?",
                (ingest_id,),
            ).fetchone()
            return row["raw_content"] if row else ""
        except Exception:
            return ""
        finally:
            conn.close()

    def _store_compressed_data(
        self,
        ingest_id: str,
        compressed_data: bytes | str,
        uncompressed_length: int,
        compressed_length: int,
        compression_ratio: float,
        db_path: Path,
    ) -> None:
        """Write the compressed BLOB to the compressed_content table."""
        conn = get_connection(db_path)
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS compressed_content (
                    ingest_id TEXT PRIMARY KEY,
                    compressed_data BLOB,
                    uncompressed_length INTEGER,
                    compressed_length INTEGER,
                    compression_ratio REAL,
                    timestamp TEXT
                )
                """
            )
            # Wrap in sqlite3.Binary for binary safety if it is bytes
            db_data = (
                sqlite3.Binary(compressed_data)
                if isinstance(compressed_data, bytes)
                else compressed_data
            )
            conn.execute(
                """
                INSERT OR REPLACE INTO compressed_content
                    (ingest_id, compressed_data, uncompressed_length, compressed_length, compression_ratio, timestamp)
                VALUES (?, ?, ?, ?, ?, datetime('now'))
                """,
                (
                    ingest_id,
                    db_data,
                    uncompressed_length,
                    compressed_length,
                    compression_ratio,
                ),
            )
            conn.commit()
        except sqlite3.Error as e:
            print(f"[COMPRESSION] Database error storing compressed data: {e}")
        finally:
            conn.close()

    def _fetch_compressed_data(
        self,
        ingest_id: str,
        db_path: Optional[Path],
    ) -> Optional[bytes | str]:
        """Fetch compressed data from the database."""
        conn = get_connection(db_path)
        try:
            row = conn.execute(
                "SELECT compressed_data FROM compressed_content WHERE ingest_id = ?",
                (ingest_id,),
            ).fetchone()
            return row["compressed_data"] if row else None
        except sqlite3.Error as e:
            print(f"[COMPRESSION] Database error fetching compressed data: {e}")
            return None
        finally:
            conn.close()


# Singleton instance
compression_engine = CompressionEngine()
