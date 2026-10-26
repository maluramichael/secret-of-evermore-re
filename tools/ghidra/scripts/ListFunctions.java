// Dump all function entry points from the imported program as
//   <image_hex> <file_offset_hex> <name>
// image = Ghidra address (primary block base 0xC00000 + file offset).
// Usage (headless): analyzeHeadless proj SoE_SNES -process <rom> -noanalysis \
//   -scriptPath tools/ghidra/scripts -postScript ListFunctions.java <outfile>
import ghidra.app.script.GhidraScript;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.FunctionIterator;
import java.io.PrintWriter;

public class ListFunctions extends GhidraScript {
    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        String out = args.length > 0 ? args[0] : "functions.txt";
        PrintWriter pw = new PrintWriter(out);
        long base = 0xC00000L;
        FunctionIterator it = currentProgram.getFunctionManager().getFunctions(true);
        int n = 0;
        while (it.hasNext()) {
            Function f = it.next();
            long img = f.getEntryPoint().getOffset();
            long fileoff = img - base;
            pw.printf("%06X %06X %s%n", img, fileoff & 0xFFFFFF, f.getName());
            n++;
        }
        pw.close();
        println("wrote " + n + " functions to " + out);
    }
}
