# Specification: Legion OS — Native Context Compression (Headroom)

## Environment Audit (Standing Rule)
1. **Local System Check:** No existing headroom binaries, tools, or local python packages were found in the workspace.
2. **Open-Source Check:** `headroom-ai` is a mature, trending open-source library for context compression in AI agents. It provides programmatic APIs for reversible text compression (Content-Addressable Retrieval / CCR) and saves 60-95% of token costs.
3. **Conclusion:** We will proceed with programmatically integrating `headroom-ai` into our pipeline.

---

## Objective
Integrate the Headroom context compression library natively into the Legion OS pipeline. The goal is to compress raw ingested text records immediately after ingestion/normalization and before they are parsed or stored in the main database tables. This reduces storage footprint and downstream token costs while preserving the ability to retrieve the original uncompressed content when needed.

---

## Requirements

1. **Placement:**
   - The compression pass must occur inside `node_ingest` or immediately after it, before `node_parse` runs.
   - Raw normalized text from `ingest_records` is compressed.

2. **Core Library Call:**
   - Import and use the `headroom` Python API programmatically:
     ```python
     from headroom import HeadroomCompressor
     compressor = HeadroomCompressor()
     compressed_text = compressor.compress(raw_text)
     ```
   - Handle exceptions gracefully: if compression fails, log a warning and fallback to the uncompressed raw text (do not crash the pipeline).

3. **Database/State Contract:**
   - Add tracking keys to the `PipelineState` passport:
     - `is_compressed: bool`
     - `compression_ratio: float`
   - Store the compressed content in a dedicated SQLite table to enforce the DB-as-contract pattern:
     ```sql
     CREATE TABLE IF NOT EXISTS compressed_content (
         ingest_id TEXT PRIMARY KEY,
         compressed_data BLOB,
         uncompressed_length INTEGER,
         compressed_length INTEGER,
         compression_ratio REAL,
         timestamp TEXT
     )
     ```
   - If a downstream stage (like Stage 2 Parse or Stage 5 Deliberate) needs the uncompressed text, it must perform a Content-Addressable Retrieval (CAR) lookup:
     ```python
     # Reverse lookup helper
     uncompressed_text = compressor.decompress(compressed_data)
     ```

---

## Committee Task
1. Analyze the memory boundaries and CPU usage constraints of running native compression on our local graphics/CPU profile (Intel Iris Xe CPU-only).
2. Evaluate the design of the `compressed_content` table and the reverse lookup (decompress) mechanism for downstream stages.
3. Implement a clean, production-grade Python module `src/compression_engine.py` that wraps the Headroom compressor and exposes:
   - `compress_record(ingest_id: str, raw_text: str, db_path: Optional[str]) -> dict` (returns compression metrics)
   - `retrieve_uncompressed(ingest_id: str, db_path: Optional[str]) -> str` (performs reverse lookup and decompression)
