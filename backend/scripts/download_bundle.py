#!/usr/bin/env python3
import io, json, re, sys, time, urllib.request, zipfile

B = sys.argv[1] if len(sys.argv) > 1 else "https://hive-production-7343.up.railway.app"
t0 = time.perf_counter()
try:
    with urllib.request.urlopen(B + "/api/diagnostic-bundle/download", timeout=300) as res:
        cd = res.headers.get("Content-Disposition", "")
        z = res.read()
    ms = int((time.perf_counter() - t0) * 1000)
    m = re.search(r'filename="?([^";]+)', cd)
    fn = m.group(1).strip() if m else "unknown.zip"
    names = zipfile.ZipFile(io.BytesIO(z)).namelist()
    print(json.dumps({"ok": True, "ms": ms, "filename": fn, "zip_entry_count": len(names), "entries": names}))
except Exception as exc:
    print(json.dumps({"ok": False, "ms": int((time.perf_counter() - t0) * 1000), "error": str(exc)[:400]}))
