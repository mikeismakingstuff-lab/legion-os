"""
aggregate_directory_metadata.py
Legion OS — Production Asset

Scans any absolute local directory path (including alternate drive partitions
on Windows) and returns a dict mapping relative file paths → SHA-256 hex digests.

Zero external dependencies. Standard library only.
"""

import os
import hashlib


def aggregate_directory_metadata(directory_path: str) -> dict[str, str]:
    """
    Scan *directory_path* recursively and return a mapping of
    relative file paths → SHA-256 hex digests.

    Parameters
    ----------
    directory_path : str
        Any absolute or relative local path to a directory.
        Cross-drive paths (e.g. E:\\Legion while CWD is C:\\) are fully supported.

    Returns
    -------
    dict[str, str]
        Keys   : file paths relative to *directory_path* (forward-slash separated)
        Values : SHA-256 hex digest of the file's binary content

    Raises
    ------
    ValueError
        If *directory_path* does not exist or is not a directory.
    """
    # --- Path validation: existence + type only, no CWD lock-in ---
    resolved = os.path.abspath(directory_path)

    if not os.path.exists(resolved):
        raise ValueError(
            f"The provided path does not exist: '{resolved}'"
        )
    if not os.path.isdir(resolved):
        raise ValueError(
            f"The provided path is not a directory: '{resolved}'"
        )

    metadata: dict[str, str] = {}

    for root, _, files in os.walk(resolved):
        for file_name in files:
            file_path = os.path.join(root, file_name)

            # Build a stable relative key so entries are unique across subdirectories
            rel_key = os.path.relpath(file_path, resolved).replace(os.sep, "/")

            try:
                # Fresh hashlib instance per file — no shared-state contamination
                hasher = hashlib.sha256()
                with open(file_path, "rb") as fh:
                    # Stream in 64 KB chunks for large-file performance
                    for chunk in iter(lambda: fh.read(65536), b""):
                        hasher.update(chunk)
                metadata[rel_key] = hasher.hexdigest()

            except FileNotFoundError:
                print(f"[SKIP] File not found (race condition?): {file_path}")
            except PermissionError:
                print(f"[SKIP] Permission denied: {file_path}")
            except OSError as exc:
                print(f"[SKIP] OS error while processing '{file_path}': {exc}")
            except IOError as exc:
                print(f"[SKIP] I/O error while processing '{file_path}': {exc}")
            except Exception as exc:  # noqa: BLE001
                print(f"[SKIP] Unexpected error while processing '{file_path}': {exc}")

    return metadata


# ---------------------------------------------------------------------------
# CLI entry-point — lets you test from the command line:
#   python aggregate_directory_metadata.py E:\Legion
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import sys
    import json

    if len(sys.argv) < 2:
        sys.stderr.write(
            "Usage: python aggregate_directory_metadata.py <directory_path>\n"
        )
        sys.exit(1)

    target = sys.argv[1]
    print(f"Scanning: {os.path.abspath(target)}\n")

    try:
        result = aggregate_directory_metadata(target)
    except ValueError as e:
        sys.stderr.write(f"[ERROR] {e}\n")
        sys.exit(1)

    print(json.dumps(result, indent=2))
    print(f"\n✓ {len(result)} file(s) hashed.")
