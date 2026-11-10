import collections
import json
import sys

d = json.load(open(sys.argv[1]))
segs, steps = d["segs"], d["steps"]
total = sum(x["s"] for x in segs)
route_by_seg = collections.defaultdict(float)
for st in steps:
    route_by_seg[st["seg"]] += st["ms"] / 1000

print(f"TỔNG {total:.1f}s · {len(segs)} bước kịch bản · {len(steps)} bước route · lỗi {sum(1 for x in segs if x['err'])}")
print("\n== A. từng bước kịch bản (tổng | route | thao tác) — chậm nhất trước")
for x in sorted(segs, key=lambda x: -x["s"]):
    r = route_by_seg.get(x["seg"], 0)
    print(f"  {x['seg']:38s} {x['s']:6.2f} | {r:5.2f} | {x['s'] - r:5.2f}" + (f"   LỖI {x['err'][:90]}" if x["err"] else ""))

print("\n== B. route theo loại bước")
g = collections.defaultdict(list)
for st in steps:
    kind = "back mù" if st["how"].startswith("mù") else f"{st['g']} ({st['how'].split(',')[0][:22]})"
    g[kind].append(st)
for k, v in sorted(g.items(), key=lambda kv: -sum(s["ms"] for s in kv[1])):
    ms = [s["ms"] for s in v]
    print(f"  {k:38s} {len(v):3d} bước  tổng {sum(ms)/1000:6.2f}s  TB {sum(ms)/len(ms):5.0f} ms  max {max(ms):5d}")

print("\n== C. route: thời gian theo pha (cộng mọi bước)")
ph = collections.defaultdict(float)
for st in steps:
    for k, v in st["ph"].items():
        ph[k] += v
for k, v in sorted(ph.items(), key=lambda kv: -kv[1]):
    print(f"  {k:10s} {v:6.2f}s")

print("\n== D. 12 bước route chậm nhất")
for st in sorted(steps, key=lambda s: -s["ms"])[:12]:
    print(f"  {st['ms']:5d} ms  {st['src'][:34]:34s} → {st['to'][:34]:34s} {st['g']:5s} {st['how'][:40]}  {st['ph']}")

print("\n== E. RPC uiautomator2 (toàn kịch bản)")
r = collections.defaultdict(lambda: [0, 0.0])
for seg, m, n, sec in d["rpc"]:
    r[m][0] += n; r[m][1] += sec
rt = sum(v[1] for v in r.values())
print(f"  tổng {sum(v[0] for v in r.values())} RPC, {rt:.1f}s ({rt / total * 100:.0f}% thời gian)")
for m, (n, sec) in sorted(r.items(), key=lambda kv: -kv[1][1])[:12]:
    print(f"  {m:24s} {n:5d} lần  {sec:6.2f}s  TB {sec / n * 1000:5.0f} ms")

print("\n== F. ngủ cứng theo chỗ gọi")
sl = collections.defaultdict(lambda: [0, 0.0])
for seg, where, n, sec in d["sleeps"]:
    sl[where][0] += n; sl[where][1] += sec
st_ = sum(v[1] for v in sl.values())
print(f"  tổng {st_:.1f}s ({st_ / total * 100:.0f}%)")
for w, (n, sec) in sorted(sl.items(), key=lambda kv: -kv[1][1])[:12]:
    print(f"  {w:42s} {n:5d} lần  {sec:6.2f}s")

print("\n== G. lệnh adb (subprocess)")
a = collections.defaultdict(lambda: [0, 0.0])
for seg, cmd, n, sec in d["adb"]:
    a[cmd][0] += n; a[cmd][1] += sec
for c, (n, sec) in sorted(a.items(), key=lambda kv: -kv[1][1])[:8]:
    print(f"  {c:42s} {n:5d} lần  {sec:6.2f}s  TB {sec / n * 1000:5.0f} ms")

print("\n== H. hàm Ui + goto: thời gian riêng (trừ hàm con)")
u = collections.defaultdict(lambda: [0, 0.0])
for seg, f, n, sec in d["ui"]:
    u[f][0] += n; u[f][1] += sec
for f, (n, sec) in sorted(u.items(), key=lambda kv: -kv[1][1])[:14]:
    print(f"  {f:16s} {n:5d} lần  {sec:6.2f}s  TB {sec / n * 1000:5.0f} ms")
