#!/usr/bin/env bash
# Dump 65816 disassembly (+decompile) from the proj_script project (script interpreter work).
# Usage: dump_script.sh <outfile> <addr[:len]> [addr[:len] ...]   (hex; SNES addrs)
# Env: GHIDRA_HOME (Ghidra install dir), JAVA_HOME (JDK 21, optional if already set).
cd "$(dirname "$0")/../.."
if [ -z "$GHIDRA_HOME" ]; then echo "GHIDRA_HOME is not set (path to the Ghidra install dir)" >&2; exit 1; fi
GH="$GHIDRA_HOME"
OUT="$1"; shift
$GH/support/analyzeHeadless \
  build/ghidra/proj_script SoE_Script \
  -process "Secret of Evermore (Europe).sfc" \
  -noanalysis \
  -scriptPath tools/ghidra/scripts \
  -postScript DumpRange.java "$OUT" "$@" 2>&1 | grep -E "ERROR|Exception|wrote" | head
echo "=== $OUT ==="; cat "$OUT" 2>/dev/null
