import collections
import json
import sys

a, b = json.load(open(sys.argv[1])), json.load(open(sys.argv[2]))


def per_seg(d):
    out = collections.defaultdict(list)
    for x in d["segs"]:
        out[x["seg"]].append(x)
    return out


A, B = per_seg(a), per_seg(b)
labels = [x["seg"] for x in b["segs"] if x["seg"] in A and x["seg"] != "khởi động"]
seen, rows = set(), []
for lb in labels:
    if lb in seen:
        continue
    seen.add(lb)
    ta, tb = sum(x["s"] for x in A[lb]), sum(x["s"] for x in B[lb])
    err = any(x["err"] for x in B[lb])
    rows.append((lb, ta, tb, err))
sa, sb = sum(r[1] for r in rows), sum(r[2] for r in rows)
print(f"TỔNG các bước chung: trước {sa:.1f}s → sau {sb:.1f}s ({(sb - sa) / sa * 100:+.0f}%)  ·  lỗi sau: "
      f"{sum(1 for r in rows if r[3])}")
print(f"{'bước':38s} {'trước':>7s} {'sau':>7s} {'chênh':>7s}")
for lb, ta, tb, err in sorted(rows, key=lambda r: r[2] - r[1]):
    print(f"{lb:38s} {ta:7.2f} {tb:7.2f} {tb - ta:+7.2f}" + ("  LỖI " + next(x["err"] for x in B[lb] if x["err"])[:80]
                                                             if err else ""))
segs = set(seen)


def rpc(d):
    r = collections.defaultdict(lambda: [0, 0.0])
    for seg, m, n, sec in d["rpc"]:
        if seg in segs:
            r[m][0] += n
            r[m][1] += sec
    return r


ra, rb = rpc(a), rpc(b)
print(f"\nRPC (cùng các bước): trước {sum(v[0] for v in ra.values())} lệnh / {sum(v[1] for v in ra.values()):.1f}s → "
      f"sau {sum(v[0] for v in rb.values())} lệnh / {sum(v[1] for v in rb.values()):.1f}s")
for m in sorted(set(ra) | set(rb), key=lambda m: -(ra[m][1] + rb[m][1]))[:10]:
    (na, sa_), (nb, sb_) = ra[m], rb[m]
    print(f"  {m:22s} {na:4d}× {sa_:6.2f}s ({sa_ / na * 1000 if na else 0:4.0f} ms)  →  {nb:4d}× {sb_:6.2f}s "
          f"({sb_ / nb * 1000 if nb else 0:4.0f} ms)")


def sleeps(d):
    return sum(sec for seg, w, n, sec in d["sleeps"] if seg in segs)


print(f"\nngủ cứng: trước {sleeps(a):.1f}s → sau {sleeps(b):.1f}s")
