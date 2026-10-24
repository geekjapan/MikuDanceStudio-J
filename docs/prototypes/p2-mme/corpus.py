import hashlib, json, os, re, subprocess, sys, collections
C = "/work/vkd3d/bin/vkd3d-compiler"; NAGA = "/work/naga/bin/naga"
env = dict(os.environ, LD_LIBRARY_PATH="/work/vkd3d/lib")
def run(args, inp=None):
    p = subprocess.run(args, input=inp, capture_output=True, env=env, timeout=120)
    return p.returncode, p.stdout, p.stderr.decode("utf-8", "replace")
def err_key(s):
    lines = [l for l in s.splitlines() if re.search(r"\bE\d{4}\b|error|Unsupported|not supported|Failed", l, re.I)]
    if not lines: return (s.strip().splitlines() or ["?"])[-1][:120]
    m = re.sub(r"^.*?:\d+:\d+: ", "", lines[0]); m = re.sub(r'"[^"]*"|\'[^\']*\'', '"…"', m)
    return m[:140]
status_rows = []
seen = {}; stats = collections.Counter(); errs = collections.defaultdict(collections.Counter)
def ci_resolve(base, rel):
    cur = base
    for part in rel.replace("\\", "/").split("/"):
        if part in ("", "."): continue
        if part == "..": cur = os.path.dirname(cur); continue
        hit = [n for n in os.listdir(cur) if n.lower() == part.lower()]
        if not hit: raise FileNotFoundError(rel)
        cur = os.path.join(cur, hit[0])
    return cur
INC = re.compile(r'^[ \t]*#[ \t]*include[ \t]*"([^"]+)"', re.M)
def expand(path, stack, root=None):
    root = root or os.path.dirname(path)
    raw = open(path, "rb").read()
    for enc in ("utf-8", "cp932"):
        try: txt = raw.decode(enc); break
        except UnicodeDecodeError: pass
    if path in stack: return ""
    stack = stack | {path}
    def sub(m):
        try: p = ci_resolve(root, m.group(1)); stats["inc_root"] += 1
        except FileNotFoundError: p = ci_resolve(os.path.dirname(path), m.group(1)); stats["inc_parent"] += 1
        return expand(p, stack, root)
    return INC.sub(sub, txt)
STR2 = re.compile(r'"((?:[^"\\]|\\.)*)"\s*"')
def shader_only(t):
    while True:
        n = STR2.sub(lambda m: '"' + m.group(1), t)
        if n == t: break
        t = n
    out, i = [], 0
    for m in re.finditer(r"\btechnique\b", t):
        if m.start() < i: continue
        j = t.find("{", m.end()); depth = 0; k = j
        while k < len(t):
            depth += {"{": 1, "}": -1}.get(t[k], 0); k += 1
            if depth == 0: break
        out.append(t[i:m.start()]); i = k
        out.append("\n" * t[m.start():k].count("\n"))
    out.append(t[i:]); t = "".join(out)
    if os.environ.get("SAMPLER_FIX"): t = re.sub(r"\bsampler2D(?=\s+\w+\s*[,)])", "sampler", t)
    return t
files = []
for root in sys.argv[1:]:
    for d, _, fs in os.walk(root):
        files += [os.path.join(d, f) for f in fs if f.lower().endswith(".fx")]
COMPILE = re.compile(r"compile\s+([vp]s_[0-9]_[0-9a-z]+)\s+(\w+)\s*\(([^;]*?)\)\s*;")
for path in sorted(files):
    raw = open(path, "rb").read()
    for enc in ("utf-8", "cp932"):
        try: txt = raw.decode(enc); break
        except UnicodeDecodeError: pass
    tmp = "/tmp/src/" + hashlib.md5(path.encode()).hexdigest()
    os.makedirs("/tmp/src", exist_ok=True)
    src = os.path.join(os.path.dirname(path), ".__u8_" + os.path.basename(path))
    src = path  # includes resolve relative to original dir
    try: expanded = expand(path, set())
    except FileNotFoundError as ex: stats["file_include_missing"] += 1; errs["include"][str(ex)[:120]] += 1; continue
    open(tmp + ".in.hlsl", "w").write(expanded)
    rc, out, e = run([C, "-x", "hlsl", "-E", tmp + ".in.hlsl"])
    if rc: stats["file_preprocess_fail"] += 1; errs["preprocess"][err_key(e)] += 1; continue
    pre = out.decode("utf-8", "replace")
    h = hashlib.md5(out).hexdigest()
    if h in seen: stats["file_dup"] += 1; continue
    seen[h] = path; stats["file_unique"] += 1
    entries = set(COMPILE.findall(pre))
    pre = shader_only(pre)
    open(tmp + ".hlsl", "w").write(pre)
    for prof, fn, args in entries:
        stats["shader_total"] += 1
        row = [os.path.relpath(path, "/"), prof, fn, args.strip()]
        status_rows.append(row); row.append("FAIL")
        entry, srcfile = fn, tmp + ".hlsl"
        if args.strip():
            m = re.search(r"([\w:]+)\s+" + fn + r"\s*\(([^)]*)\)\s*(:\s*\w+)?\s*\{", pre)
            if not m: stats["wrap_fail"] += 1; errs["wrap"]["signature not found"] += 1; continue
            ret, params, rsem = m.group(1), [p.strip() for p in m.group(2).split(",") if p.strip()], m.group(3) or ""
            argv = [a.strip() for a in re.split(r",(?![^(]*\))", args)]
            call, decl, ai = [], [], 0
            for i, p in enumerate(params):
                if re.match(r"uniform\b", p):
                    call.append(argv[ai] if ai < len(argv) else "0"); ai += 1
                else:
                    nm = re.sub(r"\s*:.*$", "", p).split()[-1]; nm = re.sub(r"\[.*", "", nm)
                    decl.append(p); call.append(nm)
            body = ("return " if ret != "void" else "") + f"{fn}({', '.join(call)});"
            wrap = f"\n{ret} __mme_entry({', '.join(decl)}) {rsem} {{ {body} }}\n"
            srcfile = tmp + "_" + fn + "_" + hashlib.md5(args.encode()).hexdigest()[:6] + ".hlsl"
            open(srcfile, "w").write(pre + wrap); entry = "__mme_entry"; stats["shader_wrapped"] += 1
        if os.environ.get("DIRECT"):
            rc, _, e = run([C, "-x", "hlsl", "-p", prof, "-e", entry, "-b", "spirv-binary", "-o", "/tmp/s.spv", srcfile])
            if rc:
                stats["direct_fail"] += 1; errs["hlsl->spirv"][err_key(e)] += 1
                k = err_key(e)[:5]
                if errs["sample"][k] < 2:
                    errs["sample"][k] += 1
                    m = re.search(r":(\d+):\d+: E", e)
                    ln = open(srcfile).read().splitlines()[int(m.group(1)) - 1].strip()[:150] if m else ""
                    print("SAMPLE", k, path, prof, fn, "|", ln, "|", e.strip().splitlines()[-1][:160])
                continue
            rc, _, e = run(["spirv-val", "/tmp/s.spv"])
            if rc: stats["spirv_val_fail"] += 1; errs["spirv-val"][err_key(e)] += 1; continue
            stats["spirv_ok"] += 1
        else:
          rc, _, e = run([C, "-x", "hlsl", "-p", prof, "-e", entry, "-b", "d3dbc", "-o", "/tmp/s.d3dbc", srcfile])
          if rc:
            stats["hlsl_fail"] += 1; errs["hlsl->d3dbc"][err_key(e)] += 1
            for nm in re.findall(r'E5005: No compatible \d+ parameter declaration for "(\w+)"', e): errs["E5005 fn"][nm] += 1
            continue
          rc, _, e = run([C, "-x", "d3dbc", "-b", "spirv-binary", "-o", "/tmp/s.spv", "/tmp/s.d3dbc"])
          if rc: stats["spv_fail"] += 1; errs["d3dbc->spirv"][err_key(e)] += 1; continue
          rc, _, e = run(["spirv-val", "/tmp/s.spv"])
          if rc: stats["spirv_val_fail"] += 1; errs["spirv-val"][err_key(e)] += 1; continue
          stats["spirv_ok"] += 1
        if prof.startswith("vs"):
            rc, asm, e = run(["spirv-dis", "--raw-id", "/tmp/s.spv"])
            asm = asm.decode()
            m = re.search(r"OpDecorate (%\d+) BuiltIn PointSize", asm)
            if m:
                v = m.group(1)
                lines = [l for l in asm.splitlines() if not re.search(rf"(OpName|OpDecorate|OpStore) {v}\b|^\s*{v} = OpVariable", l)]
                asm = "\n".join(re.sub(rf" {v}\b(?=.*$)", "", l) if "OpEntryPoint" in l else l for l in lines) + "\n"
                open("/tmp/s.spvasm", "w").write(asm)
                rc, _, e = run(["spirv-as", "/tmp/s.spvasm", "-o", "/tmp/s.spv"])
                if rc or run(["spirv-val", "/tmp/s.spv"])[0]: stats["psize_strip_fail"] += 1; errs["psize-strip"][err_key(e)] += 1; continue
                stats["psize_stripped"] += 1
        row[-1] = "OK"
        for o in ("wgsl", "metal", "hlsl"):
            rc, _, e = run([NAGA, "/tmp/s.spv", "/tmp/s." + o])
            if rc: row[-1] = "NAGA_FAIL"
            if rc: errs["naga->" + o][err_key(e)] += 1
            else: stats["naga_" + o + "_ok"] += 1
if os.environ.get("LIST"):
    with open(os.environ["LIST"], "w") as f:
        for row in sorted(status_rows): f.write("\t".join(row) + "\n")
print(json.dumps(stats, indent=1))
for k, c in errs.items():
    print("==", k)
    for m, n in c.most_common(12): print(f"  {n:4d}  {m}")
