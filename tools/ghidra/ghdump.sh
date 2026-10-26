#!/usr/bin/env bash
# Dump 65816 disassembly (+decompile) for arbitrary SNES addrs from the imported project.
# Usage: ghdump.sh <outfile> <addr[:len]> [addr[:len] ...]   (addrs+len in hex)
# Env: GHIDRA_HOME (Ghidra install dir), JAVA_HOME (JDK 21, optional if already set).
cd "$(dirname "$0")/../.."
if [ -z "$GHIDRA_HOME" ]; then echo "GHIDRA_HOME is not set (path to the Ghidra install dir)" >&2; exit 1; fi
GH="$GHIDRA_HOME"
OUT="$1"; shift
$GH/support/analyzeHeadless \
  build/ghidra/proj_snes SoE_SNES \
  -process "Secret of Evermore (Europe).sfc" \
  -noanalysis \
  -scriptPath tools/ghidra/scripts \
  -postScript DumpRange.java "$OUT" "$@" 2>&1 | grep -E "ERROR|Exception|wrote" | head
echo "=== $OUT ==="; cat "$OUT" 2>/dev/null
