// Decompile + disassemble the SoE map decompressor at $8C9C22 and its handlers.
// Runs on the already-imported SoE_SNES program. Writes results to args[0].
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.*;
import ghidra.program.model.address.*;
import ghidra.program.model.mem.*;
import ghidra.program.model.listing.*;
import ghidra.util.task.ConsoleTaskMonitor;
import java.io.*;

public class DumpRoutine extends GhidraScript {
    @Override
    public void run() throws Exception {
        String outpath = (getScriptArgs().length > 0) ? getScriptArgs()[0] : "routine_dump.txt";
        Memory mem = currentProgram.getMemory();
        AddressSpace sp = currentProgram.getAddressFactory().getDefaultAddressSpace();
        MemoryBlock mir = mem.getBlock("ROM_mirror_80BF");
        if (mir != null) { mir.setExecute(true); mir.setRead(true); }

        // seed addresses (bank $8C, real runtime addresses) - all jump-table targets
        long[] seeds = {0x8C9C22L, 0x8C9C46L, 0x8C9C5EL,
                        0x8C9C7FL, 0x8C9C92L, 0x8C9CB7L, 0x8C9CD5L, 0x8C9CE9L, 0x8C9D03L, 0x8C9D16L,
                        0x8C9D5EL,
                        // $9DFB table (bit-shift handlers)
                        0x8C9E0BL,0x8C9E12L,0x8C9E1AL,0x8C9E23L,0x8C9E2DL,0x8C9E37L,0x8C9E40L,0x8C9E48L,
                        // $9EA7 table
                        0x8C9EB7L,0x8C9EBEL,0x8C9EC6L,0x8C9ECFL,0x8C9ED9L,0x8C9EE3L,0x8C9EECL,0x8C9EF4L,
                        // $9E4D table
                        0x8C9E5FL,0x8C9E65L,0x8C9E6CL,0x8C9E74L,0x8C9E7DL,0x8C9E87L,0x8C9E91L,0x8C9E9AL,0x8C9EA2L,
                        0x8C9EF9L, 0x8C9EFAL, 0x8C9F62L};
        for (long s : seeds) {
            Address a = sp.getAddress(s);
            try { disassemble(a); } catch (Exception e) { println("dis fail "+Long.toHexString(s)+": "+e); }
        }
        // create function at entry + handlers
        for (long s : seeds) {
            Address a = sp.getAddress(s);
            if (getFunctionAt(a) == null) {
                try { createFunction(a, String.format("codec_%06X", s)); } catch (Exception e) {}
            }
        }

        PrintWriter out = new PrintWriter(new FileWriter(outpath));

        // 1) raw instruction listing for the whole codec region 8C9C22..8C9F80
        out.println("===== DISASSEMBLY $8C9C22 .. $8C9F80 =====");
        Listing lst = currentProgram.getListing();
        Address cur = sp.getAddress(0x8C9C22L);
        Address end = sp.getAddress(0x8C9F90L);
        while (cur.compareTo(end) < 0) {
            Instruction ins = lst.getInstructionAt(cur);
            if (ins == null) {
                Data d = lst.getDataAt(cur);
                out.println(cur + ":  (data) " + (d!=null?d.toString():"??"));
                cur = cur.add(1);
                continue;
            }
            out.println(String.format("%s:  %-24s %s", cur, ins.toString(), ""));
            cur = cur.add(ins.getLength());
        }

        // 2) decompiled C for entry + each handler function
        DecompInterface ifc = new DecompInterface();
        ifc.openProgram(currentProgram);
        ConsoleTaskMonitor mon = new ConsoleTaskMonitor();
        long[] funcs = {0x8C9C22L, 0x8C9C46L, 0x8C9C5EL, 0x8C9EFAL};
        for (long s : funcs) {
            Address a = sp.getAddress(s);
            Function f = getFunctionContaining(a);
            if (f == null) { out.println("\n// no function at "+Long.toHexString(s)); continue; }
            out.println("\n===== DECOMPILE " + f.getName() + " @ " + f.getEntryPoint() + " =====");
            try {
                DecompileResults r = ifc.decompileFunction(f, 90, mon);
                DecompiledFunction df = r.getDecompiledFunction();
                out.println(df != null ? df.getC() : "// <decompile failed>");
            } catch (Exception e) { out.println("// decompile exception: " + e); }
        }
        out.close();
        println("wrote " + outpath);
    }
}
