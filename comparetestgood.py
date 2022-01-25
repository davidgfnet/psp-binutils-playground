
# Copyright 2021 David Guillen Fandos <david@davidgf.net>

# VFPU assembly/disassembly compare test tool
#
# This script will pair two `as` executables (model and exec under test)
# It will assemble instructions and compare binary outputs.
# For speed we do it in one single massive file

import argparse, re, subprocess, tempfile, os, itertools, uuid, collections
from tqdm import tqdm

parser = argparse.ArgumentParser(prog='comparetest')
parser.add_argument('--reference', dest='reference', required=True, help='Path (or executable within PATH) to invoke reference `as`')
parser.add_argument('--undertest', dest='undertest', required=True, help='Path (or executable within PATH) to invoke for `as`')
parser.add_argument('--objcopy', dest='objcopy', required=True, help='Path (or executable within PATH) to invoke MIPS objcopy')
args = parser.parse_args()

ALLCNT = [
  "VFPU_HUGE",
  "VFPU_SQRT2",
  "VFPU_SQRT1_2",
  "VFPU_2_SQRTPI",
  "VFPU_2_PI",
  "VFPU_1_PI",
  "VFPU_PI_4",
  "VFPU_PI_2",
  "VFPU_PI",
  "VFPU_E",
  "VFPU_LOG2E",
  "VFPU_LOG10E",
  "VFPU_LN2",
  "VFPU_LN10",
  "VFPU_2PI",
  "VFPU_PI_6",
  "VFPU_LOG10TWO",
  "VFPU_LOG2TEN",
  "VFPU_SQRT3_2"
]

allrots = [
  ["c", "s", "s", "s"],
  ["s", "c", "0", "0"],
  ["s", "0", "c", "0"],
  ["s", "0", "0", "c"],
  ["c", "s", "0", "0"],
  ["s", "c", "s", "s"],
  ["0", "s", "c", "0"],
  ["0", "s", "0", "c"],
  ["c", "0", "s", "0"],
  ["0", "c", "s", "0"],
  ["s", "s", "c", "s"],
  ["0", "0", "s", "c"],
  ["c", "0", "0", "s"],
  ["0", "c", "0", "s"],
  ["0", "0", "c", "s"],
  ["s", "s", "s", "c"],
  ["c", "-s", "-s", "-s"],
  ["-s", "c", "0", "0"],
  ["-s", "0", "c", "0"],
  ["-s", "0", "0", "c"],
  ["c", "-s", "0", "0"],
  ["-s", "c", "-s", "-s"],
  ["0", "-s", "c", "0"],
  ["0", "-s", "0", "c"],
  ["c", "0", "-s", "0"],
  ["0", "c", "-s", "0"],
  ["-s", "-s", "c", "-s"],
  ["0", "0", "-s", "c"],
  ["c", "0", "0", "-s"],
  ["0", "c", "0", "-s"],
  ["0", "0", "c", "-s"],
  ["-s", "-s", "-s", "c"],
]

def samemtx(reg1, reg2):
  return reg1[1] == reg2[1]

def genregm(mode):
  for mtx in range(8):
    for col in {"p": [0,2], "t": [0,1], "q": [0]}[mode]:
      for row in {"p": [0,2], "t": [0,1], "q": [0]}[mode]:
        for e in "ME":
          yield "%s%d%d%d.%s" % (e, mtx, col, row, mode)

def genregs(mode):
  if mode == "s":
    for com in itertools.product("0123", repeat=3):
      yield "S%s.s" % "".join(com)
  else:
    for mtx in range(8):
      for col in {"p": [0,2], "t": [0,1], "q": [0]}[mode]:
        for row in {"p": [0,2], "t": [0,1], "q": [0]}[mode]:
          for e in "RC":
            yield "%s%d%d%d.%s" % (e, mtx, col, row, mode)

def genhfloat():
  for sign in "-+ ":
    for sp in ["NaN", "Inf", "inf", "0"]:
      yield sign + sp
  for i in range(12):
    for j in range(8):
      yield "%f" % ((1<<i) * (j+1))
  for i in range(8):
    for j in range(0, 256, 13):
      yield "%f" % ((1<<i) * (j+1) * 0.015625)

def regcpu():
  for i in range(28):
    yield "$%d" % i

def regcc():
  for i in range(128, 143, 1):
    yield "$%d" % i

def genregs3(mode):
  for reg in genregs(mode):
    yield (reg,reg,reg)

def genregs2(mode):
  for reg in genregs(mode):
    yield (reg,reg)

def genregm2(mode):
  for mtx1 in range(7):
    for col1 in {"p": [0,2], "t": [0,1], "q": [0]}[mode]:
      for row1 in {"p": [0,2], "t": [0,1], "q": [0]}[mode]:
        for e1 in "ME":
          for mtx2 in range(8):
            for col2 in {"p": [0,2], "t": [0,1], "q": [0]}[mode]:
              for row2 in {"p": [0,2], "t": [0,1], "q": [0]}[mode]:
                for e2 in "ME":
                  if mtx1 != mtx2:
                    yield ("%s%d%d%d.%s" % (e1, mtx1, col1, row1, mode),
                           "%s%d%d%d.%s" % (e2, mtx2, col2, row2, mode))

VTESTS = []

# Branch insts
for i in range(6):
  for cond in "ft":
    for lik in "l ":
      VTESTS.append("bv%s%s %d, 1f\n1:" % (cond, lik, i))

# Load/Store
for i in range(8):
  for op, wbmode in [("l", ""), ("s", ""), ("s", ", wb"), ("s", ", wt")]:
    for mode, regm in [("s", "S"), ("q", "R"), ("q", "C")]:
      for offset in range(0, 4096, 4):
        wbm = wbmode if mode == "q" else ""
        VTESTS.append("%sv.%s %s000, %d($4) %s" % (op, mode, regm, offset, wbm))
        VTESTS.append("%sv.%s %s000, -%d($4) %s" % (op, mode, regm, offset, wbm))

# Prefix instructions
# The syntax was slightly changed since it was quite hard to parse it otherwise
for atype, regpfx, N in [("q", "R", 4), ("t", "R", 3), ("p", "R", 2), ("s", "S", 1)]:
  availchs = ["x","y","z","w"][0:N]
  for chs in itertools.product(availchs + [""], repeat=N):
    for ab in itertools.product("| ", repeat=N):
      if any(chs[i] == "" and ab[i] == "|" for i in range(N)):
        continue

      for neg in itertools.product("- ", repeat=N):
        if any(chs[i] == "" and neg[i] == "-" for i in range(N)):
          continue

        for pfxt in "st":
          exp = ["%s%s%s%s" % (neg[i], ab[i], chs[i], ab[i])
                 for i in range(N)]
          exp = ",".join(exp)
          if N == 4:
            VTESTS.append(
              ("vpfx%s %s" % (pfxt, exp),
              ("vpfx%s [%s]" % (pfxt, exp))))
          VTESTS.append("vadd.%s %s000, %s100, %s200[%s]" % (atype, regpfx, regpfx, regpfx, exp))
          VTESTS.append("vadd.%s %s000, %s100[%s], %s200" % (atype, regpfx, regpfx, exp, regpfx))

for c1,c2,c3,c4 in itertools.product(["x","y","z","w","","0","1","2","1/2","3","1/3","1/4","1/6"], repeat=4):
  for pfxt in "st":
    VTESTS.append(
      ("vpfx%s %s, %s, %s, %s" % (pfxt, c1, c2, c3, c4),
      ("vpfx%s [%s, %s, %s, %s]" % (pfxt, c1, c2, c3, c4))))

for c1,c2,c3,c4 in itertools.product(["", "m", "-1:1", "[-1:1]", "0:1", "[0:1]"], repeat=4):
  VTESTS.append(
    ("vpfxd %s,%s,%s,%s" % (c1,c2,c3,c4),
    ("vpfxd [%s,%s,%s,%s]" % (c1,c2,c3,c4))))

for c1,c2,c3,c4 in itertools.product(["", "m", "-1:1", "0:1"], repeat=4):
  VTESTS.append("vadd.q R000[%s,%s,%s,%s], R000, R200" % (c1,c2,c3,c4))

for atype, regpfx, N in [("q", "R", 4), ("t", "R", 3), ("p", "R", 2), ("s", "S", 1)]:
  for chs in itertools.product(["", "m", "-1:1", "0:1"], repeat=N):
    exp = ",".join([chs[i] for i in range(N)])
    VTESTS.append("vadd.%s %s000[%s], %s100, %s200" % (atype, regpfx, exp, regpfx, regpfx))

# vrot insts are hard too, .p encoding is ambigous :)
#for c, mode in [(2, "p"), (3, "t"), (4, "q")]:
for c, mode in [(3, "t"), (4, "q")]:
  for perm in allrots:
    for regd in genregs(mode):
      VTESTS.append("vrot.%s %s, S733.s, [%s]" % (mode, regd, ",".join(perm[:c])))


# 3 operand VFPU instructions
for op in ["add", "sub", "div", "mul", "min", "max", "sge", "slt", "scmp"]:
  for mode in "sptq":
    for regd, regs, regt in genregs3(mode):
      VTESTS.append("v%s.%s %s, %s, %s" % (op, mode, regd, regs, regt))

for regd in genregs("s"):
  for regs, regt in genregs2("s"):
    VTESTS.append("vsbn.s %s, %s, %s" % (regd, regs, regt))
  for regs in genregs("s"):
    for imm in range(0, 256, 17):
      VTESTS.append("vwbn.s %s, %s, %d" % (regd, regs, imm))
      VTESTS.append("vwbn.s %s, %s, 0x%x" % (regd, regs, imm))

for regd in genregs("q"):
  for regs, regt in genregs2("q"):
    if not samemtx(regd, regs) and not samemtx(regd, regt):
      VTESTS.append("vqmul.q %s, %s, %s" % (regd, regs, regt))

for op in ["dot", "hdp"]:
  for mode in "ptq":
    for regs, regt in genregs2(mode):
      for regd in genregs("s"):
        VTESTS.append("v%s.%s %s, %s, %s" % (op, mode, regd, regs, regt))

for op in ["crs", "crsp"]:
  for regd, regs, regt in genregs3("t"):
    VTESTS.append("v%s.%s %s, %s, %s" % (op, "t", regd, regs, regt))

for mode in "ptq":
  for regd, regs in genregm2(mode):
    VTESTS.append("vmmul.%s %s, %s, %s" % (mode, regd, regs, regs))
  for regd, regs in genregm2(mode):
    for regt in ["S700.s", "S712.s", "S732.s", "S720.s", "S733.s"]:
      VTESTS.append("vmscl.%s %s, %s, %s" % (mode, regd, regs, regt))
  for regd, regs in genregs2(mode):
    for regt in genregs("s"):
      VTESTS.append("vscl.%s %s, %s, %s" % (mode, regd, regs, regt))

for nmode, mode in [(4, "q"), (3, "t"), (2, "p")]:
  for regd, regt in genregs2(mode):
    for regs in genregm(mode):
      if not samemtx(regd, regs) and not samemtx(regd, regt):
        VTESTS.append("vtfm%d.%s %s, %s, %s" % (nmode, mode, regd, regs, regt))
        VTESTS.append("vhtfm%d.%s %s, %s, %s" % (nmode, mode, regd, regs, regt))

for mode in "sptq":
  for regd, regs in genregs2(mode):
    for op in ["cmov", "cmovt", "cmovf"]:
      for code in range(7):
        VTESTS.append("v%s.%s %s, %s, %s" % (op, mode, regd, regs, code))
  for regd, regs in genregs2(mode):
    for op in "f2in", "f2iz", "f2iu", "f2id", "i2f":
      for code in range(32):
        VTESTS.append("v%s.%s %s, %s, %s" % (op, mode, regd, regs, code))

# 2 operand VFPU instructions
for op in ["mov", "abs", "neg", "sgn", "rcp", "rsq", "sin", "cos", "exp2", "log2", "sqrt", "asin",
           "nrcp", "nsin", "rexp2", "ocp", "sat0", "sat1"]:
  for mode in "sptq":
    for regd, regs in genregs2(mode):
      VTESTS.append("v%s.%s %s, %s" % (op, mode, regd, regs))

for op in ["bfy1"]:
  for mode in "pq":
    for regd, regs in genregs2(mode):
      VTESTS.append("v%s.%s %s, %s" % (op, mode, regd, regs))

for dmode, smode in [("p", "q"), ("s", "p")]:
  for regd in genregs(dmode):
    for regs in genregs(smode):
      for op in ["i2us", "i2s", "f2h"]:
        VTESTS.append("v%s.%s %s, %s" % (op, smode, regd, regs))
      for op in ["us2i", "s2i", "socp", "h2f"]:
        VTESTS.append("v%s.%s %s, %s" % (op, dmode, regs, regd))

for regd in genregs("s"):
  for regs, regt in genregs2("p"):
    VTESTS.append("vdet.p %s, %s, %s" % (regd, regs, regt))

for op in ["i2uc", "i2c"]:
  for regd in genregs("s"):
    for regs in genregs("q"):
      VTESTS.append("v%s.q %s, %s" % (op, regd, regs))

for op in ["t4444", "t5551", "t5650"]:
  for regd in genregs("p"):
    for regs in genregs("q"):
      VTESTS.append("v%s.q %s, %s" % (op, regd, regs))

for op in ["srt1", "srt2", "srt3", "srt4", "bfy2"]:
  for regd, regs in genregs2("q"):
    VTESTS.append("v%s.%s %s, %s" % (op, "q", regd, regs))

for op in ["avg", "fad"]:
  for mode in "ptq":
    for regs in genregs(mode):
      for regd in genregs("s"):
        VTESTS.append("v%s.%s %s, %s" % (op, mode, regd, regs))

for op in ["sbz", "lgb"]:
  for regd, regs in genregs2("s"):
    VTESTS.append("v%s.s %s, %s" % (op, regd, regs))

for mode in "ptq":
  for regd, regs in genregm2(mode):
    VTESTS.append("vmmov.%s %s, %s" % (mode, regd, regs))

# Unary VFPU instructions
for op in ["zero", "one", "rndi", "rndf1", "rndf2"]:
  for mode in "sptq":
    for regd in genregs(mode):
      VTESTS.append("v%s.%s %s" % (op, mode, regd))

for mode in "pq":
  for regd in genregs(mode):
    VTESTS.append("vidt.%s %s" % (mode, regd))

for op in ["zero", "one", "idt"]:
  for mode in "ptq":
    for regd in genregm(mode):
      VTESTS.append("vm%s.%s %s" % (op, mode, regd))

# Special insts
for mode in "sptq":
  for regd in genregs(mode):
    for ct in ALLCNT:
      VTESTS.append("vcst.%s %s, %s" % (mode, regd, ct))

for mode in "sptq":
  for regs, regt in genregs2(mode):
    for ct in ["FL", "EQ", "NE", "GT", "fl", "eq", "ne", "gt"]:
      VTESTS.append("vcmp.%s %s, %s, %s" % (mode, ct, regs, regt))
    for ct in ["NN", "NZ", "nn", "nz"]:
      VTESTS.append("vcmp.%s %s, %s" % (mode, ct, regs))
    for ct in ["FL", "TR", "fl", "tr"]:
      VTESTS.append("vcmp.%s %s" % (mode, ct))

# Immediate insts
for regd in genregs("s"):
  for imm in genhfloat():
    VTESTS.append("vfim.s %s, %s" % (regd, imm))
  for imm in range(0, 1 << 16, 13*17):
    VTESTS.append("viim.s %s, %d" % (regd, imm))

# Interlock insts
for cpureg in regcpu():
  for ccreg in regcc():
    VTESTS.append("mtvc %s, %s" % (cpureg, ccreg))
    VTESTS.append("mfvc %s, %s" % (cpureg, ccreg))
  for vreg in genregs("s"):
    VTESTS.append("mtv %s, %s" % (cpureg, vreg))
    VTESTS.append("mfv %s, %s" % (cpureg, vreg))

for ccreg in regcc():
  for vreg in genregs("s"):
    VTESTS.append("vmtvc %s, %s" % (ccreg, vreg))
    VTESTS.append("vmfvc %s, %s" % (vreg, ccreg))

for i in range(0, 1000, 13):
  VTESTS.append("vsync %d" % i)

VTESTS.append("vflush")
VTESTS.append("vsync")


def tmpfile():
  return "/tmp/as-test-%s" % str(uuid.uuid4())

def runtest(instlist):
  oref = tmpfile()
  otst = tmpfile()
  bref = tmpfile()
  btst = tmpfile()

  for fn in [oref, otst, bref, btst]:
    if os.path.exists(fn):
      os.unlink(fn)

  iref = ".set noat\n.set noreorder\n" + "\n".join(x[0] if isinstance(x, tuple) else x for x in instlist) + "\n"
  itst = ".set noat\n.set noreorder\n" + "\n".join(x[1] if isinstance(x, tuple) else x for x in instlist) + "\n"
  print("Test size (asm): %d KB" % (len(iref)/1024))

  p1 = subprocess.Popen([args.reference, '-o', oref], stdin=subprocess.PIPE)
  p2 = subprocess.Popen([args.undertest, '-o', otst], stdin=subprocess.PIPE)

  ref_outp = p1.communicate(input=iref.encode("ascii"))
  aut_outp = p2.communicate(input=itst.encode("ascii"))

  p1.wait()
  p2.wait()

  ref_exit_code = p1.poll()
  aut_exit_code = p2.poll()

  if ref_exit_code != 0 or aut_exit_code != 0:
    print("Failed assembly!")
  else:
    # Now check that the binary output is identical
    p1 = subprocess.Popen([args.objcopy, '-O', 'binary', '--only-section=.text', oref, bref],
      stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    p2 = subprocess.Popen([args.objcopy, '-O', 'binary', '--only-section=.text', otst, btst],
      stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    p1.wait()
    p2.wait()
    ref_exit_code = p1.poll()
    aut_exit_code = p2.poll()

    if open(bref, "rb").read() != open(btst, "rb").read():
      print("Mismatch binary output!")

  for fn in [oref, otst, bref, btst]:
    if os.path.exists(fn):
      os.unlink(fn)

# Invoke "as" for each test using stdin and stdout, and recording the exit code
runtest(VTESTS)

