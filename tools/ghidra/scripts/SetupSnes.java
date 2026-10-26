// Ghidra preScript (Java): build HiROM memory layout for Secret of Evermore (EU).
// BinaryLoader imports the 3MiB file as one block at 0xC00000. Here we add:
//  - byte-mapped mirror banks $80-$BF -> $C0-$FF ($8C9DDD -> src $CC9DDD -> file 0x0C9DDD)
//  - uninitialized WRAM 7E0000-7FFFFF (writes to $7F0000/$7FC300 resolve)
//  - reset vector as entry point, disassembled.
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.address.AddressSpace;
import ghidra.program.model.mem.Memory;
import ghidra.program.model.mem.MemoryBlock;

public class SetupSnes extends GhidraScript {
    @Override
    public void run() throws Exception {
        Memory mem = currentProgram.getMemory();
        AddressSpace space = currentProgram.getAddressFactory().getDefaultAddressSpace();

        if (mem.getBlock("ROM_mirror_80BF") == null) {
            try {
                Address start = space.getAddress(0x808000L);
                long length = 0xBFFFFFL - 0x808000L + 1;
                Address src = space.getAddress(0xC08000L);
                mem.createByteMappedBlock("ROM_mirror_80BF", start, src, length, false);
                println("added ROM_mirror_80BF");
            } catch (Exception e) { println("mirror failed: " + e); }
        }
        if (mem.getBlock("WRAM") == null) {
            try {
                MemoryBlock b = mem.createUninitializedBlock(
                        "WRAM", space.getAddress(0x7E0000L), 0x20000L, false);
                b.setRead(true); b.setWrite(true); b.setExecute(false);
                println("added WRAM 7E0000-7FFFFF");
            } catch (Exception e) { println("WRAM failed: " + e); }
        }
        try {
            int lo = mem.getByte(space.getAddress(0xC0FFFCL)) & 0xFF;
            int hi = mem.getByte(space.getAddress(0xC0FFFDL)) & 0xFF;
            long reset = 0xC00000L | (hi << 8) | lo;
            println(String.format("reset vector -> 0x%06X", reset));
            Address ra = space.getAddress(reset);
            createLabel(ra, "RESET", true);
            currentProgram.getSymbolTable().addExternalEntryPoint(ra);
            disassemble(ra);
        } catch (Exception e) { println("reset setup failed: " + e); }
    }
}
