# Specification: Secure Local Directory Metadata Aggregator

## Objective
Write a Python function named `aggregate_directory_metadata` that accepts a local directory path as a string argument. 

## Requirements
1. The function must scan the target directory and collect a list of all files.
2. For each file, it must read the content and calculate a standard MD5 hash to use as a unique signature.
3. It must return a Python dictionary where the keys are the file names and the values are their calculated hashes.

## Hard Constraints
- The tool must run with zero external dependencies (standard library only).
- The solution must be highly performant and execute rapidly on large file groups.