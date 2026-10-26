// Disassemble + decompile arbitrary seed addresses. Args: outfile then hex addrs.
// Also dumps a raw listing for each [seed, seed+len) window.
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.*;
import ghidra.program.model.address.*;
import ghidra.program.model.mem.*;
import ghidra.program.model.listing.*;
import ghidra.util.task.ConsoleTaskMonitor;
import java.io.*;

public class DumpRange extends GhidraScript {
    @Override
    public void run() throws Exception {
        String[] a = getScriptArgs();
        String outpath = a[0];
        Memory mem = currentProgram.getMemory();
        AddressSpace sp = currentProgram.getAddressFactory().getDefaultAddressSpace();
        MemoryBlock mir = mem.getBlock("ROM_mirror_80BF");
        if (mir != null) { mir.setExecute(true); mir.setRead(true); }
        Listing lst = currentProgram.getListing();
        PrintWriter out = new PrintWriter(new FileWriter(outpath));

        DecompInterface ifc = new DecompInterface();
        ifc.openProgram(currentProgram);
        ConsoleTaskMonitor mon = new ConsoleTaskMonitor();

        for (int i = 1; i < a.length; i++) {
            String[] parts = a[i].split(":");
            long addr = Long.parseLong(parts[0], 16);
            long len = (parts.length > 1) ? Long.parseLong(parts[1], 16) : 0x120;
            Address start = sp.getAddress(addr);
            disassemble(start);
            Address cur = start;
            Address end = sp.getAddress(addr + len);
            out.println(String.format("===== LISTING $%06X .. $%06X =====", addr, addr+len));
            while (cur.compareTo(end) < 0) {
                Instruction ins = lst.getInstructionAt(cur);
                if (ins == null) {
                    out.println(cur + ":  (data) " + String.format("%02X", mem.getByte(cur)&0xFF));
                    cur = cur.add(1);
                } else {
                    out.println(String.format("%s:  %s", cur, ins.toString()));
                    cur = cur.add(ins.getLength());
                }
            }
            Function f = getFunctionContaining(start);
            if (f == null) { try { f = createFunction(start, null); } catch (Exception e) {} }
            if (f != null) {
                out.println("----- decompile " + f.getName() + " @ " + f.getEntryPoint() + " -----");
                try {
                    DecompileResults r = ifc.decompileFunction(f, 60, mon);
                    DecompiledFunction df = r.getDecompiledFunction();
                    out.println(df != null ? df.getC() : "// <decompile failed>");
                } catch (Exception e) { out.println("// decompile exception: " + e); }
            }
            out.println();
        }
        out.close();
        println("wrote " + outpath);
    }
}
