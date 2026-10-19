"""Negative acceptance cases: offline image parity must not imply live coverage."""
import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from run_cpu_geometry_diagnostic import LIVE_PHASES, live_history_exact, resident_preview_exact, preview_ui_exact


def complete_capture():
    groups = {}
    for index, (phase, (version, playing)) in enumerate(LIVE_PHASES.items(), 1):
        owner = '101' if version == 'v1' else '202'
        common = dict(phase=phase, pmmVersion=version, playing=playing,
                      process=owner, status='PASS', differentPixels='0', draws='1')
        rows = [dict(common, boundary=str(n), backend=backend, family='clear' if n == 0 else 'model_material')
                for n in range(2) for backend in ('dx11', 'dx12')]
        rows.append(dict(common, boundary='1', backend='both', family='lifecycle'))
        groups[(owner, str(index))] = rows
    return groups


class LiveEvidenceTest(unittest.TestCase):
    def test_preview_ui_requires_release_and_same_process_reload(self):
        rows=[dict(process=p,backend=b,operation='close',status='PASS',resident='0',retiring='0',device='0',epoch='0')
              for p in ('101','202') for b in ('dx11','dx12') for _ in range(3)]
        log='menu_open_close_cycles=3 per_backend PASS\n'*2+'same_process_v1_unload_empty_status_v2_reload=PASS\n'
        self.assertTrue(preview_ui_exact(rows,{'101','202'},log))
        for field in ('resident','retiring','device','epoch'):
            bad=copy.deepcopy(rows);bad[-1][field]='1'
            self.assertFalse(preview_ui_exact(bad,{'101','202'},log))
        self.assertFalse(preview_ui_exact(rows[:-1],{'101','202'},log))
        self.assertFalse(preview_ui_exact(rows,{'101','202'},log.split('same_process')[0]))
    def test_resident_requires_images_lifecycle_and_cache_reuse(self):
        rows=[]
        for process in ('101','202'):
            for backend in ('dx11','dx12'):
                common=dict(process=process,backend=backend,status='PASS',differentPixels='0',uploads='48',textureUploads='11',device=process+backend)
                rows.extend(dict(common,operation=operation) for operation in ['image']*4+['present']*5+['resize','suspend','replace'])
        self.assertTrue(resident_preview_exact(rows,{'101','202'},('dx11','dx12')))
        self.assertTrue(resident_preview_exact(rows,{'101','202'},('dx11','dx12'),{'101':4,'202':4}))
        self.assertFalse(resident_preview_exact(rows,{'101','202'},('dx11','dx12'),{'101':5,'202':4}))
        for operation in ('image','present','resize','suspend','replace'):
            filtered=[r for r in rows if not (r['process']=='202' and r['backend']=='dx12' and r['operation']==operation)]
            self.assertFalse(resident_preview_exact(filtered,{'101','202'},('dx11','dx12')))
        failed=copy.deepcopy(rows);failed[0]['differentPixels']='1'
        self.assertFalse(resident_preview_exact(failed,{'101','202'},('dx11','dx12')))
        changed=copy.deepcopy(rows)
        for n,r in enumerate(changed):r['uploads']=str(n)
        self.assertFalse(resident_preview_exact(changed,{'101','202'},('dx11','dx12')))
        self.assertFalse(resident_preview_exact(rows,{'101'},('dx11','dx12')))

    def test_complete_captures(self):
        self.assertTrue(live_history_exact(complete_capture()))

    def test_stopped_frame_labelled_playing(self):
        groups = complete_capture()
        for rows in groups.values():
            if rows[0]['phase'] == 'playing':
                for row in rows:
                    row['playing'] = '0'
        self.assertFalse(live_history_exact(groups))

    def test_partial_or_inconsistent_capture(self):
        base = complete_capture()
        changes = (
            lambda rows: rows.pop(1),
            lambda rows: rows.pop(),
            lambda rows: rows[2].update(differentPixels='1'),
            lambda rows: rows[2].update(pmmVersion='v2'),
            lambda rows: rows[2].update(playing='1'),
            lambda rows: rows[2].update(status='BLOCKED'),
            lambda rows: rows.reverse(),
        )
        for change in changes:
            with self.subTest(change=change):
                groups = copy.deepcopy(base)
                change(next(iter(groups.values())))
                self.assertFalse(live_history_exact(groups))

    def test_missing_reopen_or_duplicate_phase(self):
        groups = complete_capture()
        groups.pop(next(reversed(groups)))
        self.assertFalse(live_history_exact(groups))
        groups = complete_capture()
        groups[('101', '99')] = copy.deepcopy(next(iter(groups.values())))
        self.assertFalse(live_history_exact(groups))


if __name__ == '__main__':
    unittest.main()
