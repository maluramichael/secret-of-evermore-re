// Ghidra GhidraScript (Java): decompiles ALL functions and writes the C code to
// chunked files under an output dir, plus an index.txt manifest
// (address, name, body-size, chunk, referenced strings) so the dump can be
// navigated without loading it all at once.
//
// Java is used instead of Python because Ghidra 12 dropped bundled Jython and
// needs a separate PyGhidra/CPython env for .py scripts.
//
// Usage: analyzeHeadless <proj> <name> -process <exe> -noanalysis \
//          -scriptPath tools/ghidra/scripts -postScript DumpAll.java <outdir> [chunk]
//@category Analysis
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.program.model.listing.*;
import ghidra.program.model.address.Address;
import ghidra.program.model.symbol.Reference;
import ghidra.program.model.data.DataType;

import java.io.*;
import java.util.*;

public class DumpAll extends GhidraScript {

    private String joinTrunc(List<String> strs, int n, int cap) {
        StringBuilder sb = new StringBuilder();
        for (int i = 0; i < Math.min(n, strs.size()); i++) {
            if (i > 0) sb.append(" | ");
            String s = strs.get(i);
            sb.append(s.length() > cap ? s.substring(0, cap) : s);
        }
        return sb.toString();
    }

    private String decompile(DecompInterface ifc, Function f) {
        try {
            DecompileResults res = ifc.decompileFunction(f, 60, monitor);
            if (res != null && res.getDecompiledFunction() != null)
                return res.getDecompiledFunction().getC();
        } catch (Exception e) {
            // fall through
        }
        return null;
    }

    private List<String> refStrings(Function f, Listing listing) {
        List<String> out = new ArrayList<>();
        Set<String> seen = new HashSet<>();
        CodeUnitIterator cus = listing.getCodeUnits(f.getBody(), true);
        while (cus.hasNext()) {
            CodeUnit cu = cus.next();
            for (Reference ref : cu.getReferencesFrom()) {
                Address ta = ref.getToAddress();
                if (ta == null) continue;
                Data d = listing.getDataAt(ta);
                if (d == null) continue;
                Object v = d.getValue();
                if (v == null) continue;
                DataType dt = d.getDataType();
                String tn = dt.getName().toLowerCase();
                if (tn.contains("unicode") || tn.contains("string") || tn.contains("char")) {
                    String s = v.toString().replace("\n", " ").replace("\r", " ").trim();
                    if (s.length() >= 3 && !seen.contains(s)) {
                        seen.add(s);
                        out.add(s);
                    }
                }
            }
        }
        return out;
    }

    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        String outdir = args.length > 0 ? args[0] : "assets/dumps/ghidra/decompiled";
        int chunkSize = args.length > 1 ? Integer.parseInt(args[1]) : 200;
        File od = new File(outdir);
        if (!od.isDirectory()) od.mkdirs();

        Listing listing = currentProgram.getListing();
        FunctionManager fm = currentProgram.getFunctionManager();

        DecompInterface ifc = new DecompInterface();
        ifc.openProgram(currentProgram);

        List<Function> funcs = new ArrayList<>();
        for (Function f : fm.getFunctions(true)) funcs.add(f);
        funcs.sort(Comparator.comparingLong(f -> f.getEntryPoint().getOffset()));
        int total = funcs.size();
        println("DumpAll: " + total + " functions, chunk=" + chunkSize);

        PrintWriter index = new PrintWriter(new FileWriter(new File(od, "index.txt")));
        index.println("# addr\tname\tbody_bytes\tchunk\tn_strings\tstrings(<=6)");

        int count = 0;
        PrintWriter cf = null;
        for (Function f : funcs) {
            if (count % chunkSize == 0) {
                if (cf != null) cf.close();
                int ci = count / chunkSize;
                cf = new PrintWriter(new FileWriter(
                        new File(od, String.format("chunk_%03d.c", ci))));
                cf.printf("// decompile chunk %03d (from function #%d)%n%n", ci, count);
            }
            int ci = count / chunkSize;
            Address ep = f.getEntryPoint();
            String name = f.getName();
            long bodyBytes = f.getBody().getNumAddresses();
            List<String> strs = refStrings(f, listing);

            index.printf("%s\t%s\t%d\t%03d\t%d\t%s%n",
                    ep, name, bodyBytes, ci, strs.size(), joinTrunc(strs, 6, 60));

            String c = decompile(ifc, f);
            cf.printf("%n// ===== %s @ %s  body=%d bytes  strings=%d =====%n",
                    name, ep, bodyBytes, strs.size());
            if (!strs.isEmpty()) cf.println("// refs: " + joinTrunc(strs, 12, 70));
            cf.println(c != null ? c : "// <decompile failed>");
            count++;
            if (count % 250 == 0) println("  ... " + count + "/" + total);
        }
        if (cf != null) cf.close();
        index.close();
        println("DumpAll: done, " + count + " functions -> " + outdir);
    }
}
