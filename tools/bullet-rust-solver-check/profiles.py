"""Frozen native captures; no floating-point normalization is permitted."""
import hashlib
from pathlib import Path
import platform

DATA = Path(__file__).resolve().parents[2] / 'rust/crates/mds-bullet/tests/solver_data'
PROFILES = {
    'aarch64': ('native.tsv', '156498fd111eb89fa3d60c75edbaf5068a89acecd9cde7a48b573e7e53ef65d8'),
    'x86_64': ('native-x86_64.tsv', 'd0a64453bce494764fcfb8a43bdb284ad4634666aac141ad9ede3a635fa568f5'),
}


def fixture_path(machine=None):
    machine = platform.machine().lower() if machine is None else machine.lower()
    architecture = {'arm64': 'aarch64', 'amd64': 'x86_64'}.get(machine, machine)
    if architecture not in PROFILES:
        raise ValueError(f'Unsupported native joint fixture architecture: {machine}')
    return DATA / PROFILES[architecture][0]


def compare_capture(captured, fixture):
    if fixture.read_bytes() != captured:
        raise ValueError(f'Native joint output differs from checked-in fixture: {fixture.name}')


def verify_profiles():
    for name, digest in PROFILES.values():
        assert hashlib.sha256((DATA / name).read_bytes()).hexdigest() == digest, name
    arm = (DATA / PROFILES['aarch64'][0]).read_text().splitlines()
    x64 = (DATA / PROFILES['x86_64'][0]).read_text().splitlines()
    assert len(arm) == len(x64) == 518
    assert arm[:512] == x64[:512]
    differences = []
    events = 0
    for case, (a, b) in enumerate(zip(arm, x64)):
        aw, bw = a.split('\t'), b.split('\t')
        assert aw[0] == bw[0] == str(case)
        assert len(aw) == len(bw)
        assert aw[1:302] == bw[1:302], f'case {case} inputs'
        rows = int(aw[302], 16)
        if int(aw[2], 16) == 260:
            events += rows * 10
        for index, (av, bv) in enumerate(zip(aw[302:], bw[302:]), start=302):
            if av != bv:
                assert 512 <= case < 516
                assert (av, bv) == ('7fc00000', 'ffc00000')
                differences.append((case, index))
    assert len(differences) == 48
    assert events == 20_580
