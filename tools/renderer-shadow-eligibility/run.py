#!/usr/bin/env python3
import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import struct
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
BASE = '2210a28022844b373e1146a91bf0def2f4be8f0b'
MODEL = 'src/render/model_renderers.cpp'
ACCESSORY = 'src/render/accessory.cpp'
PMM = 'tests/fixtures/rust/golden2/selfshadow.pmm'
PMX = 'tests/fixtures/rust/chain8.pmx'
PMD = 'tests/fixtures/rust/chain8.pmd'
FLOOR = 'tests/fixtures/rust/golden2/shadow_floor.x'
SOURCES = {
    MODEL: 'c3279aee855b3abb1792b9a9264aa7006ab3b747d045cec58a5ef889d7c8f321',
    ACCESSORY: 'd5e98eb260eab2f6a86c235bc40d54e0ea862393e6b58616223398b89ad79be6',
    'src/model/pmx_load.cpp': 'c388cc0694c29495bb1d40951f41aa5f1746c6b2b058209daf28dad072a3497c',
    'src/model/pmd_load.cpp': '48099f35af76c666bea158e44b8534666f621d91e43582cd68388567949dbad4',
    'src/model/model_init.cpp': '268247dc8a90367fef7cfed28d76aa3720d197ba65b47404b43a7ea01b35dd2b',
    'src/io/pmm_load_v2.cpp': 'b6f65fb954caf9224c6f34676158bb832a3e723cef465f4569e6fe627ea7a33d',
    'tests/fixtures/rust/golden2/gen_golden2.py': '29f23d6b5b56e292c206afcc4092931e972d7f44abacbbd6cf9f5f50d2e72656',
    'tools/fixtures/gen_fixtures.py': 'ccd982adb5ada42ba2668d583169bb5597700b23193f0a034f92bf82458ad56e',
    'rust/crates/mds-render/src/renderer.rs': '5c31f91eff8ebd2e96f1d32107a0975793fe75246cc40be3a9997f69f095f3f5',
    'rust/crates/mds-render/tests/golden2.rs': 'b6b462bcd156f498a9a50829670e25d5447fb68ec9f56c990f9a49dc0d9e2612',
    'include/mikudancestudio/model.hpp': 'de39a41321d2fa4f3301479e0074b7c998dbb4f0f566ff389767d41c1accd40b',
    'include/mikudancestudio/bone_layout.hpp': '5c509ca7326d531cdc36b740a55daad53e5d2fea684d15f89536643be820d0dd',
    'include/mikudancestudio/model_layout.hpp': 'e3bbb905f170363cc174696a733e52bcaf5c2421699f1dbc51ae81e3f7506da5',
    'include/mikudancestudio/subrecord_layout.hpp': '5a91fb1fb62753faf331f1810f7069941a7abfedc995f70c7051bb70f6b9c485',
    'include/mikudancestudio/raw_pad.hpp': '4b96f1f7c5916f78836d6094e8af20a3cd0d53fdd1823f18e4c3241b6e977128',
    'include/mikudancestudio/bone_binding.hpp': 'fafaf19804925860e2a37443ab557dc43242b26cd6f5d1b0842bdcdd8815fa87',
    'include/mikudancestudio/undo_layout.hpp': '75aec6ff67c51e2a6a6bb30a1f0f9eea86497f89edd968edfaafd74494933595',
    'include/mikudancestudio/skeleton_tracking.hpp': '8247030a89459dcecea6afe8bb145317f42ad294205ec9b4843b5c9fd427fef2',
    'include/mikudancestudio/accessory_layout.hpp': 'ba9112534c377c423e1eac25810e12124d07fa2ed0d681f6ad4f914f96e36f9f',

}
FIXTURES = {
    PMM: '98b2adab073ddf3057b3cebf8c8450f1594aac241bf733b444710d18efcdc83e',
    PMX: 'fe207ad765e022190515f0d6fe9e22c3f582f067af4ea179603abfe84a336ccc',
    PMD: '3fd0f2e5b54bb3387a0e106b697ff3e27f8aed3685e9705fb18a56f63ac4bd58',
    FLOOR: 'adfd3e6fb4b552f6c38eb9b94bc8b75061270e7d24a4933694c73df02e58122c',
}
CONDITIONS = {
    'rust_scene_origin': 'not_captured',
    'native_field_projection': 'fixed_fixture_bytes_and_original_assignments',
    'native_pmm_load': 'not_executed',
    'native_gpu_draw': 'not_executed',
    'geometry_equivalence': 'not_established',
    'receiver_primitive_uv_depth_filter_msaa': 'not_observed',
}


def require(ok, message):
    if not ok:
        raise ValueError(message)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def load_json(raw):
    def pairs(items):
        out = {}
        for key, value in items:
            require(key not in out, 'duplicate JSON key')
            out[key] = value
        return out
    def number(text):
        value = float(text)
        require(math.isfinite(value), 'nonfinite JSON number')
        return value
    def constant(text):
        raise ValueError('nonfinite JSON constant: ' + text)
    return json.loads(raw, object_pairs_hook=pairs, parse_float=number, parse_constant=constant)


def fixed(root):
    blobs = {}
    for path, sha in (SOURCES | FIXTURES).items():
        raw = (root/path).read_bytes()
        require(digest(raw) == sha, 'fixed source/fixture drift: ' + path)
        blobs[path] = raw
    validate_blobs(blobs)
    return blobs


def validate_blobs(blobs):
    require(set(blobs) == set(SOURCES | FIXTURES), 'source/fixture inventory')
    for path, sha in (SOURCES | FIXTURES).items():
        require(digest(blobs[path]) == sha, 'fixed source/fixture drift: ' + path)


def span(blobs, path, begin, end=None, scope=None):
    original = blobs[path]
    scope_start, scope_end = 0, len(original)
    if scope:
        require(original.count(scope[0].encode()) == original.count(scope[1].encode()) == 1,
                'missing/duplicate scope anchor')
        scope_start = original.index(scope[0].encode())
        scope_end = original.index(scope[1].encode())
        require(scope_start < scope_end, 'source scope order')
    raw = original[scope_start:scope_end]
    first = begin.encode()
    require(raw.count(first) == 1, 'missing/duplicate begin anchor: ' + begin)
    start = raw.index(first)
    if end is None:
        stop = start + len(first)
    else:
        last = end.encode()
        require(raw.count(last) == 1, 'missing/duplicate end anchor: ' + end)
        stop = raw.index(last)
        require(stop > start, 'reversed source span')
    return {'path': path, 'start': start+scope_start, 'end': stop+scope_start, 'begin': begin, 'until': end,
            'scope': scope,
            'sha256': digest(raw[start:stop]), 'text': raw[start:stop].decode()}


def extract(blobs):
    def model(begin, end=None):
        return span(blobs, MODEL, begin, end, scope=[
            'void DrawModelMaterials(MMDApp* app, unsigned char* model, bool effectPass, bool shadowOnly) {',
            'void DrawModelEdgeGeometry(MMDApp* app, unsigned char* model, bool projectedShadow) {'])
    def accessory(begin, end=None):
        return span(blobs, ACCESSORY, begin, end, scope=[
            'void RenderAccessoriesShadow(MMDApp* app) {',
            'void RenderAccessoriesEffect(MMDApp* app) {'])
    rows = {
        'model_load': model(
            '    if (model == nullptr || mdl::Mdl(model)->loadComplete == 0)\n',
            '    D3DRenderer* sub = app->Renderer();\n    auto* device = sub->device;\n    auto* effect = sub->effect;\n'),
        'model_materials': model(
            '    UINT firstIndex = 0;\n    state.toonShared = static_cast<std::uint32_t>(-1);\n',
            '            D3DMATERIAL9 d3dMaterial{};\n'),
        'model_cull': model(
            'record.doubleSided == 0 ? D3DCULL_CCW : D3DCULL_NONE'),
        'model_advance': model(
            '        firstIndex += indexCount;\n    }\n    state.toonShared = static_cast<std::uint32_t>(-1);\n'),
        'model_slots': span(blobs, MODEL,
            '        for (int slot = 0; slot < kModelSlotCount; ++slot) {\n',
            '            app->ActiveRenderObject() = model;\n', scope=[
                'void RenderShadowMap(MMDApp* app, const float frameMatrix[16]) {',
                '} // namespace mikudancestudio']),
        'accessory_slots': accessory(
            '    for (int slot = 0; slot < 255; ++slot) {\n        void* accessory = app->AccessorySlot(slot);\n',
            '        Matrix world;\n        Matrix light;\n'),
        'accessory_materials': accessory(
            '        auto* materials = static_cast<const D3DMATERIAL9*>(mdl::Accessory(accessory)->materials);\n',
            '        fx::EndPass(effect);\n        mdl::Accessory(accessory)->currentMaterial = -1;\n'),
        'model_endpoint': model(
            '                mme::DrawIndexedPrimitive(device, D3DPT_TRIANGLELIST, 0, 0, state.vertexCount,\n                                          firstIndex, indexCount / 3);\n'),
        'accessory_endpoint': accessory(
            '                mme::DrawAccessorySubset(app, accessory, i);\n'),
    }
    require(rows['accessory_materials']['text'].count(rows['accessory_endpoint']['text']) == 1,
            'accessory endpoint extraction')
    return rows


def assignment(blobs, path, text):
    return span(blobs, path, text)


def binding(blobs, path, offset, size, value, source):
    raw = blobs[path][offset:offset+size]
    require(len(raw) == size and int.from_bytes(raw, 'little') == value, 'raw field offset/value')
    return {'fixture': path, 'offset': offset, 'size': size, 'raw_hex': raw.hex(),
            'value': value, 'assignment': source}


def pmm_model_prefix(raw, start):
    at = start + 1
    for _ in range(2):
        size = raw[at]
        at += 1 + size
    path_at = at
    path = raw[at:at+256].split(b'\0')[0].decode('cp932')
    at += 257
    for names in (True, True, False, False):
        count = struct.unpack_from('<i', raw, at)[0]
        at += 4
        require(0 <= count <= 64, 'bounded PMM name/mapping count')
        for _ in range(count):
            if names:
                size = raw[at]
                at += 1 + size
            else:
                at += 4
            require(at < len(raw), 'PMM prefix bounds')
    return {'slot_offset': start, 'path_offset': path_at, 'path': path,
            'load_complete_offset': at + 1}


def fixture_projection(blobs):
    pmm = blobs[PMM]
    require(pmm[:30] == b'Polygon Movie maker 0002' + bytes(6) and pmm[54] == 2,
            'bounded PMM model domain')
    require(pmm[55] == 0 and pmm[1250] == 1, 'bounded PMM slots')
    prefixes = [pmm_model_prefix(pmm, start) for start in (55, 1250)]
    require([p['path'] for p in prefixes] == ['chain8.pmx', 'chain8.pmd'], 'bounded PMM paths')
    require(pmm[58:314].split(b'\0')[0] == b'chain8.pmx' or b'chain8.pmx\0' in pmm[55:400],
            'PMM model zero path')
    require(b'chain8.pmd\0' in pmm[1250:1600], 'PMM model one path')
    require(pmm[2632] == 1 and pmm[2733] == 0 and b'.\\shadow_floor.x\0' in pmm[2733:3100],
            'bounded PMM accessory domain')
    pmx, pmd = blobs[PMX], blobs[PMD]
    at = 17
    require(pmx[:4] == b'PMX ' and pmx[8:17] == bytes([8, 0, 0, 2, 1, 1, 1, 1, 1]),
            'bounded PMX header')
    for _ in range(4):
        n = struct.unpack_from('<I', pmx, at)[0]
        at += 4 + n
        require(at <= len(pmx), 'PMX text bounds')
    vertices = struct.unpack_from('<I', pmx, at)[0]
    at += 4
    require(vertices == 16, 'bounded PMX vertex domain')
    for _ in range(vertices):
        kind = pmx[at+32]
        require(kind == 1, 'bounded PMX BDEF2')
        at += 43
    indices = struct.unpack_from('<I', pmx, at)[0]
    at += 4 + indices*2
    require(struct.unpack_from('<I', pmx, at)[0] == 1, 'bounded PMX texture domain')
    at += 4
    texture_size = struct.unpack_from('<I', pmx, at)[0]
    at += 4
    require(pmx[at:at+texture_size].decode('utf-16-le') == 'chain.png', 'bounded PMX texture')
    at += texture_size
    require(struct.unpack_from('<I', pmx, at)[0] == 1, 'bounded PMX material domain')
    at += 4
    for _ in range(2):
        n = struct.unpack_from('<I', pmx, at)[0]
        at += 4 + n
    pmx_material = at
    pmx_count = at + 44 + 1 + 20 + 1 + 1 + 3 + 4
    require(pmd[:7] == b'Pmd\0\0\x80?' and struct.unpack_from('<I', pmd, 283)[0] == 16,
            'bounded PMD header/vertices')
    pmd_indices = 287 + 16*38
    count = struct.unpack_from('<I', pmd, pmd_indices)[0]
    pmd_material = pmd_indices + 4 + count*2 + 4
    require(struct.unpack_from('<I', pmd, pmd_material-4)[0] == 1, 'bounded PMD material domain')
    result = {'models': [], 'accessories': []}
    for slot, path, material, toon, mode in [(0, PMX, pmx_material, 1248, 2), (1, PMD, pmd_material, 2441, 0)]:
        loader = 'src/model/pmx_load.cpp' if mode == 2 else 'src/model/pmd_load.cpp'
        alpha = struct.unpack_from('<I', blobs[path], material+12)[0]
        count_at = pmx_count if mode == 2 else material+46
        face_count = struct.unpack_from('<I', blobs[path], count_at)[0]
        require(face_count == indices == count, 'bounded fixture index domain')
        flag_at = material+44 if mode == 2 else material+45
        flag = blobs[path][flag_at]
        require(flag == (0x1e if mode == 2 else 1), 'native-sidedness raw byte')
        fields = {
            'slot': binding(blobs, PMM, prefixes[slot]['slot_offset'], 1, slot,
                assignment(blobs, 'src/io/pmm_load_v2.cpp', '    slots[slotByte] = nm;                        // 0x4504F7')),
            'loadComplete': binding(blobs, PMM, prefixes[slot]['load_complete_offset'], 1, 1,
                assignment(blobs, 'src/io/pmm_load_v2.cpp',
                           '        modelRecord->loadComplete = (b == 1) ? 1 : 0;')),
            'toonFlag': binding(blobs, PMM, toon, 1, 1, assignment(blobs, 'src/io/pmm_load_v2.cpp',
                '        mdl::Mdl(model)->toonFlag = (b == 1) ? 1 : 0;')),
            'diffuse_alpha_bits': binding(blobs, path, material+12, 4, alpha,
                assignment(blobs, loader, '            _read(fh, mat.diffuse, sizeof(mat.diffuse));')),
            'faceVertexCount': binding(blobs, path, count_at, 4, face_count,
                assignment(blobs, loader, '            _read(fh, &mat.faceVertexCount, sizeof(mat.faceVertexCount));')),
            'doubleSided_raw': binding(blobs, path, flag_at, 1, flag,
                assignment(blobs, loader, '            mat.doubleSided = (mat.flags & 0x10) != 0;' if mode == 2 else
                           '            mat.doubleSided = sphereFlag ? 1 : 0;')),
        }
        if mode == 2:
            fields['edge_alpha_bits'] = binding(blobs, path, material+57, 4, 1065353216,
                assignment(blobs, loader, '            _read(fh, mat.edgeColor, sizeof(mat.edgeColor));'))
            fields['flags'] = binding(blobs, path, flag_at, 1, flag,
                assignment(blobs, loader, '            _read(fh, &mat.flags, 1);'))
        result['models'].append({'slot': slot, 'material': 0, 'format': 'pmx' if mode == 2 else 'pmd',
            'physicsMode': {'value': mode, 'assignment': assignment(blobs,
                loader if mode == 2 else 'src/model/model_init.cpp',
                '    model.physicsMode = 2;' if mode == 2 else '    model.physicsMode = 0;')},
            'loadComplete': fields['loadComplete'],
            'doubleSided': int(bool(flag & 0x10)) if mode == 2 else int(bool(flag)),
            'fields': fields})
    floor = blobs[FLOOR]
    match = re.search(rb'Material \{\r\n   [^\r\n]*;([0-9.]+);;', floor)
    require(match is not None and match.group(1) == b'1.000000', 'bounded X material alpha')
    a = result['accessories']
    a.append({'slot': 0, 'material': 0, 'fields': {
        'slot': binding(blobs, PMM, 2733, 1, 0, assignment(blobs, 'src/io/pmm_load_v2.cpp',
            '        Rd(fd, &accSlot, 1); // 0x455A3F')),
        'visible': binding(blobs, PMM, 3146, 1, 1, assignment(blobs, 'src/io/pmm_load_v2.cpp',
            '            accessory.visible = b & 1;')),
        'shadowEnabled': binding(blobs, PMM, 3183, 1, 1, assignment(blobs, 'src/io/pmm_load_v2.cpp',
            '            accessory.shadowEnabled = (b == 1) ? 1 : 0;')),
        'additiveBlend': binding(blobs, PMM, 3184, 1, 0, assignment(blobs, 'src/io/pmm_load_v2.cpp',
            '            accessory.additiveBlend = (b == 1) ? 1 : 0;')),
        'diffuse_alpha_text': {'fixture': FLOOR, 'offset': match.start(1), 'size': len(match.group(1)),
            'raw_hex': match.group(1).hex(), 'value': '1.000000',
            'condition': 'X_material_decoder_not_executed', 'projected_f32_bits': 1065353216,
            'assignment': assignment(blobs, ACCESSORY, '            *material = source.MatD3D;')},
    }})
    return result


def generate(blobs, template):
    rows = extract(blobs)
    generated = template
    mapping = {}
    used = ['model_load', 'model_materials', 'model_cull', 'model_advance', 'model_slots',
            'accessory_slots', 'accessory_materials']
    used.sort(key=lambda name: template.index('@' + name.upper() + '@'))
    for name in used:
        token = '@' + name.upper() + '@'
        require(generated.count(token) == 1, 'native template anchor: ' + name)
        code = rows[name]['text']
        if name == 'accessory_materials':
            code = code.replace(rows['accessory_endpoint']['text'],
                '                emit_accessory(slot, i);\n')
        start = generated.index(token)
        generated = generated[:start] + code + generated[start+len(token):]
        mapping[name] = {'generated_start': start, 'generated_bytes': len(code.encode()),
                         'sha256': digest(code.encode())}
    require(not re.search(r'@[A-Z_]+@', generated), 'unexpanded native template token')
    for name, row in mapping.items():
        start, size = row['generated_start'], row['generated_bytes']
        require(digest(generated.encode()[start:start+size]) == row['sha256'], 'generated byte span')
    original = generated
    for name in reversed(used):
        start = mapping[name]['generated_start']
        n = mapping[name]['generated_bytes']
        original = original[:start] + '@' + name.upper() + '@' + original[start+n:]
    require(original == template, 'native template inverse reconstruction')
    return generated, rows, mapping


def omitted_spans(blobs, rows):
    result = []
    scopes = {(row['path'], tuple(row['scope'])) for row in rows.values() if row['scope']}
    for path, scope in sorted(scopes):
        raw = blobs[path]
        start, end = raw.index(scope[0].encode()), raw.index(scope[1].encode())
        intervals = sorted((row['start'], row['end']) for row in rows.values()
                           if row['path'] == path and start <= row['start'] < end)
        cursor = start
        for first, last in intervals + [(end, end)]:
            if first > cursor:
                result.append({'path': path, 'start': cursor, 'end': first,
                               'sha256': digest(raw[cursor:first])})
            cursor = max(cursor, last)
    return result


def native_wire(packet):
    models = packet['fixture_projection']['models']
    accessories = packet['fixture_projection']['accessories']
    lines = ['MDS_SHADOW_ELIGIBILITY_V1', f'{len(models)} {len(accessories)}']
    for model in models:
        f = model['fields']
        lines.append(f"M {model['slot']} {model['loadComplete']['value']} {f['toonFlag']['value']} "
                     f"{model['physicsMode']['value']} 1")
        lines.append(' '.join(str(v) for v in [f['faceVertexCount']['value'],
            f['diffuse_alpha_bits']['value'], f.get('edge_alpha_bits', {'value': 0})['value'],
            f.get('flags', {'value': 0})['value'], model['doubleSided']]))
    for accessory in accessories:
        f = accessory['fields']
        lines.append(f"A {accessory['slot']} {f['visible']['value']} {f['shadowEnabled']['value']} "
                     f"{f['additiveBlend']['value']} 1")
        lines.append(str(f['diffuse_alpha_text']['projected_f32_bits']))
    return '\n'.join(lines) + '\n'


def preflight(root):
    blobs = fixed(root)
    template = (Path(__file__).parent/'native.cpp.in').read_text()
    generated, rows, mapping = generate(blobs, template)
    packet = {'schema': 'mds-shadow-eligibility-preflight-v1', 'base': BASE,
        'state': 'PARTIAL_NOT_A_COMPARISON', 'conditions': CONDITIONS,
        'sources': SOURCES, 'fixtures': FIXTURES, 'extraction': rows, 'generated_spans': mapping,
        'template_sha256': digest(template.encode()), 'native_source_sha256': digest(generated.encode()),
        'fixture_projection': fixture_projection(blobs),
        'pmm_model_tail_layout': assignment(blobs, 'tests/fixtures/rust/golden2/gen_golden2.py',
            '    o += u8(0) + f32(m.edge_scale) + u8(1, 0)'),
        'accessory_alpha_assignment': assignment(blobs, ACCESSORY, '            *material = source.MatD3D;'),
        'omitted_spans': omitted_spans(blobs, rows),
        'endpoint_replacements': {'model_endpoint': 'CALL ordinal M slot material firstIndex indexCount cull',
                                  'accessory_endpoint': 'emit_accessory(slot, i)'},
        'native_input_origin': 'fixture_projection_only_not_canonical_stepped_scene',
        'not_executed_prerequisites': ['native PMM/model/accessory loaders', 'device/resource availability',
            'effect Begin/BeginPass success', 'MME bridge execution', 'GPU draw and geometry'],
        'omitted_operations': ['model renderer resources/FVF/lighting/effect/material/device operations',
            'accessory renderer resources/world/light matrices/effect/material/device operations',
            'RenderShadowMap setup/effect Begin and End/matrices/active-object assignments'],
        'missing': ['actual Rust selfshadow_30 30-step all-candidate capture and stable PMM slot binding',
            'actual pre-draw_indexed observer for each source-derived encode call',
            'posed material alpha/edge and range agreement against fixture projection',
            'canonical 14-test control/observed outcomes and all 11 RGBA/diff/mask/metric equality',
            'hosted Windows compiler/includes/link/binary/direct-execution receipts',
            'hosted source-semantic mutation and sensitivity execution',
            'Linux to Windows TAR capture transfer and independently sealed comparison']}
    return packet, generated, blobs


def verify_preflight(root, out):
    expected, generated, blobs = preflight(root)
    require(load_json((out/'packet.json').read_text()) == expected, 'preflight packet drift')
    require((out/'native.cpp').read_bytes() == generated.encode(), 'generated native source drift')
    require((out/'fixture-input.txt').read_text() == native_wire(expected), 'fixture native wire drift')
    names = {'packet.json', 'native.cpp', 'fixture-input.txt'} | {'inputs/'+p for p in blobs}
    actual = set()
    for path in out.rglob('*'):
        require(not path.is_symlink(), 'preflight symlink')
        if path.is_file():
            actual.add(path.relative_to(out).as_posix())
    require(actual == names, 'preflight path inventory')
    for path, raw in blobs.items():
        require((out/'inputs'/path).read_bytes() == raw, 'retained source/fixture drift')
    return {'state': expected['state'], 'comparison': 'INVALID_MISSING_EXECUTION',
            'model_materials': len(expected['fixture_projection']['models']),
            'accessory_materials': len(expected['fixture_projection']['accessories'])}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--prepare', action='store_true')
    parser.add_argument('--run', choices=('capture','native'))
    parser.add_argument('--build-root', type=Path)
    parser.add_argument('--archive', type=Path)
    parser.add_argument('--bundle', type=Path)
    parser.add_argument('--unpack', action='store_true')
    args = parser.parse_args()
    out = args.out.resolve()
    require(not out.is_relative_to(ROOT), 'evidence must be outside source worktree')
    if args.run or args.archive or args.bundle or (out/'capture.json').exists():
        import capture
        require(not args.unpack or (args.archive and not args.run), '--unpack requires --archive without execution')
        if args.archive:
            capture.transport(args.archive.resolve(), out, extract=args.run == 'native' or args.unpack)
        if args.run == 'capture':
            result = capture.capture_inputs(sys.modules[__name__], out, args.build_root.resolve() if args.build_root else None)
        elif args.run == 'native':
            result = capture.evaluate_native_predicates(sys.modules[__name__], out)
        elif (out/'native/witness.json').exists():
            result = capture.verify_native(sys.modules[__name__], out)
        else:
            require(not (out/'native').exists(), 'INVALID_NATIVE_EXECUTION_INCOMPLETE')
            result = capture.verify_capture(sys.modules[__name__], out)
        if args.bundle:
            result = result | {'bundle':capture.bundle(out,args.bundle.resolve())}
        print(json.dumps(result, sort_keys=True))
        return
    if args.prepare:
        require(not out.exists(), 'fresh evidence directory required')
        packet, generated, blobs = preflight(ROOT)
        out.mkdir(parents=True)
        (out/'packet.json').write_text(json.dumps(packet, indent=2)+'\n')
        (out/'native.cpp').write_text(generated)
        (out/'fixture-input.txt').write_text(native_wire(packet))
        for path, raw in blobs.items():
            target = out/'inputs'/path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
    print(json.dumps(verify_preflight(ROOT, out), sort_keys=True))


if __name__ == '__main__':
    main()
