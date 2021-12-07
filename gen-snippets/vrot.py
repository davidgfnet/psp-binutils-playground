
import collections

results = collections.defaultdict(list)

for N in [2,3,4]:
  for i in range(16):
    c = i & 3
    s = i >> 2
    if c == s:
      ret = ["s"] * N
    else:
      ret = ["0"] * N

    if s < len(ret):
      ret[s] = "s"
    if c < len(ret):
      ret[c] = "c"

    enc = 0
    for e in ret:
      enc <<= 2
      if e == 's':
        enc += 2
      elif e == 'c':
        enc += 3

    results[N].append((enc, "".join(ret)))

for i in range(16):
  print("  {{%2d, %2d, %3d}, %2d},  // %s" % (results[2][i][0], results[3][i][0], results[4][i][0], i, results[4][i][1]))

