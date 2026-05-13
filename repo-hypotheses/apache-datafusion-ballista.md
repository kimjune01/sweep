# apache/datafusion-ballista Triage Graph

**Repository**: apache/datafusion-ballista  
**Language**: Rust  
**Hypothesis**: H0/H3 — bug fix, `good first issue` tags present, Apache project  
**Triage Date**: 2026-05-09

## Issue Scan Summary

**Selected issue**: #631

## Issue Evaluation

### Selected: #631 - `write_time` of ShuffleWriterExec is incorrect

**Status**: Open, community-filed, confirmed bug  
**Competing PRs**: None direct (PR #1537 touches shuffle writer I/O but for async, not metrics)  
**Actionability**: High  

**Problem**:
The `write_time` metric in `ShuffleWriterExec` records the total stream processing time rather than actual write time. In the `None` output-partitioning branch, an outer `write_time` timer wraps the entire `write_stream_to_disk` call. But `write_stream_to_disk` already starts/stops `write_time` internally per batch. The outer timer double-counts.

**Implementation**:
- Removed the outer `let timer = write_metrics.write_time.timer()` and its `timer.done()` in the `None` branch
- `write_stream_to_disk` handles per-batch timing internally, which is the correct granularity
- Added a comment explaining why no outer timer is needed
- 1 file changed, 2 insertions, 3 deletions

**Branch**: fix/shuffle-writer-write-time-metric  
**Commit**: 77ff42a  
**Tests**: Minimal change, metrics-only fix

## Repository Health

**Strengths**:
- Clear bug reports with expected vs actual behavior
- `good first issue` and `help wanted` labels on issues
- Active development (TUI docs merged recently)

**Risks**:
- Apache CLA/ICLA required for contributions
- Low PR velocity — review turnaround may be slow
- PR #1537 (shuffle writer async I/O) could conflict if merged first
