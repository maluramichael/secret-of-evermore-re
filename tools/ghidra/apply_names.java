// Apply the curated docs/labels.md address->name table to the proj_snes program.
// Parses rows of the form  | $XXXXXX | 0xYYYYYY | name | ... |  and, per address:
//   - renames an existing function, else
//   - creates a function (disassembling if needed), else
//   - drops a plain label.
// A trailing '?' in a name (provisional) becomes suffix '_q' in the Ghidra symbol.
//
// Headless:
//   $GHIDRA_HOME/support/analyzeHeadless build/ghidra/proj_snes SoE_SNES \
//     -process "Secret of Evermore (Europe).sfc" -noanalysis \
//     -scriptPath tools/ghidra -postScript apply_names.java [docs/labels.md]
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;
import ghidra.program.model.symbol.SourceType;
import java.io.BufferedReader;
import java.io.FileReader;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

public class apply_names extends GhidraScript {
    @Override
    public void run() throws Exception {
        String[] a = getScriptArgs();
        String path = a.length > 0 ? a[0] : "docs/labels.md";
        // | $8C9C22 | 0x0C9C22 | decompress_dispatch | F-A | ... |
        Pattern p = Pattern.compile(
            "^\\|\\s*\\$([0-9A-Fa-f]{6})\\s*\\|\\s*0x[0-9A-Fa-f]+\\s*\\|\\s*([^|]+?)\\s*\\|");
        int renamed = 0, created = 0, labelled = 0, failed = 0;
        BufferedReader br = new BufferedReader(new FileReader(path));
        String line;
        while ((line = br.readLine()) != null) {
            Matcher m = p.matcher(line);
            if (!m.find()) continue;
            long snes = Long.parseLong(m.group(1), 16);
            String name = m.group(2).trim().replace("?", "_q");
            if (name.isEmpty()) continue;
            Address addr = currentProgram.getAddressFactory()
                .getDefaultAddressSpace().getAddress(snes);
            Function f = getFunctionAt(addr);
            try {
                if (f != null) {
                    f.setName(name, SourceType.USER_DEFINED);
                    renamed++;
                } else if (getInstructionAt(addr) != null) {
                    // already disassembled code -> promote to a named function
                    Function nf = createFunction(addr, name);
                    if (nf != null) { created++; }
                    else { createLabel(addr, name, true); labelled++; }
                } else {
                    // data table or un-analysed bytes -> label only, never disassemble
                    createLabel(addr, name, true);
                    labelled++;
                }
                println(String.format("%06X -> %s", snes, name));
            } catch (Exception e) {
                failed++;
                println(String.format("FAIL %06X %s: %s", snes, name, e.getMessage()));
            }
        }
        br.close();
        println(String.format("done: renamed=%d created=%d labelled=%d failed=%d",
            renamed, created, labelled, failed));
    }
}
