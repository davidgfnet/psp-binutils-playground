
# Copyright 2021 David Guillen Fandos <david@davidgf.net>

# VFPU assembly/disassembly compare test tool
#
# This script will pair two `as` executables (model and exec under test)
# It will assemble instructions and compare binary outputs.

import argparse, re, subprocess, tempfile, os, itertools, uuid, collections
from tqdm import tqdm
from concurrent import futures

parser = argparse.ArgumentParser(prog='comparetest')
parser.add_argument('--reference', dest='reference', required=True, help='Path (or executable within PATH) to invoke reference `as`')
parser.add_argument('--undertest', dest='undertest', required=True, help='Path (or executable within PATH) to invoke for `as`')
parser.add_argument('--objcopy', dest='objcopy', required=True, help='Path (or executable within PATH) to invoke MIPS objcopy')
args = parser.parse_args()

# The 2.23 toolchain has a couple bugs :)
buggy_toolchain = frozenset([
  "0,0,0,s", "0,0,0,c", "0,0,0,-s", "0,0,s,0",
  "0,0,c,0", "0,0,-s,0", "0,s,0,0", "0,c,0,0",
  "0,-s,0,0", "s,0,0,0", "c,0,0,0", "-s,0,0,0",
])

TESTS = []

# vrot immediates are a paaaain
for com in itertools.product(["0", "s", "c", "-s"], repeat=4):
  arg = ",".join(com)
  if arg not in buggy_toolchain:
    TESTS.append("vrot.q R000.q, S100.s, [%s]" % arg)

for com in itertools.product(["0", "s", "c", "-s"], repeat=3):
  TESTS.append("vrot.t R000.t, S100.s, [%s]" % ",".join(com))


# Exhaustive register naming test
for mtx in range(8):
  for col in range(4):
    for row in range(4):
      TESTS.append("vadd.s S%u%u%u.s, S000.s, S000.s" % (mtx, col, row))

for mode in "ptq":
  for mtx in range(8):
    for col in range(4):
      for row in range(4):
        for t in "CR":
          TESTS.append("vadd.%s %s%u%u%u.%s, %s000.%s, %s000.%s" % (
                       mode, t, mtx, col, row, mode, t, mode, t, mode))

for mode in "ptq":
  for mtx in range(8):
    for col in range(4):
      for row in range(4):
        for t in "ME":
          TESTS.append("vmmov.%s %s%u%u%u.%s, %s100.%s" % (
                       mode, t, mtx, col, row, mode, t, mode))
          # vmmul is a bit special with register VS
          TESTS.append("vmmul.%s %s200.%s, %s%u%u%u.%s, %s100.%s" % (
                       mode, t, mode, t, mtx, col, row, mode, t, mode))
          TESTS.append("vmmul.%s %s200.%s, %s100.%s, %s%u%u%u.%s" % (
                       mode, t, mode, t, mode, t, mtx, col, row, mode))

# Check register collision. Should agree.
for mode in "ptq":
  for mtx1 in range(8):
    for col1 in range(4):
      for row1 in range(4):
        for t1 in "CR":
          for mtx2 in range(8):
            for col2 in range(4):
              for row2 in range(4):
                for t2 in "CR":
                  TESTS.append("vmmul.%s %s%u%u%u.%s, %s%u%u%u.%s, %s000.%s" % (
                               mode, t, mtx1, col1, row1, mode, t, mtx2, col2, row2, mode, t, mode))
                  TESTS.append("vmmul.%s %s%u%u%u.%s, %s000.%s, %s%u%u%u.%s" % (
                               mode, t, mtx1, col1, row1, mode, t, mode, t, mtx2, col2, row2, mode))

def tmpfile():
  return "/tmp/as-test-%s" % str(uuid.uuid4())

def runtest(inst):
  oref = tmpfile()
  otst = tmpfile()
  bref = tmpfile()
  btst = tmpfile()

  for fn in [oref, otst, bref, btst]:
    if os.path.exists(fn):
      os.unlink(fn)

  p1 = subprocess.Popen([args.reference, '-o', oref],
    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
  p2 = subprocess.Popen([args.undertest, '-o', otst],
    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

  ref_outp = p1.communicate(input=(inst + "\n").encode("ascii"))
  aut_outp = p2.communicate(input=(inst + "\n").encode("ascii"))

  p1.wait()
  p2.wait()

  ref_exit_code = p1.poll()
  aut_exit_code = p2.poll()

  if ref_exit_code != aut_exit_code:
    print("Exit code mismatch for test `%s`" % inst)
  elif aut_exit_code == 0:
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
      print("Mismatch binary output for test `%s`" % inst)

  for fn in [oref, otst, bref, btst]:
    if os.path.exists(fn):
      os.unlink(fn)

# Invoke "as" for each test using stdin and stdout, and recording the exit code
tp = futures.ProcessPoolExecutor(64)
res = collections.deque()
for inst in tqdm(TESTS):
  res.append(tp.submit(runtest, inst))
  while len(res) > 2048:
    res.popleft().result()

while len(res) > 0:
  res.popleft().result()

