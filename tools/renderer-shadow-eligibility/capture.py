import copy
import importlib.util
import json
import math
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import shutil
import struct
import subprocess
import sys
import tarfile
import time

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
TRANSPORT_MODES = {}
spec = importlib.util.spec_from_file_location('sample_helpers', ROOT/'tools/renderer-sample-readback/run.py')
h = importlib.util.module_from_spec(spec)
spec.loader.exec_module(h)
require = h.require
PREFIX = 'tools/renderer-shadow-eligibility/'
ORIGINAL = '2210a28022844b373e1146a91bf0def2f4be8f0b'
SELECTED = 'std::thread::current().name() == Some("selfshadow_30")'
SCENE = '''    if std::thread::current().name() == Some("selfshadow_30") {
        eprintln!("SH_SCENE {} {} {} {}", frame, pmm.models.len(), pmm.accessories.len(), SAMPLES_8X.len());
        for (ordinal, m) in pmm.models.iter().enumerate() {
            eprintln!("SH_MODEL {} {} {} {} {}", ordinal, m.slot, m.selection.load_complete, m.toon, m.path.text);
        }
        for (ordinal, a) in pmm.accessories.iter().enumerate() {
            eprintln!("SH_ACCESSORY {} {} {} {} {} {}", ordinal, a.slot, a.state.opacity_visible, a.state.shadow, a.state.additive, a.path.text);
        }
    }
'''
UPLOAD = '''            if std::thread::current().name() == Some("selfshadow_30") {
                let ordinal = frame.models.iter().position(|(m, _)| std::ptr::eq(*m, mesh)).expect("frame ordinal");
                for (i, m) in skin.materials.iter().enumerate() {
                    eprintln!("SH_UPLOAD {} {} {} {}", ordinal, i, diffuse(m)[3].to_bits(), m.edge_color[3].to_bits());
                }
            }
'''
ENCODE = '''        let mut shadow_observed_draws = 0usize;
        if std::thread::current().name() == Some("selfshadow_30") {
            eprintln!("SH_ENCODE {} {} {} {} {}", shift[0].to_bits(), shift[1].to_bits(), samples, frame.models.len(), stage.accessories.len());
            for (ordinal, (&(mesh, _), key)) in frame.models.iter().zip(Self::keys(frame)).enumerate() {
                let res = &self.models[&key];
                for (i, (m, alpha)) in mesh.materials.iter().zip(&res.alpha).enumerate() {
                    eprintln!("SH_CANDIDATE M {} {} {} {} {} {}", ordinal, i, m.start, m.count, m.flags, alpha.to_bits());
                }
            }
            for (ordinal, (a, key)) in stage.accessories.iter().zip(Self::accessory_keys(stage)).enumerate() {
                let res = &self.models[&key];
                for (i, (m, alpha)) in a.mesh.accessory.materials.iter().zip(&res.alpha).enumerate() {
                    eprintln!("SH_CANDIDATE A {} {} {} {} {} {} {}", ordinal, i, m.diffuse[3].to_bits(), alpha.to_bits(), u8::from(a.state.visible), u8::from(a.state.shadow_enabled), u8::from(a.state.additive_blend));
                }
            }
        }
'''
DRAW = '''                        if std::thread::current().name() == Some("selfshadow_30") {
                            let ordinal = frame.models.iter().position(|(v, _)| std::ptr::eq(*v, mesh)).expect("frame ordinal");
                            let material = mesh.materials.iter().position(|v| std::ptr::eq(v, m)).expect("material ordinal");
                            shadow_observed_draws += 1;
                            eprintln!("SH_DRAW M {} {} {} {}", ordinal, material, m.start, m.count);
                        }
'''


def generated(base, observed):
    changes = {h.COMMON: h.COMMON_CHANGES}
    if observed:
        changes[h.GOLDEN] = [
            ('        physics.step().unwrap();\n', '        if '+SELECTED+' { eprintln!("SH_STEP"); }\n'),
            ('    let physics = stepped(pmm, frame);\n', SCENE),
        ]
        renderer = (base/h.RENDERER).read_text()
        endpoint = '                        pass.draw_indexed(m.start..m.start + m.count, 0, 0..1);\n'
        first = renderer.index('        if self_shadow_map(stage).is_some() {\n')
        last = renderer.index('        {\n            let mut pass = encoder.begin_render_pass', first)
        scope = renderer[first:last]
        require(scope.count(endpoint) == 1, 'shadow endpoint scope/uniqueness')
        anchor = scope[:scope.index(endpoint)]
        changes[h.RENDERER] = [
            ('            p.alpha = skin.materials.iter().map(|m| diffuse(m)[3]).collect();\n', UPLOAD),
            ('        let mut encoder = self.device.create_command_encoder(&Default::default());\n', ENCODE),
            (scope, '        if '+SELECTED+' { eprintln!("SH_END {}", shadow_observed_draws); }\n'),
            (anchor, DRAW),
        ]
    return {name: h.insertions((base/name).read_text(), rows) for name, rows in changes.items()}


def source_inventory(root):
    result = {}
    for p in sorted(root.rglob('*')):
        require(not p.is_symlink() and (p.is_file() or p.is_dir()), 'source symlink/special entry')
        if p.is_file():
            result[p.relative_to(root).as_posix()] = {'sha256':h.digest(p.read_bytes()),'mode':TRANSPORT_MODES.get(str(p.resolve()),p.stat().st_mode & 0o777)}
    return result


def validate_source(base, dest, observed):
    expected = source_inventory(base)
    for name, (text, _) in generated(base, observed).items():
        expected[name] = expected[name] | {'sha256': h.digest(text.encode())}
    require(source_inventory(dest) == expected, 'generated source/inverse/mode drift')
    return expected


def words(text, count):
    values = text.split()
    require(len(values) == count and all(re.fullmatch(r'0|[1-9][0-9]*', v) for v in values), 'capture integer wire')
    result = list(map(int, values))
    require(all(v <= 0xffffffff for v in result), 'capture u32 overflow')
    return result


def finite(bits):
    require(type(bits) is int and 0 <= bits <= 0xffffffff and
            math.isfinite(struct.unpack('<f', struct.pack('<I', bits))[0]), 'nonfinite/overflow float word')
    return bits


def parse_capture(raw, contract, projection):
    lines = [v for v in raw.splitlines() if v.startswith('SH_')]
    require(lines and all(v.split()[0] in {'SH_STEP','SH_SCENE','SH_MODEL','SH_ACCESSORY','SH_UPLOAD','SH_ENCODE','SH_CANDIDATE','SH_DRAW','SH_END'} for v in lines), 'unknown/missing capture record')
    at = 0
    def take(tag):
        nonlocal at
        require(at < len(lines) and lines[at].startswith(tag+' '), 'missing/ordered capture '+tag)
        value = lines[at][len(tag)+1:]
        at += 1
        return value
    while at < len(lines) and lines[at] == 'SH_STEP':
        at += 1
    steps = at
    frame, models, accessories, samples = words(take('SH_SCENE'), 4)
    require(steps == frame == 30 and models == len(projection['models']) and accessories == len(projection['accessories']) and samples == len(contract['offsets']), 'actual stepped scene/domain/sample coverage')
    mappings = []
    for kind, count, tag in [('M',models,'SH_MODEL'), ('A',accessories,'SH_ACCESSORY')]:
        for ordinal in range(count):
            row = take(tag).split(' ', 4 if kind == 'M' else 5)
            nums = words(' '.join(row[:-1]), 4 if kind == 'M' else 5)
            require(nums[0] == ordinal, 'stable helper ordinal')
            source = projection['models' if kind == 'M' else 'accessories'][ordinal]
            require(nums[1] == source['slot'], 'PMM stable slot')
            if kind == 'M':
                expected = [ordinal,source['slot'],source['loadComplete']['value'],source['fields']['toonFlag']['value']]
                require(nums == expected and row[-1] == ('chain8.'+source['format']), 'actual model PMM/projection mismatch')
            else:
                f = source['fields']
                require(nums == [ordinal,source['slot'],f['visible']['value'],f['shadowEnabled']['value'],f['additiveBlend']['value']] and row[-1] == '.\\shadow_floor.x', 'actual accessory PMM/projection mismatch')
            mappings.append({'kind':kind,'ordinal':ordinal,'slot':nums[1],'path':row[-1]})
    upload = []
    for ordinal, source in enumerate(projection['models']):
        row = words(take('SH_UPLOAD'), 4)
        f = source['fields']
        require(row[:2] == [ordinal,source['material']] and finite(row[2]) == f['diffuse_alpha_bits']['value'], 'actual posed alpha/projection mismatch')
        finite(row[3])
        if source['physicsMode']['value'] == 2:
            require(row[3] == f['edge_alpha_bits']['value'], 'actual posed edge alpha/projection mismatch')
        upload.append(row)
    calls = []
    for sample in contract['offsets']:
        row = words(take('SH_ENCODE'), 5)
        shifts = [h.fbits(struct.unpack('<f',struct.pack('<I',p))[0]-struct.unpack('<f',struct.pack('<I',s))[0]) for p,s in zip(contract['pixel'],sample)]
        require(row == shifts+[1,models,accessories], 'dynamic encode identity/order/count')
        candidates = []
        for kind, group in [('M',projection['models']), ('A',projection['accessories'])]:
            for ordinal, source in enumerate(group):
                value = take('SH_CANDIDATE')
                require(value.startswith(kind+' '), 'candidate domain order')
                nums = words(value[2:], 6 if kind == 'M' else 7)
                require(nums[:2] == [ordinal,source['material']], 'candidate identity/coverage')
                f = source['fields']
                if kind == 'M':
                    require(nums[2:4] == [0,f['faceVertexCount']['value']] and nums[4] == (f['flags']['value'] if source['format'] == 'pmx' else 30) and finite(nums[5]) == upload[ordinal][2], 'model candidate input/projection')
                else:
                    require(finite(nums[2]) == f['diffuse_alpha_text']['projected_f32_bits'] and finite(nums[3]) == nums[2] and nums[4:] == [f[n]['value'] for n in ('visible','shadowEnabled','additiveBlend')], 'accessory candidate input/projection')
                candidates.append({'kind':kind,'slot':source['slot'],'material':source['material'],'values':nums})
        draws = []
        while at < len(lines) and lines[at].startswith('SH_DRAW '):
            value = take('SH_DRAW')
            require(value.startswith('M '), 'draw kind')
            ordinal, material, start, count = words(value[2:], 4)
            require(ordinal < models and count > 0 and count % 3 == 0 and start+count <= 0xffffffff, 'draw identity/range')
            identity = ['M',projection['models'][ordinal]['slot'],material,start,count,1]
            require(identity not in draws and any(c['kind'] == 'M' and c['slot'] == identity[1] and c['material'] == material and c['values'][2:4] == [start,count] for c in candidates), 'draw bound to candidate')
            draws.append(identity)
        require(words(take('SH_END'),1) == [len(draws)], 'actual draw endpoint count/completeness')
        calls.append({'shift':shifts,'candidates':candidates,'draws':draws})
    require(at == len(lines) and len(calls) == len(contract['offsets']), 'capture trailing/duplicate/encode coverage')
    return {'steps':steps,'frame':frame,'mappings':mappings,'upload':upload,'encodes':calls}


def native_stdout(raw, status, projection):
    require(type(status) is int and status == 0, 'native successful normal exit required')
    lines = raw.splitlines()
    require(lines and lines[0] == 'BEGIN MDS_SHADOW_ELIGIBILITY_V1' and re.fullmatch(r'END (0|[1-9][0-9]*)',lines[-1]), 'native stdout framing')
    candidates, calls = [], []
    expected = {(kind,m['slot'],m['material']) for kind,key in [('M','models'),('A','accessories')] for m in projection[key]}
    ranges, starts = {}, {}
    for m in projection['models']:
        slot = m['slot']
        count = m['fields']['faceVertexCount']['value']
        ranges[('M',slot,m['material'])] = [starts.get(slot,0),count,1 if m['doubleSided'] else 3]
        starts[slot] = starts.get(slot,0)+count
    seen_call = False
    for line in lines[1:-1]:
        if line.startswith('CANDIDATE '):
            require(not seen_call, 'native candidate order')
            parts = line.split()
            require(len(parts) == 4 and parts[1] in ('M','A'), 'native candidate format')
            slot, material = words(' '.join(parts[2:]),2)
            key = (parts[1],slot,material)
            require(key in expected and key not in candidates, 'native candidate coverage/duplicate')
            candidates.append(key)
        else:
            seen_call = True
            parts = line.split()
            require(len(parts) == 8 and parts[0] == 'CALL' and parts[2] in ('M','A'), 'native call format')
            ordinal = words(parts[1],1)[0]
            slot, material, start, count, cull = words(' '.join(parts[3:]),5)
            key = (parts[2],slot,material)
            require(ordinal == len(calls) and key in expected and all(tuple(v[:3]) != key for v in calls), 'native call identity/ordinal/duplicate')
            if key[0] == 'A':
                require([start,count,cull] == [0,0,0], 'accessory endpoint range/cull must be NOT_APPLICABLE')
                calls.append([*key,None,None,None])
            else:
                require(count > 0 and count % 3 == 0 and start+count <= 0xffffffff and cull in (1,3) and [start,count,cull] == ranges[key], 'native model range/cull')
                calls.append([*key,start,count,cull])
    require(set(candidates) == expected and int(lines[-1].split()[1]) == len(calls), 'native terminal/candidate coverage')
    return {'candidates':[list(v) for v in candidates], 'calls':calls,
            'rejected':[list(v) for v in candidates if not any(tuple(c[:3]) == v for c in calls)],
            'accessory_range_cull':'NOT_APPLICABLE'}


def compare(capture, witness, conditions):
    require(conditions == {
        'rust_scene_origin':'actual_canonical_helper_30_steps',
        'native_field_projection':'fixed_fixture_bytes_and_original_assignments',
        'native_pmm_load':'not_executed','native_gpu_draw':'not_executed',
        'geometry_equivalence':'not_established',
        'receiver_primitive_uv_depth_filter_msaa':'not_observed'}, 'required conditional origin labels')
    expected = {tuple(v) for v in witness['candidates']}
    differences = []
    for index, encode in enumerate(capture['encodes']):
        require({(v['kind'],v['slot'],v['material']) for v in encode['candidates']} == expected, 'candidate input domain mismatch')
        native_keys = [v[:3] for v in witness['calls']]
        rust_keys = [v[:3] for v in encode['draws']]
        if set(map(tuple,native_keys)) != set(map(tuple,rust_keys)):
            differences.append({'encode':index,'boundary':'eligibility','native':native_keys,'rust':rust_keys})
        elif native_keys != rust_keys:
            differences.append({'encode':index,'boundary':'order','native':native_keys,'rust':rust_keys})
        elif witness['calls'] != encode['draws']:
            differences.append({'encode':index,'boundary':'range_or_cull','native':witness['calls'],'rust':encode['draws']})
    return {'state':'ConditionalEligibilityDifference' if differences else 'ConditionalAgreement',
            'first_within_comparison_contract':differences[0] if differences else None,
            'conditions':conditions, 'native_endpoint':'source_call_eligibility_under_unexecuted_device_effect_mesh_MME_prerequisites',
            'native_gpu_submission':'UNPROVEN', 'rust_cull_origin':'fixed_source_shadow_pipeline_default_primitive_state_none', 'renderer_adoption':'NOT_ESTABLISHED', 'golden_parity':'NOT_ESTABLISHED'}


def record(out, label, argv, cwd, env):
    allowed = ('PATH','HOME','CARGO_HOME','RUSTUP_HOME','TMPDIR','LD_LIBRARY_PATH','WGPU_BACKEND','VK_ICD_FILENAMES','XDG_RUNTIME_DIR','CARGO_TERM_COLOR','CARGO_INCREMENTAL','CARGO_TARGET_DIR','CXX','MDS_RENDER_PNG_DIR','INCLUDE','LIB','LIBPATH','VCToolsInstallDir','WindowsSdkDir','WindowsSDKVersion')
    row = {'argv':list(map(str,argv)), 'cwd':str(cwd), 'env':{k:env[k] for k in allowed if k in env}, 'start_ns':time.time_ns()}
    for suffix in ('stdout','stderr'):
        require(not (out/(label+'.'+suffix)).exists(), 'fresh command receipt')
    with (out/(label+'.stdout')).open('xb') as stdout, (out/(label+'.stderr')).open('xb') as stderr:
        process = subprocess.run(row['argv'], cwd=cwd, env=env, stdout=stdout, stderr=stderr)
    row |= {'end_ns':time.time_ns(), 'status':process.returncode}
    for suffix in ('stdout','stderr'):
        path = out/(label+'.'+suffix)
        row[suffix] = {'name':path.name,'sha256':h.digest(path.read_bytes()),'size':path.stat().st_size}
    (out/(label+'.json')).write_text(json.dumps(row,indent=2)+'\n')
    return row


def receipt(directory, label, expected_status):
    row = h.load_json((directory/(label+'.json')).read_bytes())
    require(type(row['status']) is int and row['status'] == expected_status and
            type(row['start_ns']) is int and type(row['end_ns']) is int and 0 < row['start_ns'] <= row['end_ns'] and
            type(row['argv']) is list and row['argv'] and all(type(v) is str for v in row['argv']) and
            type(row['cwd']) is str and type(row['env']) is dict, 'command terminal/identity receipt')
    outputs = []
    for suffix in ('stdout','stderr'):
        item = row[suffix]
        require(item['name'] == label+'.'+suffix and type(item['size']) is int and item['size'] >= 0 and isinstance(item['sha256'],str) and re.fullmatch('[0-9a-f]{64}',item['sha256']), 'receipt output identity')
        raw = (directory/item['name']).read_bytes()
        require(len(raw) == item['size'] and h.digest(raw) == item['sha256'], 'command output receipt digest')
        outputs.append(raw)
    return row, outputs[0], outputs[1]


def images(out, contract, logs):
    expected = {name+suffix for name in contract['gates'].values() for suffix in ('.png','-diff.png')}
    dirs = [out/name/'images' for name in ('control','observed')]
    require(all({p.name for p in d.iterdir()} == expected for d in dirs), 'canonical all-image coverage')
    result = {}
    for test,name in sorted(contract['gates'].items()):
        a,b = [h.read_png(d/(name+'.png'), tuple(contract['dimensions'])) for d in dirs]
        da,db = [h.read_png(d/(name+'-diff.png'), tuple(contract['dimensions'])) for d in dirs]
        gold = h.read_png(out/'sources/base/tests/fixtures/rust/golden2'/(name+'.png'), tuple(contract['dimensions']))
        require(a == b and da == db, 'control/observer pixel/diff/mask drift')
        mask = [v == (255,0,255,255) for v in da]
        error = [max(abs(p[k]-g[k]) for k in range(3)) for p,g in zip(a,gold)]
        selected = [v for v,m in zip(error,mask) if not m]
        require(selected, 'empty mask')
        for v,m,pixel in zip(error,mask,da):
            require(m or pixel == (255-min(255,4*v),)*3+(255,), 'diff encoding')
        close = sum(v <= 4 for v in selected)/len(selected)
        score = {'pixels':len(selected),'masked':sum(mask),'close_count':sum(v <= 4 for v in selected),'max':max(selected),'sum':sum(selected)}
        require((close >= .9999 and max(selected) <= 48) == (test not in h.FAILURES), 'canonical metric/status drift')
        for log in logs:
            rows = re.findall(re.escape(name)+r': (\d+) px \((\d+) masked\), within 4 ([0-9.]+), max (\d+), mean ([0-9.]+)',log)
            require(rows == [(str(len(selected)),str(sum(mask)),f'{close:.5f}',str(max(selected)),f'{sum(selected)/len(selected):.4f}')], 'canonical printed metric drift')
        result[name] = score | {'rgba_sha256':h.digest(bytes(v for pixel in a for v in pixel)),
                                  'mask_sha256':h.digest(bytes(mask))}
    return result


def safe_tar(archive, dest=None):
    with tarfile.open(archive) as tar:
        members = tar.getmembers()
        require(len({m.name.rstrip('/') for m in members}) == len(members), 'duplicate TAR member')
        inventory = {}
        file_names = {m.name for m in members if m.isfile()}
        require(all(not any(str(parent) in file_names for parent in PurePosixPath(m.name).parents if str(parent) != '.') for m in members), 'TAR file/directory collision')
        for m in members:
            h.safe_name(m.name.rstrip('/'))
            require(m.isdir() or m.isfile(), 'TAR link/special entry')
            require(m.mode in ((0o644,0o755) if m.isfile() else (0o755,0o700)), 'TAR unsafe/missing executable mode')
            require(not m.isfile() or not m.name.endswith('/'), 'TAR file trailing slash')
            if m.isfile():
                raw = tar.extractfile(m).read()
                require(len(raw) == m.size, 'TAR truncated member')
                inventory[m.name] = {'sha256':h.digest(raw),'mode':m.mode}
        if dest is not None:
            require(not dest.exists(), 'fresh TAR destination')
            dest.mkdir(parents=True)
            tar.extractall(dest, filter='data')
            if sys.platform != 'win32':
                require(source_inventory(dest) == inventory, 'TAR extracted byte/mode drift')
        return inventory


def capture_inputs(r, out, build_root):
    require(sys.platform == 'linux' and os.environ.get('GITHUB_ACTIONS') == 'true', 'hosted Linux capture only')
    require(build_root is not None and not out.exists() and not build_root.exists() and
            not out.is_relative_to(ROOT) and not build_root.is_relative_to(ROOT) and
            not out.is_relative_to(build_root) and not build_root.is_relative_to(out), 'fresh separate external roots')
    require(not subprocess.check_output(['git','status','--porcelain','--untracked-files=no'],cwd=ROOT), 'tracked checkout must be clean')
    head = subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    paths = subprocess.check_output(['git','diff','--name-only',ORIGINAL,head],cwd=ROOT,text=True).splitlines()
    require(paths and all(p.startswith(PREFIX) or p == '.github/workflows/renderer-shadow-eligibility.yml' for p in paths), 'tooling-only source delta')
    out.mkdir(parents=True)
    build_root.mkdir(parents=True)
    archive = out/'base-source.tar'
    with archive.open('xb') as stream:
        subprocess.run(['git','-c','tar.umask=0022','archive',ORIGINAL],cwd=ROOT,stdout=stream,check=True)
    base = out/'sources/base'
    safe_tar(archive,base)
    (out/'base.commit').write_bytes(subprocess.check_output(['git','cat-file','commit',ORIGINAL],cwd=ROOT))
    (out/'head.commit').write_bytes(subprocess.check_output(['git','cat-file','commit',head],cwd=ROOT))
    h.commit_proof(out/'base.commit',ORIGINAL,{name:['100755' if row['mode'] & 0o111 else '100644',h.git_hash('blob',(base/name).read_bytes())] for name,row in source_inventory(base).items()})
    r.fixed(base)
    pre, native, blobs = r.preflight(ROOT)
    (out/'preflight.json').write_text(json.dumps(pre,indent=2)+'\n')
    (out/'native.cpp').write_text(native)
    (out/'canonical-input.txt').write_text(r.native_wire(pre))
    tooling = out/'tooling'
    for path in paths:
        dest = tooling/path
        dest.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(ROOT/path,dest)
    contract = h.contract(base)
    icds = list(Path('/usr/share/vulkan/icd.d').glob('lvp_icd*.json'))
    require(len(icds) == 1, 'one actual llvmpipe ICD required')
    runtime = out/'runtime'
    runtime.mkdir(mode=0o700)
    env = {k:os.environ[k] for k in ('PATH','HOME','CARGO_HOME','RUSTUP_HOME','TMPDIR','LD_LIBRARY_PATH') if k in os.environ}
    env |= {'WGPU_BACKEND':'vulkan','VK_ICD_FILENAMES':str(icds[0]),'XDG_RUNTIME_DIR':str(runtime),'CARGO_TERM_COLOR':'never','CARGO_INCREMENTAL':'0','CXX':'clang++'}
    manifest = {'schema':'mds-shadow-capture-v1','head':head,'base':ORIGINAL,'paths':paths,'artifact_root':str(out),'contract':contract,'variants':[],
                'conditions':r.CONDITIONS | {'rust_scene_origin':'actual_canonical_helper_30_steps'},'shared_control_telemetry':'SAMPLE_ADAPTER; control is telemetry-instrumented'}
    for name,argv in [('rust-version',['rustc','+1.95.0','-vV']),('vulkan-summary',['vulkaninfo','--summary'])]:
        require(record(out,name,argv,base/'rust',env)['status'] == 0, 'host telemetry execution')
    for name in ('control','observed'):
        directory = out/name
        directory.mkdir()
        source = out/'sources'/name
        shutil.copytree(base,source)
        patches = generated(base,name == 'observed')
        for path,(text,_) in patches.items():
            (source/path).write_text(text)
        before = validate_source(base,source,name == 'observed')
        png = directory/'images'
        png.mkdir()
        variant_env = env | {'CARGO_TARGET_DIR':str(build_root/name)}
        build = record(directory,'build',h.BUILD,source/'rust',variant_env)
        require(build['status'] == 0, 'Cargo build execution failed')
        original = Path(h.cargo_binary((directory/'build.stdout').read_bytes(),source,build_root/name))
        binary = directory/'golden2'
        shutil.copy2(original,binary)
        require(h.digest(original.read_bytes()) == h.digest(binary.read_bytes()), 'retained binary copy drift')
        test_env = variant_env | {'MDS_RENDER_PNG_DIR':str(png)}
        run = record(directory,'test',[binary]+h.FLAGS,source/'rust',test_env)
        after = validate_source(base,source,name == 'observed')
        require(before == after, 'source before/end drift')
        h.golden_log((directory/'test.stdout').read_text()+'\n'+(directory/'test.stderr').read_text(),run['status'],contract)
        manifest['variants'].append({'name':name,'source':str(source),'target':str(build_root/name),'before':before,'after':after,
            'patches':{p:spans for p,(_,spans) in patches.items()},'original_binary':{'path':str(original),'sha256':h.digest(original.read_bytes()),'mode':original.stat().st_mode & 0o777},
            'binary':{'sha256':h.digest(binary.read_bytes()),'mode':binary.stat().st_mode & 0o777}})
        (out/'capture.json').write_text(json.dumps(manifest,indent=2)+'\n')
    result = verify_capture(r,out)
    (out/'capture-result.json').write_text(json.dumps(result,indent=2)+'\n')
    return result


def verify_capture(r, out):
    manifest = h.load_json((out/'capture.json').read_bytes())
    require(manifest['schema'] == 'mds-shadow-capture-v1' and manifest['base'] == ORIGINAL and
            re.fullmatch('[0-9a-f]{40}',manifest['head']) and manifest['shared_control_telemetry'] == 'SAMPLE_ADAPTER; control is telemetry-instrumented', 'capture source identity')
    base = out/'sources/base'
    archive_inventory = safe_tar(out/'base-source.tar')
    require(source_inventory(base) == archive_inventory, 'retained base TAR/source bytes/modes')
    h.commit_proof(out/'base.commit',ORIGINAL,{name:['100755' if row['mode'] & 0o111 else '100644',h.git_hash('blob',(base/name).read_bytes())] for name,row in source_inventory(base).items()})
    r.fixed(base)
    packet, native, _ = r.preflight(ROOT)
    require(h.load_json((out/'preflight.json').read_bytes()) == packet and (out/'native.cpp').read_bytes() == native.encode() and
            (out/'canonical-input.txt').read_text() == r.native_wire(packet), 'source/projection/input binding')
    require(manifest['conditions'] == r.CONDITIONS | {'rust_scene_origin':'actual_canonical_helper_30_steps'}, 'required capture conditional origins')
    require(all(p.startswith(PREFIX) or p == '.github/workflows/renderer-shadow-eligibility.yml' for p in manifest['paths']) and
            len(set(manifest['paths'])) == len(manifest['paths']), 'tooling manifest scope')
    for path in manifest['paths']:
        require((out/'tooling'/path).read_bytes() == (ROOT/path).read_bytes(), 'retained tooling source identity')
    head_entries = {name:['100755' if row['mode'] & 0o111 else '100644',h.git_hash('blob',(base/name).read_bytes())] for name,row in source_inventory(base).items()}
    for name,row in source_inventory(out/'tooling').items():
        require(name in manifest['paths'], 'extra retained tooling path')
        head_entries[name] = ['100755' if row['mode'] & 0o111 else '100644',h.git_hash('blob',(out/'tooling'/name).read_bytes())]
    h.commit_proof(out/'head.commit',manifest['head'],head_entries)
    contract = h.contract(base)
    require(h.load_json(json.dumps(contract)) == manifest['contract'], 'canonical registry binding')
    require([v['name'] for v in manifest['variants']] == ['control','observed'], 'canonical suite variant coverage')
    logs = []
    for variant in manifest['variants']:
        name = variant['name']
        directory, source = out/name, out/'sources'/name
        expected = validate_source(base,source,name == 'observed')
        require(expected == variant['before'] == variant['after'] and
                variant['patches'] == {p:spans for p,(_,spans) in generated(base,name == 'observed').items()}, 'source insertion inverse/before/end')
        build, stdout, _ = receipt(directory,'build',0)
        require(build['argv'] == h.BUILD and build['cwd'] == variant['source']+'/rust' and
                build['env']['CARGO_TARGET_DIR'] == variant['target'], 'Cargo exact invocation')
        original = portable_cargo(stdout,variant['source'],variant['target'])
        require(original == variant['original_binary']['path'], 'original Cargo binary identity')
        binary = directory/'golden2'
        require(h.digest(binary.read_bytes()) == variant['binary']['sha256'] == variant['original_binary']['sha256'] and
                TRANSPORT_MODES.get(str(binary.resolve()),binary.stat().st_mode & 0o777) == variant['binary']['mode'] == variant['original_binary']['mode'] and
                variant['binary']['mode'] & 0o111, 'actual retained binary digest/mode')
        run, stdout, stderr = receipt(directory,'test',101)
        require(run['argv'] == [manifest['artifact_root']+'/'+name+'/golden2']+h.FLAGS and run['cwd'] == variant['source']+'/rust' and
                run['env'] == build['env'] | {'MDS_RENDER_PNG_DIR':manifest['artifact_root']+'/'+name+'/images'}, 'direct binary execution invocation')
        log = (stdout+b'\n'+stderr).decode()
        h.golden_log(log,run['status'],contract)
        logs.append(log)
    require(manifest['variants'][0]['name'] == 'control', 'control identity')
    capture = parse_capture(logs[1],contract,packet['fixture_projection'])
    require(not any(v.startswith('SH_') for v in logs[0].splitlines()), 'control unexpectedly has shadow observer')
    metrics = images(out,contract,logs)
    for name,argv in [('rust-version',['rustc','+1.95.0','-vV']),('vulkan-summary',['vulkaninfo','--summary'])]:
        row,stdout,stderr = receipt(out,name,0)
        require(row['argv'] == argv and row['cwd'] == manifest['artifact_root']+'/sources/base/rust' and stdout+stderr, 'host tool actual execution receipt')
    return {'state':'CAPTURE_VALID_NATIVE_EXECUTION_UNPROVEN','capture':capture,'metrics':metrics,'conditions':manifest['conditions'],
            'suites':{'each':14,'passed':11,'failed':sorted(h.FAILURES)},'adapter':h.EXPECTED_ADAPTER,
            'encode_calls':len(capture['encodes']),'native_execution':'UNRUN'}


def directed(r, packet):
    cases = []
    def add(name, change, removed):
        p = copy.deepcopy(packet)
        change(p['fixture_projection'])
        cases.append({'name':name,'wire':r.native_wire(p),'projection':p['fixture_projection'],'removed':removed})
    for field in ('visible','shadowEnabled','additiveBlend'):
        value = 1 if field == 'additiveBlend' else 0
        add('accessory-'+field,lambda p,f=field,v=value:p['accessories'][0]['fields'][f].update(value=v), [['A',0,0]])
    threshold = h.fbits(.98)
    for bits in (threshold-1,threshold,threshold+1):
        add('accessory-alpha-'+str(bits),lambda p,b=bits:p['accessories'][0]['fields']['diffuse_alpha_text'].update(projected_f32_bits=b), [['A',0,0]] if bits == threshold else [])
    for bits in (threshold-1,threshold,threshold+1):
        add('model-alpha-'+str(bits),lambda p,b=bits:p['models'][0]['fields']['diffuse_alpha_bits'].update(value=b), [['M',0,0]] if bits == threshold else [])
    add('model-alpha-zero',lambda p:p['models'][0]['fields']['diffuse_alpha_bits'].update(value=0), [])
    add('model-edge-zero',lambda p:p['models'][0]['fields']['edge_alpha_bits'].update(value=0), [['M',0,0]])
    add('model-cast-clear',lambda p:p['models'][0]['fields']['flags'].update(value=0), [['M',0,0]])
    add('model-zero-count',lambda p:p['models'][0]['fields']['faceVertexCount'].update(value=0), [['M',0,0]])
    add('model-load-zero',lambda p:p['models'][0]['loadComplete'].update(value=0), [['M',0,0]])
    add('model-toon-zero',lambda p:p['models'][0]['fields']['toonFlag'].update(value=0), [['M',0,0]])
    p = copy.deepcopy(packet['fixture_projection'])
    original = p['models'][0]
    extras = [copy.deepcopy(original) for _ in range(3)]
    for i,m in enumerate(extras):
        m['material'] = i
        m['fields']['faceVertexCount']['value'] = [0,3,6][i]
        m['fields']['diffuse_alpha_bits']['value'] = threshold if i == 1 else h.fbits(1.)
    p['models'] = extras+p['models'][1:]
    wire = r.native_wire(packet).replace('M 0 1 1 2 1\n42 1065353216 1065353216 30 1\n',
        'M 0 1 1 2 3\n0 1065353216 1065353216 30 1\n3 '+str(threshold)+' 1065353216 30 1\n6 1065353216 1065353216 30 1\n')
    cases.append({'name':'zero-count-and-index-advance','wire':wire,'projection':p,'removed':[],
                  'expected_calls':[['A',0,0,None,None,None],['M',0,2,3,6,1],['M',1,0,0,42,1]]})
    p = copy.deepcopy(packet)
    p['fixture_projection']['models'][0]['doubleSided'] = 0
    cases.append({'name':'model-cull-ccw','wire':r.native_wire(p),'projection':p['fixture_projection'],'removed':[],
                  'expected_calls':[['A',0,0,None,None,None],['M',0,0,0,42,3],['M',1,0,0,42,1]]})
    return cases


def evaluate_native_predicates(r, out):
    require(sys.platform == 'win32' and os.environ.get('GITHUB_ACTIONS') == 'true', 'hosted Windows x64 native execution only')
    result = verify_capture(r,out)
    packet, generated_source, _ = r.preflight(ROOT)
    directory = out/'native'
    require(not directory.exists(), 'native execution must be fresh')
    directory.mkdir()
    shutil.copy2(out/'native.cpp',directory/'native.cpp')
    compiler = shutil.which('cl.exe')
    require(compiler is not None and os.environ.get('VSCMD_ARG_TGT_ARCH') == 'x64', 'actual MSVC x64 environment required')
    env = dict(os.environ)
    normal = directory/'eligibility.exe'
    def compile_native(label, source, binary):
        before_source = h.digest(source.read_bytes())
        argv = [compiler,'/nologo','/Bv','/std:c++17','/EHsc','/utf-8','/showIncludes','/W4','/I'+str(out/'sources/base/include'),str(source),'/Fe:'+str(binary),'/Fo:'+str(directory/(label+'.obj')),'/link','/VERBOSE:LIB','/MAP:'+str(directory/(label+'.map'))]
        row = record(directory,label,argv,directory,env)
        require(row['status'] == 0 and binary.is_file(), 'native compilation failed')
        require(h.digest(source.read_bytes()) == before_source, 'native source before/end compile drift')
        retained = directory/(label+'-retained.exe')
        shutil.copy2(binary,retained)
        linked = {}
        for suffix in ('.obj','.map'):
            path = directory/(label+suffix)
            require(path.is_file(), 'native compiler/link output missing')
            linked[suffix] = {'name':path.name,'sha256':h.digest(path.read_bytes()),'size':path.stat().st_size}
        return {'compile':label,'argv':argv,'binary':retained.name,'original_binary':binary.name,'link_inputs_outputs':linked,
                'sha256':h.digest(retained.read_bytes()),'source':source.name,'source_sha256':h.digest(source.read_bytes()),
                'compiler':{'path':compiler,'sha256':h.digest(Path(compiler).read_bytes())}}
    builds = [compile_native('compile',directory/'native.cpp',normal)]
    source = generated_source.replace('                emit_accessory(slot, i);\n','                (void)slot; (void)i;\n')
    require(source != generated_source, 'semantic mutant anchor')
    (directory/'mutant.cpp').write_text(source, newline='\n')
    builds.append(compile_native('compile-mutant',directory/'mutant.cpp',directory/'mutant.exe'))
    def execute(label, binary, wire, projection):
        path = directory/(label+'.input')
        path.write_text(wire)
        row = record(directory,label,[binary,path],directory,env)
        witness = native_stdout((directory/(label+'.stdout')).read_text(),row['status'],projection)
        require(not (directory/(label+'.stderr')).read_bytes(), 'native unexpected stderr')
        return witness
    canonical = execute('canonical',normal,r.native_wire(packet),packet['fixture_projection'])
    cases = directed(r,packet)
    observations = []
    for case in cases:
        witness = execute(case['name'],normal,case['wire'],case['projection'])
        require(witness['calls'] == case.get('expected_calls',[v for v in canonical['calls'] if v[:3] not in case['removed']]), 'directed boundary semantic mismatch: '+case['name'])
        observations.append({'name':case['name'],'witness':witness})
    mutant = execute('semantic-mutant',directory/'mutant.exe',r.native_wire(packet),packet['fixture_projection'])
    require(mutant['calls'] != canonical['calls'], 'compiled normal-exit semantic mutant survived')
    manifest = {'schema':'mds-shadow-native-v1','capture_sha256':h.digest((out/'capture.json').read_bytes()),'input_sha256':h.digest((out/'canonical-input.txt').read_bytes()),
                'native_root':str(directory),'builds':builds,'canonical':canonical,'directed':observations,'mutant':mutant,'mutant_caught':'valid_trace_result_difference',
                'comparison':compare(result['capture'],canonical,result['conditions'])}
    (directory/'witness.json').write_text(json.dumps(manifest,indent=2)+'\n')
    return verify_native(r,out,result)


def verify_native(r, out, capture_result=None):
    result = capture_result or verify_capture(r,out)
    directory = out/'native'
    manifest = h.load_json((directory/'witness.json').read_bytes())
    packet, source, _ = r.preflight(ROOT)
    require(manifest['schema'] == 'mds-shadow-native-v1' and
            manifest['capture_sha256'] == h.digest((out/'capture.json').read_bytes()) and
            manifest['input_sha256'] == h.digest((out/'canonical-input.txt').read_bytes()), 'native source/input/capture binding')
    require([v['compile'] for v in manifest['builds']] == ['compile','compile-mutant'], 'native build coverage')
    native_root = PureWindowsPath(manifest['native_root'])
    require(native_root.is_absolute() and native_root.name == 'native', 'native receipt cwd origin')
    for build, expected in zip(manifest['builds'],[source,source.replace('                emit_accessory(slot, i);\n','                (void)slot; (void)i;\n')]):
        require((directory/build['source']).read_bytes() == expected.encode() and h.digest(expected.encode()) == build['source_sha256'], 'native source before/end or semantic mutation drift')
        require(all(h.digest((directory/build[key]).read_bytes()) == build['sha256'] for key in ('binary','original_binary')), 'native original/retained binary hash drift')
        require(set(build['link_inputs_outputs']) == {'.obj','.map'}, 'native link receipt coverage')
        for suffix,item in build['link_inputs_outputs'].items():
            path = directory/(build['compile']+suffix)
            require(item['name'] == path.name and path.is_file() and path.stat().st_size == item['size'] and h.digest(path.read_bytes()) == item['sha256'], 'native link input/output digest')
        row, stdout, stderr = receipt(directory,build['compile'],0)
        expected_argv = [build['compiler']['path'],'/nologo','/Bv','/std:c++17','/EHsc','/utf-8','/showIncludes','/W4',
            '/I'+str(native_root.parent/'sources/base/include'),str(native_root/build['source']),
            '/Fe:'+str(native_root/build['original_binary']),'/Fo:'+str(native_root/(build['compile']+'.obj')),
            '/link','/VERBOSE:LIB','/MAP:'+str(native_root/(build['compile']+'.map'))]
        require(row['argv'] == build['argv'] == expected_argv and row['cwd'] == str(native_root) and row['argv'][0] == build['compiler']['path'] and
                re.fullmatch('[0-9a-f]{64}',build['compiler']['sha256']) and
                '/showIncludes' in row['argv'] and '/link' in row['argv'] and '/VERBOSE:LIB' in row['argv'] and
                any(v.startswith('/I') and v.endswith('sources\\base\\include') for v in row['argv']) and
                b'model.hpp' in stdout+stderr and b'd3d9.h' in (stdout+stderr).lower() and
                all(v in row['env'] for v in ('INCLUDE','LIB')), 'native actual compiler/include/link receipt')
    def replay(label, projection, wire, binary):
        row, stdout, stderr = receipt(directory,label,0)
        require((directory/(label+'.input')).read_text() == wire and not stderr and
                row['cwd'] == str(native_root) and row['argv'] == [str(native_root/binary),str(native_root/(label+'.input'))], 'native input/argv/stderr receipt')
        return native_stdout(stdout.decode(),row['status'],projection)
    canonical = replay('canonical',packet['fixture_projection'],r.native_wire(packet),'eligibility.exe')
    require(canonical == manifest['canonical'], 'native canonical stdout parser drift')
    cases = directed(r,packet)
    require([v['name'] for v in manifest['directed']] == [v['name'] for v in cases], 'directed coverage')
    for case, retained in zip(cases,manifest['directed']):
        witness = replay(case['name'],case['projection'],case['wire'],'eligibility.exe')
        require(witness == retained['witness'] and witness['calls'] == case.get('expected_calls',[v for v in canonical['calls'] if v[:3] not in case['removed']]), 'directed semantic result')
    mutant = replay('semantic-mutant',packet['fixture_projection'],r.native_wire(packet),'mutant.exe')
    require(mutant == manifest['mutant'] and mutant['calls'] != canonical['calls'] and manifest['mutant_caught'] == 'valid_trace_result_difference', 'semantic normal-exit mutant not caught')
    comparison = compare(result['capture'],canonical,result['conditions'])
    require(comparison == manifest['comparison'], 'conditional comparison result drift')
    return comparison | {'suites':result['suites'],'encode_calls':result['encode_calls'],'directed_cases':len(cases),'semantic_mutant':'CAUGHT_BY_RESULT_DIFFERENCE'}


def bundle(out, archive):
    require(not archive.exists() and not archive.is_relative_to(out), 'fresh external TAR path')
    def mode(info):
        path = out/info.name
        info.mode = TRANSPORT_MODES.get(str(path.resolve()), 0o755 if path.suffix == '.exe' or path.stat().st_mode & 0o111 else 0o644)
        return info
    with tarfile.open(archive,'w') as tar:
        for path in sorted(out.rglob('*')):
            require(not path.is_symlink(), 'bundle symlink')
            if path.is_file():
                tar.add(path,arcname=path.relative_to(out).as_posix(),recursive=False,filter=mode)
    return {'sha256':h.digest(archive.read_bytes()),'members':len(safe_tar(archive))}


def transport(archive, out, extract=False):
    inventory = safe_tar(archive, out if extract else None)
    for name,row in inventory.items():
        path = out/name
        require(path.is_file() and not path.is_symlink() and h.digest(path.read_bytes()) == row['sha256'], 'transport byte drift')
        if sys.platform != 'win32':
            require(path.stat().st_mode & 0o777 == row['mode'], 'transport extracted mode drift')
        TRANSPORT_MODES[str(path.resolve())] = row['mode']
    return inventory


def portable_cargo(raw, source, target):
    lines = [line for line in raw.splitlines(keepends=True) if line.lstrip().startswith(b'{')]
    require(lines and all(line.endswith(b'\n') for line in lines), 'Cargo truncated object')
    rows = [h.load_json(line) for line in lines]
    require(all(type(v) is dict and isinstance(v.get('reason'),str) and v['reason'] for v in rows), 'Cargo object shape')
    finishes = [v for v in rows if v['reason'] == 'build-finished']
    require(len(finishes) == 1 and rows[-1] is finishes[0] and finishes[0] == {'reason':'build-finished','success':True} and finishes[0]['success'] is True, 'Cargo terminal success')
    selected = [v for v in rows if v['reason'] == 'compiler-artifact' and v.get('target',{}).get('name') == 'golden2']
    require(len(selected) == 1, 'Cargo golden2 artifact identity/count')
    row = selected[0]
    t = row['target']
    crate = PurePosixPath(source)/'rust/crates/mds-render'
    require(row.get('manifest_path') == str(crate/'Cargo.toml') and t.get('src_path') == str(crate/'tests/golden2.rs') and
            t.get('kind') == ['test'] and t.get('crate_types') == ['bin'] and t.get('test') is True, 'Cargo target/manifest/source')
    profile = {'opt_level':'0','debuginfo':2,'debug_assertions':True,'overflow_checks':True,'test':True}
    require(row.get('profile') == profile and type(row['profile']['debuginfo']) is int and
            all(row['profile'][key] is True for key in ('debug_assertions','overflow_checks','test')), 'Cargo test profile')
    exe = row.get('executable')
    require(isinstance(exe,str) and PurePosixPath(exe).parent == PurePosixPath(target)/'debug/deps' and
            re.fullmatch('golden2-[0-9a-f]+',PurePosixPath(exe).name) and row.get('filenames') == [exe], 'Cargo executable path')
    return exe
