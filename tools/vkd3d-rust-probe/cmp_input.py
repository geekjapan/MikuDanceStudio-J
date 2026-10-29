import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
from typing import NamedTuple

CONTRACT_SHA256 = '51e155ac7517976290e7d1b5028b51947c685f7cab306558480c8a629d86f8b8'
CONTRACT_PATH = Path(__file__).with_name('cmp_input_contract.json')
SITE = 'libs/vkd3d-shader/spirv.c'


def require(ok, message):
    if not ok:
        raise ValueError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def read_json(path):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, 'duplicate JSON key ' + key)
            result[key] = value
        return result
    return json.loads(path.read_bytes(), object_pairs_hook=pairs)


def reviewed_contract(path=CONTRACT_PATH):
    data = path.read_bytes()
    require(sha(data) == CONTRACT_SHA256, 'unknown or modified reviewed contract')
    return read_json(path)


def file_identity(path):
    data = path.read_bytes()
    return {'sha256': sha(data), 'size': len(data), 'mode': stat.S_IMODE(path.stat().st_mode)}


def regular_tree(root):
    require(root.is_dir() and not root.is_symlink(), 'source/header root must be a real directory')
    result = {}
    for path in sorted(root.rglob('*')):
        mode = path.lstat().st_mode
        require(stat.S_ISREG(mode) or stat.S_ISDIR(mode), 'nonregular source/header path ' + str(path))
        if stat.S_ISREG(mode):
            result[path.relative_to(root).as_posix()] = file_identity(path)
    return result


def rewrite(source, contract, order):
    require(order in ('zero-first', 'type-first'), 'unknown CMP order')
    require(len(source) == contract['source_size'] and sha(source) == contract['source_sha256'],
            'original spirv.c identity differs or patch already applied')
    patch = contract['patches'][order]
    before, after = patch['before'].encode(), patch['after'].encode()
    require(sha(before) == patch['before_sha256'] and sha(after) == patch['after_sha256'], 'patch data differs')
    require(source.count(before) == 1, 'CMP call shape must occur exactly once')
    owner = source.index(b'static void spirv_compiler_emit_movc(')
    end = source.index(b'\nstatic void ', owner + 1)
    require(owner < source.index(before) < end, 'CMP site outside exact movc owner')
    for name in ('spirv_get_type_id', 'spirv_compiler_get_constant_float_vector'):
        require(source.count(('static uint32_t ' + name + '(').encode()) == 1,
                'reviewed helper UInt return declaration differs')
    normalized = source.replace(before, after, 1)
    require(sha(normalized) == patch['normalized_sha256'], 'normalized C hash differs')
    require(normalized.replace(after, before, 1) == source, 'non-CMP source delta')
    return normalized


class AdmittedInputs(NamedTuple):
    roots: dict
    manifests: dict
    members: dict
    native_library: Path
    native_identity: dict
    tool: Path | None


def canonical_input(path, name):
    path = Path(path).absolute()
    resolved = path.resolve(strict=True)
    require(path == resolved, 'symlink or alias input ' + name)
    return resolved


def admit_inputs(original, target, native_library, destinations, contract, *, tool=None):
    require(target == contract['target'], 'target has no reviewed immutable CMP contract')
    original = canonical_input(original, 'source')
    roots = {'source': original, 'hdr': original.parent / 'hdr/include', 'spv': original.parent / 'spv/include'}
    roots = {key: canonical_input(path, key) for key, path in roots.items()}
    native_library = canonical_input(native_library, 'native')
    require(native_library.is_file(), 'native library must be regular')
    if tool is not None:
        tool = canonical_input(tool, 'tool')
    domains = {**roots, 'native': native_library}
    if tool is not None:
        domains['tool'] = tool
    for destination in destinations:
        destination = Path(destination).absolute()
        require(destination == destination.resolve(), 'symlink or alias output')
        for key, path in domains.items():
            require(destination != path and destination not in path.parents and path not in destination.parents,
                    'owned parent/output overlaps input root ' + key)
    manifests = {key: regular_tree(path) for key, path in roots.items()}
    require(manifests == contract['manifests'], 'original source/header/configuration manifest differs')
    library = file_identity(native_library)
    require(all(library[key] == value for key, value in contract['native_library'].items()), 'fixed native library differs')
    if tool is not None:
        require(regular_tree(tool) == contract['tool_manifest'], 'unknown current translator tool manifest')
    members = {key: sorted(p.relative_to(path).as_posix() for p in path.rglob('*')) for key, path in roots.items()}
    return AdmittedInputs(roots, manifests, members, native_library, library, tool)


def normalize(original, target, native_library, output, ownership_root, *, contract_path=CONTRACT_PATH,
              opposite_control=False):
    """Publish a new ready input or leave an explicit, unusable failed directory.

    The opposite control is diagnostic data under the same Linux oracle contract.
    It never admits a second production contract or target.
    """
    contract = reviewed_contract(contract_path)
    output, ownership_root = Path(output), Path(ownership_root)
    require(not ownership_root.is_symlink() and ownership_root.is_dir(), 'owned parent must already exist')
    ownership_root = canonical_input(ownership_root, 'owned parent')
    require(output.parent.resolve(strict=True) == ownership_root and not output.is_symlink()
            and not output.exists(), 'output must be a fresh direct child of owned parent')
    require(output.absolute() == output.resolve(), 'symlink or alias output')
    output = ownership_root / output.name
    admitted = admit_inputs(original, target, native_library, (ownership_root, output), contract)
    roots, manifests = admitted.roots, admitted.manifests
    original, native_library = roots['source'], admitted.native_library
    library = admitted.native_identity
    order = 'type-first' if opposite_control else contract['order']
    normalized = rewrite((original / SITE).read_bytes(), contract, order)
    expected = json.loads(json.dumps(manifests))
    expected['source'][SITE].update(sha256=sha(normalized), size=len(normalized))
    output.mkdir()
    incomplete = output / 'INCOMPLETE'
    incomplete.write_text('Not a usable translation input until receipt.json reports ready.\n')
    try:
        destinations = {'source': output / 'source', 'hdr': output / 'hdr/include', 'spv': output / 'spv/include'}
        for key, root in roots.items():
            shutil.copytree(root, destinations[key])
        (destinations['source'] / SITE).write_bytes(normalized)
        actual = {key: regular_tree(root) for key, root in destinations.items()}
        require(actual == expected, 'copied normalized manifest differs')
        require({key: regular_tree(root) for key, root in roots.items()} == manifests
                and {key: sorted(p.relative_to(root).as_posix() for p in root.rglob('*'))
                     for key, root in roots.items()} == admitted.members,
                'original source changed while normalizing')
        require(file_identity(native_library) == library, 'native oracle changed while normalizing')
        patch = contract['patches'][order]
        receipt = {'state': 'ready', 'contract_sha256': CONTRACT_SHA256, 'contract_id': contract['id'],
                   'target': target, 'order': order, 'diagnostic_opposite_control': opposite_control,
                   'original_source': str(original), 'translation_source': str(destinations['source']),
                   'original_manifests': manifests, 'normalized_manifests': actual,
                   'native_library': str(native_library), 'native_identity': library,
                   'exact_delta': {'path': SITE, **patch},
                   'stable_build': 'UNRUN; historical E0554 is not acceptance',
                   'four_target_execution': 'UNRUN', 'product_integration': 'UNRUN'}
        temporary = output / 'receipt.pending'
        temporary.write_text(json.dumps(receipt, indent=2, sort_keys=True) + '\n')
        incomplete.unlink()
        os.replace(temporary, output / 'receipt.json')
        return receipt
    except BaseException as error:
        if not (output / 'receipt.json').exists():
            incomplete.write_text('Failed input; no ready receipt was published.\n')
        (output / 'failure.json').write_text(json.dumps({'state': 'failed', 'error': str(error)}) + '\n')
        raise
