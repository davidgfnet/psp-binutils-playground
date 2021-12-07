
MIPS allegrex VFPU instruction playground for GAS
=================================================

This is a collection of scripts used to verify that the binutils fork for
MIPS allegrex (the CPU that Sony's PSP ships) works as intended.

comparetestgood.py: Generates a massive assembly file (~32MB) that is then
assembled using two versions of `psp-as` (a _reference_ one, and the one to
test). The output is compared by using `objcopy` and comparing the raw bytes.
The aim is to very very exhaustive and test every instruction with a set of
meaningful operands.

errortest.py: Contains a list of hand-picked instructions and their intended
error messages (as regex). It will run `psp-as` and parse the output. This is
used to validate the different assembly errors that VFPU instructions can have.

comparetest.py: A rather slow test that will assemble instructions individually
and compare the results of two assemblers. It expects them to have an identical
exit code. This is used to test the register collision logic, register encoding
naming, and other _interesting_ operands like vrot.

Other non-testing scripts can be found under `gen-snippets`. These were used
to generate arrays and lookup tables for the assembler/disassembler, instead
of replicating the logic in `gas` itself.



