
# Copyright 2021 David Guillen Fandos <david@davidgf.net>

# VFPU assembling errors validator script
#
# This script will validate that `as` produces errors on certain conditions
# For intance: invalid register names, register conflicts, etc.

import argparse, re, subprocess

parser = argparse.ArgumentParser(prog='errortest')
parser.add_argument('--assembler', dest='asexec', required=True, help='Path (or executable within PATH) to invoke for `as`')
args = parser.parse_args()

TESTS = [
  ("vadd.s W000, W000, W000",    "invalid operand"),
  ("vadd.s $4, $4, $4",          "invalid operand"),
  ("vadd.q S000, S000, S000",    "register type mismatch.*vector.*required"),
  ("vadd.s R000, R000, R000",    "register type mismatch.*single.*required"),
  ("vadd.t R010, R000, R000",    None),
  ("vadd.t R020, R000, R000",    "register type mismatch.*triple.*required"),
  ("vadd.t R020.t, R000, R000",  "invalid operand"),
  ("vadd.q R020, R000, R000",    "register type mismatch.*quad.*required"),
  ("vadd.q R000.t, R000, R000",  "register type mismatch.*quad.*required"),

  # Register conflicts
  ("vcos.q R000, R000",          None),
  ("vcos.q R000, C000",          "register conflict..R000"),
  ("vcos.q R003, C010",          "register conflict..R003"),
  ("vcos.q R001, C020",          "register conflict..R001"),
  ("vcos.p R000, C000",          "register conflict..R000"),
  ("vcos.p R001, C000",          "register conflict..R001"),
  ("vcos.p R022, C022",          "register conflict..R022"),
  ("vcos.p R002, C000",          None),
  ("vcos.p R000, C020",          None),
  ("vcos.p R000, C030",          None),
  ("vcos.t R000, C030",          None),
  ("vcos.t R000, C031",          None),
  ("vcos.t R001, C031",          None),
  ("vcos.t R010, C030",          "register conflict..R010"),
  ("vcos.t R000, R000",          None),
  ("vcos.t R000, R010",          "register conflict..R000"),
  ("vcos.t R010, R000",          "register conflict..R010"),

  ("vmmul.q M000, M100, M100",   None),
  ("vmmul.q E000, M100, M100",   None),
  ("vmmul.q E100, M100, M100",   "register conflict..E100"),
  ("vmmul.p M000, M022, M020",   None),
  ("vmmul.p M000, M022, M002",   None),
  ("vmmul.p M000, M022, M000",   "register conflict..M000"),
  ("vmmul.p M022, M020, M022",   "register conflict..M022"),
  ("vmmul.p E022, M020, M022",   "register conflict..E022"),
  ("vmmul.t M000, M001, M010",   "register conflict..M000"),

  ("vtfm2.p R000, M000, R020",   "register conflict..R000"),
  ("vtfm2.p R000, M002, R020",   None),
  ("vtfm2.p R000, M002, C020",   None),

  # Compare instruction is interesting
  ("vcmp.q NE, R000, R002",      None),
  ("vcmp.q NZ, R000",            None),
  ("vcmp.q NN, R000",            None),
  ("vcmp.q NS, R000",            None),
  ("vcmp.q EZ, R000",            None),
  ("vcmp.q FL",                  None),
  ("vcmp.q TR",                  None),
  ("vcmp.q NE, R000",            "invalid"),
  ("vcmp.q NE",                  "invalid"),

  # Some immediate stuff
  ("viim.s S123, 32000",         None),
  ("viim.s S123, -32000",        None),
  ("viim.s S123, 65536",         "out of range"),
  ("viim.s S123, -32769",        "out of range"),
  ("viim.s S123, 128000",        "out of range"),

  # Some rotation stuff
  ("vrot.q R000,S100,[0,0,0,0]", "invalid"),

  # Prefix instructions
  ("vpfxs [0,0,0,0]",            None),
  ("vpfxd [m,0,0,0]",            "cannot contain.*constant"),
  ("vpfxs [,,,]",                None),
  ("vpfxd [,,,]",                None),
  ("vpfxd [x,,,]",               "cannot contain.*swizzle"),
  ("vpfxd ,,,,",                 "invalid operands"),
  ("vpfxd ,,,",                  "invalid operands"),
  ("vpfxd ,,",                   "invalid operands"),

  ("vadd.p R000, R100, R200[x,x]",         None),
  ("vadd.p R000, R100, R200[y,y]",         None),
  ("vadd.p R000, R100, R200[x,x,x]",       "mismatched prefix size.*too many"),
  ("vadd.p R000, R100, R200[y]",           "mismatched prefix size.*too few"),
  ("vadd.s S000, S100, S200[x]",           None),
  ("vadd.s S000, S100, S200[y]"  ,         "swizzle.*out of range"),
  ("vadd.p R000, R100, R200[z,z]",         "swizzle.*out of range"),
  ("vadd.p R000, R100, R200[w,w]",         "swizzle.*out of range"),
  ("vadd.t R000, R100, R200[z,z,z]",       None),
  ("vadd.t R000, R100, R200[w,w,w]",       "swizzle.*out of range"),

  # Prefixed operations and illegal prefixes
  ("vf2id.q R000[-1:1,,,], R100, 12",      "can only do masking in destination"),
  ("vi2f.q R000, R100[1,x,x,y], 12",       "can only perform swizzle in source prefix"),
]


# Invoke "as" for each test using stdin and stdout, and recording the exit code
for inst, errexp in TESTS:
  p = subprocess.Popen([args.asexec],
    stdin=subprocess.PIPE,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE)

  outp = p.communicate(input=(inst + "\n").encode("ascii"))
  p.wait()
  exit_code = p.poll()

  if errexp is None:
    if exit_code != 0:
      print("Test `%s` failed: unexpected error when none was expected" % inst)
      print(outp[1])
  else:
    if exit_code == 0:
      print("Test `%s` failed: expected an error but exit code is zero" % inst)
    else:
      # Match the error code regex
      if not re.search(errexp, outp[1].decode("utf-8")):
        print("Output mismatch in test `%s`!" % inst)
        print(outp[1])



