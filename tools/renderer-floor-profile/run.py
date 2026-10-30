#!/usr/bin/env python3
"""Same-host importer/math diagnostic. Without --run, replay only reads evidence."""
import argparse
import importlib.util
import json
import math
import ntpath
import os
from pathlib import Path, PureWindowsPath
import re
import shutil
import struct
import sys
import tarfile

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
BASE = '77b3e431bc1ac2ab5610692f2e12c903a7629090'
BASE_TREE = '778782dc8ad6352585a9b7eeb135c04150d1f2e4'
SCHEMA = 'mds-floor-profile-v6-witness-extent'
CENSUS_SCHEMA = 'mds-renderer-required-closure-census-v1'
CENSUS_MANIFEST_REPRESENTATION = 'bounded-graph-references-v1'
CENSUS_BUILDS = ('control-Od','observed-Od','control-O2','observed-O2')
CENSUS_STATUSES = ('CENSUS_INCOMPLETE_UNRESOLVED','CENSUS_COMPLETE_DIAGNOSTIC_ONLY')
CENSUS_BASE = 'b1d81447991df6d1e530f8032170d1a8c308c56f'
CENSUS_PATHS = ['.github/workflows/renderer-closure-census.yml'] + [
    'tools/renderer-floor-profile/'+name for name in ('run.py','observer.rs','test_run.py')]
CENSUS_LIMITS = {'ranges':4096,'bytes':16*1024*1024,'single':128*1024,'sections':96,'seconds':1200}
PARENT = 'b7f1c87388606eee4328915504d34c5e9b63ab3a'
LEGACY_SOURCE_ADMISSION = 'fixed-main-9df59aec-v1'
SOURCE_ADMISSION = 'fixed-main-5f9fec72-v1'
MAIN_SOURCE_ADMISSION = 'fixed-main-0363e9ac-v1'
MAIN_IMPORT = {
    'origin':'0363e9ac9f4ca3eae1f1c73de502f45ede1d6d7f',
    'origin_tree':'6e73c71cb121fe11e5bc3affc2064d3ae3eb225f',
    'origin_parents':['5f9fec72843431d09d21fa1a324376a36b0a3d17','4bc29bd854f2e9ae73da22a01a0d4084ea707ff3'],
    'preceding':'94fdeac3fbbcdf4558e7f9b1948bcbdb9d4e100e',
    'applied':'278b17e9885bc0875ecfdb78e84f8a776a252dfc',
    'applied_tree':'13b0311f6754b412e4ecf89c65916d81a747e3d1'}
MAIN_IMPORT_ENTRIES = {
    '.github/workflows/windows-build.yml':['100644','a3d258a8bdaa6e24e79e8871e2a054aa4ee75d58'],
    'tools/ci/install-directx-runtime.ps1':['100644','8d341f77c143d2e6b1d939a03a17431fbc886b50'],
    'tools/ci/test-directx-runtime.ps1':['100644','fe451045a0211a0c3d687b3f73914980c063170c']}
CURRENT_IMPORT = {
    'origin':'5f9fec72843431d09d21fa1a324376a36b0a3d17',
    'origin_tree':'c05f458380c1352e1e650facdb90d454e730ed7c',
    'origin_parents':['f6ab4feef335e76d590c3f8a9c5f532dec73ba70','9a2baa350d23cddfe692ca57ca32f156c44bcc0d'],
    'preceding':'900ba8b2694e1357d5a70f188aa5de2be829d199',
    'applied':'4e713c318dcd5d69ca85f9cc1ad361cf09d02d5f',
    'applied_tree':'48f624f31b2367d4ad8a5001a09f540c577d8622'}
CURRENT_IMPORT_ENTRIES = {
    '.github/workflows/bullet-dynamics-world.yml':['100644', 'f3ae1766ef8c45d1f260463377c6c89566b0a96d'],
    'rust/crates/mds-bullet/src/core/discrete_collision_world.rs':['100644', '7f9deffb2f9bdfb95c1649f6ddc2aa90ee7b15d6'],
    'rust/crates/mds-bullet/src/core/discrete_dynamics_world.rs':['100644', '8cde2d1dff4bf5cd8d5cbe550e795497946df2b1'],
    'rust/crates/mds-bullet/src/core/mod.rs':['100644', '0a91edb2e97df5862263c7399e87b61fe29c35e8'],
    'rust/crates/mds-bullet/src/core/world_objects.rs':['100644', 'cec3008cfedc2c8a16dc673468ae468222124e6c'],
    'rust/crates/mds-bullet/tests/discrete_dynamics_world.rs':['100644', 'd655428a8320e11dfd1daf6ccdb3a785a4646272'],
    'tools/bullet-rust-dynamics-world-check/README.md':['100644', '675df13724685a3c9df6902b30d6c5db09f194dd'],
    'tools/bullet-rust-dynamics-world-check/allocator.hpp':['100644', '25a69b88f962a8b1f794df42c95150ec1aec3f2c'],
    'tools/bullet-rust-dynamics-world-check/cases.py':['100644', 'e5db6952ffd9d5a15d5cb3960f957c3a50d47876'],
    'tools/bullet-rust-dynamics-world-check/check.py':['100644', '167dfd5e4dad6d90a2c78cda13981a0751f548ce'],
    'tools/bullet-rust-dynamics-world-check/dynamics_fixture.rs':['100644', '104299efc1ac8de114b4109d0c2eb23c9f948a97'],
    'tools/bullet-rust-dynamics-world-check/evidence.py':['100644', '286d1087fa2b9b9c3bbbd47a42b8b693d83225f5'],
    'tools/bullet-rust-dynamics-world-check/fixture.rs':['100644', 'bd0bbb68b282bb42db264f0cea236763c47d079e'],
    'tools/bullet-rust-dynamics-world-check/hooks.py':['100644', '0dcfe49924789ae5f5aeea6a7c6e636ba0b96a71'],
    'tools/bullet-rust-dynamics-world-check/observer.h':['100644', 'e0f42c98920a4bd5fdcaa0307b3d3045e304cb64'],
    'tools/bullet-rust-dynamics-world-check/observer.rs':['100644', '44b94812dc88fe3fad93b1b6f204b95fcfa52faa'],
    'tools/bullet-rust-dynamics-world-check/oracle.cpp':['100644', 'af1fc1f27625956ae30d67105a8b84d5820c448d'],
    'tools/bullet-rust-dynamics-world-check/runner.rs':['100644', 'c1f07397568d02b510b7fcb323e37549b71ca4bd'],
    'tools/bullet-rust-dynamics-world-check/synthetic.py':['100644', '4b9dfd612d92da818c50e2a9c07cfad87c42d6f5'],
    'tools/bullet-rust-dynamics-world-check/test_check.py':['100644', '8f4860c1ab1d3a7f9ed8adc1fe53cbc71eae6e30'],
    'tools/bullet-rust-dynamics-world-check/test_dynamics.py':['100644', '48b5b10dc6889b60d26f27178cf04fc2ec54a128'],
    'tools/bullet-rust-dynamics-world-check/test_evidence.py':['100644', '767c60eb8fec7ff79145dd237830b19ef1cd9213'],
    'tools/bullet-rust-dynamics-world-check/trace.py':['100644', '9694b2f3f87ceedc1f76ecee3648c6f9022189a4'],
    'tools/bullet-rust-dynamics-world-check/world_objects_fixture.rs':['100644', 'e348f5a257861dcec338e29ae03856b8c86430a9'],
    'tools/bullet-rust-gjk-pair-check/README.md':['100644', 'c353451a3b782cbe191f1d9aa4ec2d91ac666844'],
    'tools/bullet-rust-gjk-pair-check/measured-profiles.json':['100644', 'f4a1e2064c26753f278e2a952f53861502487968'],
    'tools/bullet-rust-gjk-pair-check/measured_profiles.py':['100644', '8506a6d9a6d629131c8c76b089fba9623df80c9f'],
    'tools/bullet-rust-gjk-pair-check/test_measured_profiles.py':['100644', 'a4cef940a72d0e0fa8f936adfacbbd9d0c8376ca']}
FIXED_IMPORT = {
    'origin':'9a2baa350d23cddfe692ca57ca32f156c44bcc0d',
    'parent':'f6ab4feef335e76d590c3f8a9c5f532dec73ba70',
    'parent_tree':'005ae1183e9972df56689796cf87589117418e7d',
    'origin_tree':'c05f458380c1352e1e650facdb90d454e730ed7c',
    'applied':'9a0910d273706c80e99f24ee330e12693ea6840b',
    'preceding':'843fd84b35e2629a5c008fb00933cb0d14655072',
    'applied_tree':'d063c4f6a57a7188df9806380abaf16cc0059d72'}
FIXED_IMPORT_BLOBS = {
    '.github/workflows/windows-build.yml':('5b60e70bea8b6c4b1c7ba162e99ad4e63cbef32e','e873f0de37a190f54f1f7c1e1dff2bc920eee219'),
    'tools/bullet-dbvt-cmake-reference/check.py':('dae333fa7078c08d9acc0c565cf92c80129024f7','1bc6303d748701ed8816f069b9f93f2bb28db00d'),
    'tools/bullet-dbvt-cmake-reference/test_check.py':('b7858502179b08cfc6c68b02ad79a52537992ff3','a1be6a32fe772b3643b8e1dd3a24adde29b09763')}
ACCEPTED_MAIN = {
    'common':'3cf0711d38f94e6be5c5d06129257d1c963f973a',
    'renderer':'634a6d3c35cd0ea1229c56d9d2eb2b336a315f60',
    'main':'816df8133b021359a2684c2ad5fd3666583c7c60',
    'merge':'9df59aec035262382b5f96d100de00204f25a815'}
ACCEPTED_MERGE_TREE = 'ffa0f0d5e9da6896b82d34bd91e98e9c3f3dd20b'
FP_CONTRACT = {'snapshot':'HardwareMxcsr', 'identity':'SourceSiteOnly',
               'rust_operation_ordering':'Unproved', 'exception_attribution':'Unsupported',
               'operation_environment':'Unproved'}
RUST_FLAGS = '--cfg mds_floor_profile --check-cfg=cfg(mds_floor_profile) -C link-arg=/MAP'
PATHS = ['.github/workflows/renderer-floor-profile.yml'] + [
    'tools/renderer-floor-profile/'+n for n in
    ('run.py','native.cpp.in','native_observer.hpp','observer.rs','test_run.py')]
MESH = 'rust/crates/mds-accessory/src/mesh.rs'
ACCESSORY = 'src/render/accessory.cpp'
FLOOR = 'tests/fixtures/rust/golden2/shadow_floor.x'
FLOOR_SHA = 'adfd3e6fb4b552f6c38eb9b94bc8b75061270e7d24a4933694c73df02e58122c'
IDENTITY = [1.,0.,0.,0.,0.,1.,0.,0.,0.,0.,1.,0.,0.,0.,0.,1.]
AFFINE = [2.,0.,0.,0.,0.,3.,0.,0.,0.,0.,4.,0.,.5,2.,-.25,1.]
PROJECTIVE = IDENTITY[:-1]+[3.]
MATRICES = [IDENTITY,AFFINE,PROJECTIVE]
POINTS = [[-1.,0.,-1.],[-1.,0.,1.],[1.,0.,1.],[1.,0.,-1.],[1.,1.,-1.]]
CASES = [('floor-top',FLOOR,None),('floor-identity',FLOOR,0),
         ('floor-affine',FLOOR,1),('cube','tests/fixtures/rust/accessory/cube.x',None),
         ('frames','tests/fixtures/rust/accessory/frames.x',None)]

def module(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT/path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result

previous = module('profile_prior', 'tools/renderer-floor-geometry/run.py')
c = previous.c
h = c.h
require, digest, load_json = previous.require, previous.digest, previous.load_json
checked, readonly = previous.checked, previous.readonly

def record(out,label,argv,cwd,env,timeout=1200):
    if env.get('MDS_CENSUS_CUSTODY'):census_custody(Path(env['MDS_CENSUS_CUSTODY']))
    binary=Path(argv[0]).read_bytes() if label in ('native','rust') else None
    tool=Path(argv[0]).read_bytes() if label=='instruction-help' or '-instructions-' in label else None
    if env.get('MDS_CENSUS_DEADLINE'):
        row=census_command(out,label,argv,cwd,env,timeout)
    elif label=='rust':
        require(not (out/(label+'.json')).exists(),'fresh own-process command')
        row={'argv':list(map(str,argv)),'cwd':str(cwd),'env':{k:v for k,v in env.items() if k in
             ('PATH','HOME','CARGO_HOME','RUSTUP_HOME','TMPDIR','LD_LIBRARY_PATH','WGPU_BACKEND','VK_ICD_FILENAMES',
              'XDG_RUNTIME_DIR','CARGO_TERM_COLOR','CARGO_INCREMENTAL','CARGO_TARGET_DIR','CXX','MDS_RENDER_PNG_DIR',
              'INCLUDE','LIB','LIBPATH','VCToolsInstallDir','WindowsSdkDir','WindowsSDKVersion')},'start_utc':previous.utc(),
             'start_ns':previous.time.time_ns(),'status':None,'terminal':'launch_failure'}
        try:
            with (out/(label+'.stdout')).open('xb') as stdout,(out/(label+'.stderr')).open('xb') as stderr:
                with previous.subprocess.Popen(row['argv'],cwd=cwd,env=env,stdout=stdout,stderr=stderr) as child:
                    row['pid']=child.pid
                    try:row.update(status=child.wait(timeout=timeout),terminal='exit')
                    except previous.subprocess.TimeoutExpired:
                        child.kill();child.wait();row['terminal']='timeout'
        finally:
            row.update(end_utc=previous.utc(),end_ns=previous.time.time_ns())
            for suffix in ('stdout','stderr'):
                raw=(out/(label+'.'+suffix)).read_bytes();row[suffix]={'name':label+'.'+suffix,'sha256':digest(raw),'size':len(raw)}
            write_json(out/(label+'.json'),row)
    else:row=previous.record(out,label,argv,cwd,env,timeout)
    if 'RUSTFLAGS' in env:
        for key in ('RUSTFLAGS','CL','_CL_'):row['env'][key]=env[key]
    if binary is not None:
        require(Path(argv[0]).read_bytes()==binary,'executed retained binary changed')
        row['executed_binary']={'path':str(argv[0]),'sha256':digest(binary),'size':len(binary)}
    if tool is not None:
        require(Path(argv[0]).read_bytes()==tool,'hosted instruction tool changed')
        if label=='instruction-help':(out/'instruction-tool.bin').write_bytes(tool)
        require((out/'instruction-tool.bin').read_bytes()==tool,'retained hosted instruction tool changed')
        row['tool_binary']={'path':str(argv[0]),'sha256':digest(tool),'size':len(tool)}
    write_json(out/(label+'.json'),row)
    return row


CUSTODY_SCHEMA = 'mds-census-writer-custody-v1'


def census_custody(out):
    marker=out/'writer-pending.json'
    require(not marker.exists(),'unclosed diagnostic writers marker')
    state=load_json((out/'writer-custody.json').read_bytes())
    require(state['schema']==CUSTODY_SCHEMA and state['state'] in ('no_writer_started','closed'),
            'unclosed diagnostic writers state')
    receipts=state['receipts']
    require(type(receipts) is list and len(set(receipts))==len(receipts),'explicit custody command receipts')
    require((state['state']=='no_writer_started')==(len(receipts)==0),'explicit startup custody classification')
    for name in receipts:
        require(type(name) is str and not Path(name).is_absolute() and '..' not in Path(name).parts,'owned custody receipt path')
        require(load_json((out/name).read_bytes()).get('writer_closure') is True,'unclosed diagnostic writers receipt')
    return state


def census_windows_job():
    import ctypes
    from ctypes import wintypes
    class BasicLimits(ctypes.Structure):
        _fields_=[('process_time',ctypes.c_int64),('job_time',ctypes.c_int64),('flags',wintypes.DWORD),
                  ('min_working_set',ctypes.c_size_t),('max_working_set',ctypes.c_size_t),
                  ('active_limit',wintypes.DWORD),('affinity',ctypes.c_size_t),('priority',wintypes.DWORD),('scheduling',wintypes.DWORD)]
    class IoCounters(ctypes.Structure):
        _fields_=[(name,ctypes.c_uint64) for name in ('read_ops','write_ops','other_ops','read_bytes','write_bytes','other_bytes')]
    class ExtendedLimits(ctypes.Structure):
        _fields_=[('basic',BasicLimits),('io',IoCounters),('process_memory_limit',ctypes.c_size_t),
                  ('job_memory_limit',ctypes.c_size_t),('peak_process_memory',ctypes.c_size_t),('peak_job_memory',ctypes.c_size_t)]
    class Accounting(ctypes.Structure):
        _fields_=[(name,ctypes.c_int64) for name in ('user_time','kernel_time','period_user_time','period_kernel_time')]+[(name,wintypes.DWORD) for name in ('page_faults','total_processes','active_processes','terminated_processes')]
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    declarations={'CreateJobObjectW':([ctypes.c_void_p,wintypes.LPCWSTR],wintypes.HANDLE),
                  'SetInformationJobObject':([wintypes.HANDLE,ctypes.c_int,ctypes.c_void_p,wintypes.DWORD],wintypes.BOOL),
                  'QueryInformationJobObject':([wintypes.HANDLE,ctypes.c_int,ctypes.c_void_p,wintypes.DWORD,ctypes.c_void_p],wintypes.BOOL),
                  'AssignProcessToJobObject':([wintypes.HANDLE,wintypes.HANDLE],wintypes.BOOL),
                  'TerminateJobObject':([wintypes.HANDLE,wintypes.UINT],wintypes.BOOL),
                  'CloseHandle':([wintypes.HANDLE],wintypes.BOOL)}
    for name,(args,result) in declarations.items():
        function=getattr(kernel,name);function.argtypes=args;function.restype=result
    resume=ctypes.WinDLL('ntdll').NtResumeProcess;resume.argtypes=[wintypes.HANDLE];resume.restype=ctypes.c_long
    class Job:
        def __init__(self):self.handle=None;self.create_attempted=False
        def setup(self):
            self.create_attempted=True
            self.handle=kernel.CreateJobObjectW(None,None)
            require(self.handle,'diagnostic process job creation')
            limits=ExtendedLimits();limits.basic.flags=0x2000
            require(kernel.SetInformationJobObject(self.handle,9,ctypes.byref(limits),ctypes.sizeof(limits)),'kill-on-close diagnostic process job')
        def assign(self,child):
            require(kernel.AssignProcessToJobObject(self.handle,int(child._handle)),'diagnostic child tree containment before execution')
        def resume(self,child):require(resume(int(child._handle))==0,'diagnostic suspended process resume')
        def terminate(self):
            if self.handle:require(kernel.TerminateJobObject(self.handle,1),'diagnostic descendants termination')
        def accounting(self):
            value=Accounting()
            require(kernel.QueryInformationJobObject(self.handle,1,ctypes.byref(value),ctypes.sizeof(value),None),'diagnostic process closure accounting')
            return value
        def resources(self,accounting):
            limits=ExtendedLimits()
            require(kernel.QueryInformationJobObject(self.handle,9,ctypes.byref(limits),ctypes.sizeof(limits),None),'diagnostic memory accounting')
            return {'peak_process_memory_bytes':limits.peak_process_memory,'peak_job_memory_bytes':limits.peak_job_memory,
                    'user_time_100ns':accounting.user_time,'kernel_time_100ns':accounting.kernel_time,'total_processes':accounting.total_processes}
        def close(self):
            require(not self.create_attempted or self.handle is not None,'diagnostic job creation returned no owned handle')
            if self.handle:
                require(kernel.CloseHandle(self.handle),'diagnostic job handle close')
                self.handle=None
    return Job()


def census_command(out,label,argv,cwd,env,timeout):
    require(sys.platform=='win32' and os.environ.get('GITHUB_ACTIONS')=='true','hosted census command only')
    root=Path(env['MDS_CENSUS_CUSTODY'])
    state=census_custody(root)
    require(not (out/(label+'.json')).exists(),'fresh diagnostic command receipt')
    remaining=float(env['MDS_CENSUS_DEADLINE'])-previous.time.monotonic()
    require(remaining>0,'diagnostic variant wall time ceiling reached')
    timeout=min(timeout,remaining)
    receipt=(out/(label+'.json')).relative_to(root).as_posix()
    row={'argv':list(map(str,argv)),'cwd':str(cwd),'env':{k:env[k] for k in ('PATH','HOME','CARGO_HOME','RUSTUP_HOME','TMPDIR','CARGO_TARGET_DIR','CARGO_INCREMENTAL','CARGO_TERM_COLOR','RUSTFLAGS','CL','_CL_','INCLUDE','LIB','LIBPATH','VCToolsInstallDir','WindowsSdkDir','WindowsSDKVersion') if k in env},
         'start_utc':previous.utc(),'start_ns':previous.time.time_ns(),'status':None,'terminal':'launch_failure',
         'timeout_seconds':timeout,'writer_closure':None}
    write_json(root/'writer-pending.json',{'schema':CUSTODY_SCHEMA,'receipt':receipt,'state':'unknown'})
    write_json(root/'writer-custody.json',dict(state,state='unknown'))
    child=None;job=None;launch_attempted=False;streams=[];cleanup_errors=[];accounting=None;closed=True;stream_acquiring=False;resource_failure=None
    def cleanup(action):
        nonlocal closed
        try:action()
        except BaseException as error:
            closed=False;cleanup_errors.append(type(error).__name__+': '+str(error))
    try:
        job=census_windows_job();job.setup()
        for suffix in ('stdout','stderr'):
            stream_acquiring=True
            streams.append((out/(label+'.'+suffix)).open('xb'))
            stream_acquiring=False
        launch_attempted=True
        child=previous.subprocess.Popen(row['argv'],cwd=cwd,env=env,stdout=streams[0],stderr=streams[1],creationflags=4)
        row['pid']=child.pid
        job.assign(child)
        job.resume(child)
        try:row.update(status=child.wait(timeout=timeout),terminal='exit')
        except previous.subprocess.TimeoutExpired:row['terminal']='timeout'
    except BaseException as error:
        row['error']=type(error).__name__+': '+str(error)
        raise
    finally:
        if stream_acquiring:
            closed=False;cleanup_errors.append('stream acquisition returned no owned descriptor')
        if launch_attempted and child is None:
            closed=False;cleanup_errors.append('launch returned no owned process handle')
        if job is not None:cleanup(job.terminate)
        if child is not None:
            cleanup(child.kill)
            cleanup(lambda:child.wait(timeout=10))
        if job is not None and child is not None:
            try:
                accounting=job.accounting();until=previous.time.monotonic()+10
                while accounting.active_processes and previous.time.monotonic()<until:
                    previous.time.sleep(0.01);accounting=job.accounting()
                require(accounting.active_processes==0,'diagnostic writers are not closed')
            except BaseException as error:
                closed=False;cleanup_errors.append(type(error).__name__+': '+str(error))
        if closed and accounting is not None:
            try:row['resources']=job.resources(accounting)
            except BaseException as error:
                resource_failure=error;row['resource_error']=type(error).__name__+': '+str(error)
        if child is not None:cleanup(child._handle.Close)
        if job is not None:cleanup(job.close)
        for stream in streams:cleanup(stream.close)
        row['writer_closure']=True if closed else None
        row.update(end_utc=previous.utc(),end_ns=previous.time.time_ns(),cleanup_errors=cleanup_errors)
        if closed:
            for suffix in ('stdout','stderr'):
                path=out/(label+'.'+suffix)
                if path.exists():
                    raw=path.read_bytes();row[suffix]={'name':path.name,'sha256':digest(raw),'size':len(raw)}
        write_json(out/(label+'.json'),row)
        if closed:
            write_json(root/'writer-custody.json',{'schema':CUSTODY_SCHEMA,'state':'closed','receipts':state['receipts']+[receipt]})
            (root/'writer-pending.json').unlink()
        require(closed,'unclosed diagnostic writers; retain marker and prohibit publication')
    if resource_failure is not None:raise resource_failure
    return row


def write_json(path, value):
    path.write_text(json.dumps(value,indent=2,sort_keys=True)+'\n',encoding='utf-8')


BOUND_SCHEMA = 'mds-bounded-document-v1'
BOUND_PAGE_BYTES = 4*1024*1024
BOUND_LIMITS = {'document_bytes':512*1024*1024,'cumulative_bytes':2*1024*1024*1024,
                'depth':128,'references':4000000,'shards':16384}
BOUND_SERIALIZER = {'sort_keys':True,'indent':2,'ensure_ascii':True,'allow_nan':False,
                    'encoding':'utf-8','newline':'LF','trailing_newline':True}


class BoundDocumentLimit(ValueError):
    pass


def bound_check(condition,message):
    if not condition:raise BoundDocumentLimit(message)


def bound_name(name):
    h.safe_name(name)
    require(':' not in name and all(part==part.rstrip(' .') and
            part.split('.')[0].upper() not in {'CON','PRN','AUX','NUL'} and
            not re.fullmatch(r'(?i)(COM|LPT)[1-9]',part.split('.')[0])
            for part in name.split('/')),'canonical bounded member name')
    return name


def bound_bytes(value):
    return (json.dumps(value,sort_keys=True,indent=2,ensure_ascii=True,allow_nan=False)+'\n').encode('utf-8')


def bound_preflight(value):
    state={'bytes':1,'estimate':0,'references':0};active=set()
    def charge(size=0,estimate=0):
        state['bytes']+=size;state['estimate']+=estimate
        bound_check(state['bytes']<=BOUND_LIMITS['document_bytes'],'bounded original serialization estimate')
        bound_check(state['estimate']<=BOUND_LIMITS['document_bytes'],'bounded document allocation estimate')
        bound_check(state['bytes']+state['estimate']<=BOUND_LIMITS['cumulative_bytes'],'bounded cumulative preflight')
    def walk(item,depth):
        state['references']+=1
        bound_check(depth<=BOUND_LIMITS['depth'] and state['references']<=BOUND_LIMITS['references'],'bounded document depth/references')
        kind=type(item)
        if kind in (dict,list):
            bound_check(id(item) not in active,'bounded document cycle')
            count=len(item)
            charge(2,8+count*(8+2*depth))
            # Nonempty pretty-printed containers include child and closing lines.
            if count:charge(count*(1+2*(depth+1))+count-1+1+2*depth)
            active.add(id(item))
            try:
                if kind is dict:
                    for key,child in item.items():
                        bound_check(type(key) is str,'bounded document string keys')
                        walk(key,depth+1);charge(2);walk(child,depth+1)
                else:
                    for child in item:walk(child,depth+1)
            finally:active.remove(id(item))
        elif kind is str:
            charge(2,len(item)*12+8)
            for char in item:
                code=ord(char)
                bound_check(not 0xd800<=code<=0xdfff,'bounded UTF-8 string')
                charge(12 if code>0xffff else 6 if code>=127 or code<32 and char not in '\b\f\n\r\t' else
                       2 if char in '\"\\\b\f\n\r\t' else 1)
        else:
            bound_check(kind in (type(None),bool,int,float),'bounded document scalar type')
            bound_check(kind is not float or math.isfinite(item),'bounded document finite scalar')
            bound_check(kind is not int or item.bit_length()<=256,'bounded document integer width')
            # 30103/100000 exceeds log10(2); include sign without str(huge_int).
            size=(item.bit_length()*30103//100000+2) if kind is int else 32 if kind is float else 5 if kind is bool else 4
            charge(size,96)
    walk(value,0)
    return state['bytes']


def bound_records(value,depth=0,state=None):
    if state is None:state={'references':0,'estimate':0}
    state['references']+=1
    bound_check(depth<=BOUND_LIMITS['depth'] and state['references']<=BOUND_LIMITS['references'],'bounded document depth/references')
    kind=type(value)
    if kind in (dict,list):
        bound_check(kind is list or all(type(key) is str for key in value),'bounded document string keys')
        state['estimate']+=8+len(value)*(8+2*depth)
        bound_check(state['estimate']<=BOUND_LIMITS['document_bytes'],'bounded document allocation estimate')
        yield ['object' if kind is dict else 'array',len(value)]
        for key in sorted(value) if kind is dict else range(len(value)):
            if kind is dict:yield from bound_records(key,depth+1,state)
            yield from bound_records(value[key],depth+1,state)
    elif kind is str:
        bound_check(not any(0xd800<=ord(char)<=0xdfff for char in value),'bounded UTF-8 string')
        state['estimate']+=len(value)*12+8
        bound_check(state['estimate']<=BOUND_LIMITS['document_bytes'],'bounded document string allocation')
        yield ['string',len(value)]
        # Even fully escaped non-BMP characters fit a minimum test page.
        for at in range(0,len(value),32):yield ['fragment',value[at:at+32]]
    else:
        bound_check(kind in (type(None),bool,int,float),'bounded document scalar type')
        bound_check(kind is not float or math.isfinite(value),'bounded document finite scalar')
        bound_check(kind is not int or value.bit_length()<=256,'bounded document integer width')
        state['estimate']+=96
        bound_check(state['estimate']<=BOUND_LIMITS['document_bytes'],'bounded document scalar allocation')
        yield ['scalar',value]


def bound_document(value,original,page_budget=BOUND_PAGE_BYTES,*,serialized=None):
    """Pure producer: typed preorder pages; original JSON is never parsed."""
    bound_check(type(page_budget) is int and 512<=page_budget<=BOUND_PAGE_BYTES,'bounded page budget')
    bound_name(original)
    bound_preflight(value)
    raw=bound_bytes(value) if serialized is None else serialized
    bound_check(len(raw)<=BOUND_LIMITS['document_bytes'],'bounded original bytes')
    pages={};rows=[];total=len(raw);records=[];encoded_size=0
    prefix=original+'.pages/'
    def flush():
        nonlocal records,encoded_size,total
        if not records:return
        ordinal=len(rows)
        bound_check(ordinal<BOUND_LIMITS['shards'],'bounded shard count')
        body=bound_bytes({'schema':BOUND_SCHEMA,'ordinal':ordinal,'records':records})
        bound_check(len(body)<=page_budget,'bounded page envelope')
        total+=len(body)
        bound_check(total<=BOUND_LIMITS['cumulative_bytes'],'bounded cumulative bytes')
        name=prefix+str(ordinal).zfill(5)+'.json'
        pages[name]=body;rows.append({'name':name,'size':len(body),'sha256':digest(body)})
        records=[];encoded_size=0
    for row in bound_records(value):
        size=len(bound_bytes(row))+32
        if records and encoded_size+size+128>page_budget:flush()
        records.append(row);encoded_size+=size
    flush()
    binding={'schema':BOUND_SCHEMA,'kind':'complete','original':{'name':original,'size':len(raw),'sha256':digest(raw)},
             'serializer':BOUND_SERIALIZER,'root':0,'pages':rows,'limits':BOUND_LIMITS}
    index=bound_bytes(binding)
    bound_check(len(index)<=BOUND_PAGE_BYTES and total+len(index)<=BOUND_LIMITS['cumulative_bytes'],'bounded binding bytes')
    return raw,index,pages


def write_bound_document(path,value):
    binding_path=path.with_name(path.name+'.binding.json')
    try:bound_preflight(value)
    except BoundDocumentLimit as error:
        witness={'schema':BOUND_SCHEMA,'kind':'incomplete','phase':'preflight','reason':str(error),
                'original_created':False,'semantic_status':'UNRUN'}
        binding_path.write_bytes(bound_bytes(witness))
        return witness
    raw=bound_bytes(value)
    path.write_bytes(raw)
    original={'name':path.name,'size':len(raw),'sha256':digest(raw)}
    try:_,index,pages=bound_document(value,path.name,serialized=raw)
    except BoundDocumentLimit as error:
        witness={'schema':BOUND_SCHEMA,'kind':'incomplete','phase':'partition','reason':str(error),
                 'original_created':True,'original':original,'semantic_status':'UNRUN'}
        binding_path.write_bytes(bound_bytes(witness))
        return witness

    for name,body in pages.items():
        target=path.parent/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(body)
    binding_path.write_bytes(index)
    return {'kind':'complete','binding':{'name':binding_path.name,'size':len(index),'sha256':digest(index)},
            'original':original}


def bound_json(raw):
    require(type(raw) is bytes and len(raw)<=BOUND_PAGE_BYTES,'bounded JSON bytes')
    depth=0;quoted=False;escaped=False
    for byte in raw:
        if quoted:
            if escaped:escaped=False
            elif byte==92:escaped=True
            elif byte==34:quoted=False
        elif byte==34:quoted=True
        elif byte in (91,123):
            depth+=1;require(depth<=BOUND_LIMITS['depth'],'bounded JSON preparse depth')
        elif byte in (93,125):depth-=1
    def pairs(rows):
        result={}
        for key,value in rows:
            require(key not in result,'duplicate bounded JSON key');result[key]=value
        return result
    def constant(value):raise ValueError('nonfinite bounded JSON')
    def integer(value):
        result=int(value);require(result.bit_length()<=256,'bounded integer width');return result
    def floating(value):
        result=float(value);require(math.isfinite(result),'finite bounded number');return result
    return json.loads(raw.decode('utf-8'),object_pairs_hook=pairs,parse_constant=constant,parse_int=integer,parse_float=floating)


def admit_bound_document(binding_name,inventory,read):
    """Inventory is externally authenticated; read returns the same verified bytes.

    This admits structure/raw identity only. Independent graph, decode, source,
    compiler and custody checks must still run on the restored object.
    """
    bound_name(binding_name)
    require(type(inventory) is dict and len(inventory)<=200000,'bounded external member count')
    for member in inventory:bound_name(member)
    def identity(name):
        bound_name(name);row=inventory[name]
        require(type(row) is dict and set(row)=={'size','sha256'} and type(row['size']) is int and
                0<=row['size']<=BOUND_LIMITS['cumulative_bytes'] and type(row['sha256']) is str and
                re.fullmatch('[0-9a-f]{64}',row['sha256']),'external bounded member identity')
        return row
    def get(name):
        row=identity(name);require(row['size']<=BOUND_PAGE_BYTES,'bounded member before read')
        raw=read(name)
        require(type(raw) is bytes and len(raw)==row['size'] and digest(raw)==row['sha256'],'same bytes bounded identity before parse')
        return bound_json(raw)
    binding=get(binding_name)
    require(type(binding) is dict and set(binding)=={'schema','kind','original','serializer','root','pages','limits'} and
            binding['schema']==BOUND_SCHEMA and binding['kind']=='complete' and bound_bytes(binding['serializer'])==bound_bytes(BOUND_SERIALIZER) and
            bound_bytes(binding['limits'])==bound_bytes(BOUND_LIMITS) and type(binding['root']) is int and binding['root']==0,'closed bounded binding')
    original=binding['original']
    require(type(original) is dict and set(original)=={'name','size','sha256'} and type(original['name']) is str and
            type(original['size']) is int and type(original['sha256']) is str,'bounded original identity')
    name=original['name'];require(binding_name==name+'.binding.json','bounded binding name')
    require(identity(name)=={k:original[k] for k in ('size','sha256')} and original['size']<=BOUND_LIMITS['document_bytes'],'opaque original inventory binding')
    pages=binding['pages'];prefix=name+'.pages/'
    require(type(pages) is list and 0<len(pages)<=BOUND_LIMITS['shards'],'bounded closed page count')
    names=[];total=original['size']+identity(binding_name)['size']
    for ordinal,row in enumerate(pages):
        require(type(row) is dict and set(row)=={'name','size','sha256'} and type(row['size']) is int and type(row['sha256']) is str and
                row['name']==prefix+str(ordinal).zfill(5)+'.json','ordered unique bounded pages')
        require(identity(row['name'])=={k:row[k] for k in ('size','sha256')} and 0<row['size']<=BOUND_PAGE_BYTES,'external page binding')
        total+=row['size'];require(total<=BOUND_LIMITS['cumulative_bytes'],'bounded cumulative allocation')
        names.append(row['name'])
    require({key for key in inventory if key.replace('\\','/').casefold().startswith(prefix.casefold())}==set(names),'complete closed page membership')
    def records():
        count=0
        for ordinal,page_name in enumerate(names):
            page=get(page_name)
            require(type(page) is dict and set(page)=={'schema','ordinal','records'} and page['schema']==BOUND_SCHEMA and
                    type(page['ordinal']) is int and page['ordinal']==ordinal and type(page['records']) is list and page['records'],'closed typed page')
            for row in page['records']:
                count+=1;require(count<=BOUND_LIMITS['references']*4,'bounded record allocation')
                require(type(row) is list and len(row)==2 and type(row[0]) is str,'closed typed record')
                yield row
    stream=iter(records());state={'references':0,'estimate':0}
    def restore(depth=0):
        state['references']+=1
        require(depth<=BOUND_LIMITS['depth'] and state['references']<=BOUND_LIMITS['references'],'bounded reconstruction depth/references')
        try:kind,value=next(stream)
        except StopIteration:raise ValueError('missing bounded record')
        if kind=='scalar':
            require(type(value) in (type(None),bool,int,float),'typed scalar record');state['estimate']+=96
            result=value
        else:
            require(kind in ('object','array','string') and type(value) is int and 0<=value<=(BOUND_LIMITS['document_bytes'] if kind=='string' else BOUND_LIMITS['references']),'typed container length')
            state['estimate']+=value*(12 if kind=='string' else 8+2*depth)+8
            require(state['estimate']<=BOUND_LIMITS['document_bytes'],'bounded reconstruction allocation')
            if kind=='string':
                chunks=[];length=0
                while length<value:
                    try:tag,part=next(stream)
                    except StopIteration:raise ValueError('missing string fragment')
                    require(tag=='fragment' and type(part) is str and 0<len(part)<=32 and length+len(part)<=value,'ordered string fragment')
                    require(not any(0xd800<=ord(char)<=0xdfff for char in part),'bounded UTF-8 string fragment')
                    chunks.append(part);length+=len(part)
                result=''.join(chunks)
            elif kind=='array':result=[restore(depth+1) for _ in range(value)]
            else:
                result={};previous_key=None
                for _ in range(value):
                    key=restore(depth+1)
                    require(type(key) is str and (previous_key is None or previous_key<key),'ordered unique object keys')
                    previous_key=key;result[key]=restore(depth+1)
        require(state['estimate']<=BOUND_LIMITS['document_bytes'],'bounded reconstruction scalar allocation')
        return result
    result=restore()
    require(next(stream,None) is None,'no extra bounded records')
    raw=bound_bytes(result)
    require(len(raw)==original['size'] and digest(raw)==original['sha256'],'reconstructed exact opaque serialization binding')
    return result


def admit_census_manifest(inventory,read):
    """Read owned producer files or an externally authenticated portable inventory."""
    require(type(inventory) is dict and len(inventory)<=200000,'bounded external member count')
    for name in inventory:bound_name(name)
    def document(prefix,original):
        scoped={}
        for name,row in inventory.items():
            if not name.startswith(prefix):continue
            local=name[len(prefix):]
            if local in (original,original+'.binding.json') or local.casefold().startswith((original+'.pages/').casefold()):
                require(type(row) is dict and set(row)=={'mode','size','sha256'} and
                        type(row['mode']) is int and row['mode']==0o644,'required Census JSON portable mode')
            scoped[local]={key:row[key] for key in ('size','sha256')}
        return admit_bound_document(original+'.binding.json',scoped,lambda name:read(prefix+name))
    root=document('','manifest.json')
    require(type(root) is dict and root.get('schema')==CENSUS_SCHEMA and
            root.get('manifest_representation')==CENSUS_MANIFEST_REPRESENTATION,'Census manifest representation')
    builds=root.get('builds')
    require(type(builds) is list and len(builds)==len(CENSUS_BUILDS) and
            all(type(build) is dict and build.get('id')==id for build,id in zip(builds,CENSUS_BUILDS)),
            'ordered four Census builds')
    for build in builds:
        id=build['id'];descriptor=build.get('closure_census')
        require(type(descriptor) is dict and set(descriptor)=={'binding','original','graph_schema','status'} and
                descriptor['graph_schema']==CENSUS_SCHEMA and descriptor['status'] in CENSUS_STATUSES,
                'closed Census graph descriptor')
        for key,suffix in (('binding','.binding.json'),('original','')):
            identity=descriptor[key];name=id+'/closure-census.json'+suffix
            require(type(identity) is dict and set(identity)=={'name','size','sha256'} and identity['name']==name and
                    type(identity['size']) is int and 0<=identity['size']<=BOUND_LIMITS['document_bytes'] and
                    (key!='binding' or identity['size']<=BOUND_PAGE_BYTES) and type(identity['sha256']) is str and
                    re.fullmatch('[0-9a-f]{64}',identity['sha256']),'canonical Census graph identity')
            require(name in inventory and inventory[name]==dict(mode=0o644,size=identity['size'],sha256=identity['sha256']) and
                    type(inventory[name]['mode']) is int and type(inventory[name]['size']) is int,
                    'external Census graph identity')
    for build in builds:
        id=build['id'];descriptor=build['closure_census']
        graph=document(id+'/','closure-census.json')
        require(type(graph) is dict and graph.get('schema')==descriptor['graph_schema'] and
                graph.get('status')==descriptor['status'],'Census graph schema/status agreement')
        del graph
    return root


def finish_census_documents(out,manifest,variants,receipts):
    receipts=receipts|{'manifest.json':write_bound_document(out/'manifest.json',manifest)}
    failures=[]
    for name in [id+'/closure-census.json' for id in CENSUS_BUILDS]+['manifest.json']:
        receipt=receipts.get(name)
        if type(receipt) is not dict or receipt.get('kind')!='complete':
            failures.append({'document':name,'reason':receipt.get('reason','missing complete receipt') if type(receipt) is dict else 'missing complete receipt'})
    if not failures:
        try:admit_census_manifest(previous.evidence_inventory(out),lambda name:(out/name).read_bytes())
        except (ValueError,OSError,KeyError,IndexError) as error:
            failures.append({'document':'manifest.json','reason':str(error)[:1024]})
    result={'schema':CENSUS_SCHEMA,'variants':variants,'expected_variants':list(CENSUS_BUILDS),
            'admission':'NotAuthorized','compiled_semantics':'UnprovedAwaitingIndependentReview',
            'fixture_contract':{name:sorted(tests) for name,tests in FIXTURE_TESTS.items()},
            'document_completeness':'incomplete' if failures else 'complete','document_failures':failures}
    bound_preflight(result)
    write_json(out/'closure-census-result.json',result)
    census_custody(out)
    require(not failures,'incomplete Census documents; see closure-census-result.json')
    write_json(out/'closure-census-seal.json',{'schema':CENSUS_SCHEMA,'files':previous.evidence_inventory(out)})
    return result


def word(x):
    return struct.unpack('<I',struct.pack('<f',x))[0]


def words(values):
    require(type(values) is list and all(type(v) is int and 0 <= v <= 0xffffffff for v in values),'u32 words')
    return values


def finite(values):
    words(values)
    require(all(math.isfinite(struct.unpack('<f',struct.pack('<I',v))[0]) for v in values),'finite initialized float')
    return values


def operation_corpus():
    return b''.join(struct.pack('<19f',*POINTS[-1],*matrix) for matrix in (IDENTITY,PROJECTIVE))


def corpus_words(raw):
    require(raw==operation_corpus(),'exact post-build two-case 152-byte corpus')
    return list(struct.unpack('<38I',raw))


def admit_operation(row,kind,owner,expected_input):
    common={'stage','kind','owner','input','output','samples','sites','base'}
    require(set(row)==common|({'target'} if kind=='DllCall' else {'values','destination'}),'closed operation record')
    require(row['stage']=='operation' and row['kind']==kind and row['owner']==owner and
            all(type(v) is int for v in row['owner']),'actual operation owner/order')
    require(len(finite(row['input']))==19 and row['input']==expected_input,'runtime operation input words')
    require(len(finite(row['output']))==3,'operation output words')
    require(type(row['samples']) is list and len(row['samples'])==2,'operation samples')
    row['fp']=[snapshot(v,kind,'operation-'+str(i),case=str(owner)) for i,v in enumerate(row['samples'])]
    require(type(row['base']) is int and 0<row['base']<2**64,'runtime module base')
    sites=row['sites'];require(type(sites) is list and len(sites)==(2 if kind=='DllCall' else 5) and
            all(type(v) is int and (v==0 or row['base']<v<2**64) for v in sites),'runtime code sites')
    required=range(2) if kind=='DllCall' else range(5) if kind=='RustTable' else (0,2)
    require(all(sites[i] for i in required),'required actual code sites')
    if kind=='DllCall':require(type(row['target']) is int and 0<row['target']<2**64,'actual DLL call target')
    else:
        require(len(finite(row['values']))==3 and len(finite(row['destination']))==3,'operation intermediate/destination words')
        if owner[0]==2:require(row['destination']==row['output'],'actual merge return/destination agreement')
        else:require(row['destination']==[0,0,0],'no direct merge destination')
        if kind=='RustEndpoint':require(row['values']==[0,0,0],'uninstrumented endpoint has no observed intermediates')
    return row


WITNESS_ROLES = ('RawCorpusThroughTableReturn', 'RawCorpusThroughHardwareReturn', 'RawFixtureThroughSelectedMeshReturn')
WITNESS_FIELDS = (('operation',176,8),('raw',1024,1),('length',8,8),('pointer',8,8),
                  ('ordinal',8,8),('sink',8,8),('sites',24,8),('handoff',24,8),
                  ('handoff_sites',16,8),('handoff_ordinal',8,8),('handoff_kind',4,4),
                  ('lineage',1280,8),('count',8,8),('returned',48,8),('caller',16,8))

def witness_layout():
    offsets=[];end=0;alignment=max(field[2] for field in WITNESS_FIELDS)
    for name,size,align in WITNESS_FIELDS:
        offset=(end+align-1)//align*align;offsets.append(offset);end=offset+size
    size=(end+alignment-1)//alignment*alignment
    return {'target':'windows-x86_64-repr-c-v1','facts':[size,alignment,8,8,176,8,*offsets]}


def witness_range(pointer,size,alignment):
    require(type(pointer) is int and 0<pointer<2**64 and type(size) is int and
            0<size<2**64 and pointer+size<2**64,'nonoverflowing witness address range')
    require(pointer%alignment==0 and pointer+size<=2**47,'canonical Windows x64 user witness range/alignment')
    return pointer,pointer+size

def admit_witness(row, operation, raw, role, ordinal, pointer):
    require(set(row)=={'stage','schema','layout','role','owner','ordinal','handoff','handoff_sites','handoff_ordinal','handoff_kind','received','received_ordinal','bytes','sites','base'},'closed versioned witness record')
    require(row['stage']=='witness' and type(row['schema']) is int and row['schema']==2 and
            row['role']==role and role in WITNESS_ROLES,'versioned consumed witness role')
    layout=row['layout'];expected=witness_layout()
    require(type(layout) is dict and set(layout)=={'target','facts'} and type(layout['facts']) is list and
            all(type(v) is int for v in layout['facts']) and layout==expected,'authenticated full Witness repr(C) layout')
    require(type(row['ordinal']) is int and row['ordinal']==ordinal and type(row['received_ordinal']) is int and
            row['received_ordinal']==ordinal and type(row['handoff_ordinal']) is int and row['handoff_ordinal']==ordinal and
            type(row['handoff_kind']) is int and row['handoff_kind']==WITNESS_ROLES.index(role) and row['owner']==operation['owner'] and
            all(type(v) is int for v in row['owner']),'witness owner/ordinal linkage')
    for field in ('handoff','received'):
        require(type(row[field]) is list and len(row[field])==3 and all(type(v) is int and 0<v<2**64 for v in row[field]),'actual raw-input and fixed-sink addresses')
    require(0<len(raw)<=1024 and row['handoff']==row['received'] and row['handoff'][:2]==[pointer,len(raw)],'actual raw-input handoff/sink identity')
    input_start,input_end=witness_range(pointer,len(raw),1)
    sink_start,sink_end=witness_range(row['received'][2],layout['facts'][0],layout['facts'][1])
    require(row['bytes']==list(raw) and all(type(v) is int for v in row['bytes']),'actual witness consumed raw bytes')
    require(type(row['base']) is int and row['base']==operation['base'] and type(row['sites']) is list and
            len(row['sites'])==3 and all(type(v) is int and row['base']<v<2**64 for v in row['sites']),'entry/materialization/fixed-sink runtime sites')
    require(type(row['handoff_sites']) is list and len(row['handoff_sites'])==2 and
            all(type(v) is int and row['base']<v<2**64 for v in row['handoff_sites']),'actual raw-input caller handoff sites')
    require(input_end<=sink_start or sink_end<=input_start,'raw input and full Witness sink do not alias')
    return dict(row,raw_sha256=digest(raw),compiled_dataflow='UnprovedAwaitingIndependentReview')


def inputs(read):
    floor=read(FLOOR)
    require(len(floor)==451 and digest(floor)==FLOOR_SHA,'fixed floor bytes')
    result=[]
    for id,path,matrix in CASES:
        original=read(path); raw=original;prefix=b'';suffix=b''
        if matrix is not None:
            text=','.join(str(v) for v in MATRICES[matrix])
            prefix=('\nFrame Diagnostic {\nFrameTransformMatrix {\n'+text+';;\n}\n').encode()
            suffix=b'\n}\n'
            raw=original[:16]+prefix+original[16:]+suffix
            require(raw[:16]+raw[16+len(prefix):-len(suffix)]==original,'wrapper inverse')
        result.append({'id':id,'source':path,'matrix':matrix,'sha256':digest(raw),'size':len(raw),
                       'original_sha256':digest(original),'prefix':prefix.hex(),'suffix':suffix.hex(),'bytes':raw})
    return result


def input_manifest(rows):
    return [{k:v for k,v in row.items() if k!='bytes'} for row in rows]


def insert(raw,anchor,addition):
    require(raw.count(anchor)==1,'unique insertion anchor '+repr(anchor))
    offset=raw.index(anchor)+len(anchor)
    generated=raw[:offset]+addition+raw[offset:]
    patch={'offset':offset,'anchor_hex':anchor.hex(),'original_sha256':digest(raw),
           'generated_sha256':digest(generated),'inserted_hex':addition.hex(),'original_hex':raw.hex()}
    require(inverse(generated,patch)==raw,'complete insertion inverse')
    return generated,patch


def inverse(raw,patch):
    require(digest(raw)==patch['generated_sha256'],'generated inverse binding')
    offset=patch['offset']; addition=bytes.fromhex(patch['inserted_hex'])
    require(raw[offset:offset+len(addition)]==addition,'inverse bytes')
    result=raw[:offset]+raw[offset+len(addition):]
    require(result.hex()==patch['original_hex'] and digest(result)==patch['original_sha256'],'original inverse identity')
    return result


def generated(read,observed,input_root,runtime_path=None,census=False):
    input_root=PureWindowsPath(str(input_root))
    runtime_path=PureWindowsPath(str(runtime_path or input_root/'operations.bin'))
    patches={};result={}
    def add(path,anchor,text):
        raw=result.get(path,read(path))
        raw,patch=insert(raw,anchor,text)
        original=read(path)
        require(original.count(anchor)==1,'unique original physical anchor')
        patch.update(original_offset=original.index(anchor)+len(anchor),base_sha256=digest(original))
        result[path]=raw;patches.setdefault(path,[]).append(patch)
    add('CMakeLists.txt',read('CMakeLists.txt'),b'''
add_executable(floor_profile native.cpp)
target_include_directories(floor_profile PRIVATE ${CMAKE_CURRENT_SOURCE_DIR})
target_link_libraries(floor_profile PRIVATE mikudancestudio_core MMEffect dsound bcrypt)
target_compile_options(mikudancestudio_core PRIVATE @OPT@)
target_compile_options(floor_profile PRIVATE @OPT@)
target_link_options(floor_profile PRIVATE /MAP)
''')
    if observed:
        add(ACCESSORY,b'#include "mikudancestudio/ported_funcs.hpp"',b'\n#include "../../native_observer.hpp"')
        add(ACCESSORY,b'    TraceAccessoryLoadStage("mesh-loaded", mesh);',b'\n    ::FloorProfileRaw(mesh);')
        add(MESH,b'    let nodes = xfile::parse(data)?;',b'\n    #[cfg(mds_floor_profile)] floor_profile::parsed(&nodes);')
        anchor=b'        return Err(Error::NoMesh);\n    }\n'
        add(MESH,anchor,b'    #[cfg(mds_floor_profile)] floor_profile::premerge(&containers);\n')
        add(MESH,b'    if single {\n        mesh.attribute_table = attribute_table(&mesh.indices, &mesh.face_material);\n    }\n',b'    #[cfg(mds_floor_profile)] floor_profile::merged(&mesh);\n')
        add(MESH,b'fn transform_coord(p: [f32; 3], m: &Mat4) -> [f32; 3] {',b'\n    #[cfg(mds_floor_profile)] floor_profile::begin_operation(p, m);')
        add(MESH,b'    let r = (e + e) - w * (e * e);',b'\n    #[cfg(mds_floor_profile)] floor_profile::intermediates(w, e, r);\n    let output =')
        add(MESH,b'        (((x * m[2] + y * m[6]) + z * m[10]) + m[14]) * r,\n    ]',b';\n    #[cfg(mds_floor_profile)] floor_profile::finish_operation(output);\n    output')
        add(MESH,b'    for c in containers {',b'\n        #[cfg(mds_floor_profile)] floor_profile::merge_container();')
        add(MESH,b'        for v in &c.vertices {',b'\n            #[cfg(mds_floor_profile)] floor_profile::merge_source(&mesh.vertices, v, &c.transform);')
        add(MESH,b'                texcoord: v.texcoord,\n            });',b'\n            #[cfg(mds_floor_profile)] floor_profile::merge_destination(&mesh.vertices);')
    observer=(HERE/'observer.rs').read_text()
    if census:observer=observer.replace('@CENSUS@','true')
    else:
        observer=observer.replace(' && !(@CENSUS@ && name == b"memset\\0")','')
        observer=observer.replace('(if @CENSUS@ { 16 * 1024 * 1024 } else { 512 * 1024 })','512 * 1024')
    require('@CENSUS@' not in observer,'closed diagnostic collector template')
    observer=observer.replace('@CASES@',','.join('('+json.dumps(id)+',include_bytes!('+json.dumps(str(input_root/(id+'.x')))+'))' for id,_,_ in CASES))
    observer=observer.replace('@MATRICES@',repr(MATRICES)).replace('@POINTS@',repr(POINTS))
    observer=observer.replace('@RUNTIME@',json.dumps(str(runtime_path))).replace('@MERGE_INPUT@',json.dumps(str(input_root/'floor-identity.x'))).replace('@OBSERVED@',str(observed).lower())
    add(MESH,read(MESH)[-40:],b'\n#[cfg(mds_floor_profile)]\nmod floor_profile {\n'+observer.encode()+b'\n}\n')
    cpp=(HERE/'native.cpp.in').read_text()
    cpp=cpp.replace('@IDS@',','.join(json.dumps(id) for id,_,_ in CASES))
    cpp=cpp.replace('@FILES@',','.join('L'+json.dumps(str(input_root/(id+'.x'))) for id,_,_ in CASES))
    cpp=cpp.replace('@RUNTIME@','L'+json.dumps(str(runtime_path)))
    for key,value in [('@MATRICES@',MATRICES),('@POINTS@',POINTS)]:
        cpp=cpp.replace(key,repr(value).replace('[','{').replace(']','}'))
    result['native.cpp']=cpp.encode();result['native_observer.hpp']=(HERE/'native_observer.hpp').read_bytes()
    return result,patches


def material_count(value,empty=False):
    require(type(value) is int and (0 if empty else 1) <= value <= 10000,'material count')
    return value


def snapshot(raw, language, stage, case=None, operation=None, matrix=None, point=None):
    require(type(raw) is int and 0 <= raw <= 0xffff,'strict MXCSR sample')
    return {'site':{'language':language,'stage':stage,'case':case,'operation':operation,'matrix':matrix,'point':point},
            'raw':raw,'controls':raw & 0xffc0,'sticky_flags':raw & 63}


def qualify_fp(left,right):
    a=[v['controls'] for v in left];b=[v['controls'] for v in right]
    status=('ObservedControlMismatch' if a!=b else
            'SampledDefaultControlsAgree' if all(v==0x1f80 for v in a+b) else 'ObservedNondefaultControls')
    return {'sampled_controls':status,'left':left,'right':right,'operation_environment':'Unproved'}


def mesh(row,native=False,domain=True):
    require(not domain or 'material_count' in row,'required geometry material domain')
    require(type(row['positions']) is list and 0<len(row['positions'])<=1000000,'position count')
    for position in row['positions']: require(len(finite(position))==3,'position words')
    indices=words(row['indices']);attrs=words(row['attributes'])
    require(indices and len(indices)%3==0 and len(attrs)*3==len(indices) and all(i<len(row['positions']) for i in indices),'index/count/bounds')
    if 'material_count' in row:
        count=material_count(row['material_count'],row.get('stage')=='premerge');require(all(i<max(count,1) for i in attrs),'material bounds')
    if 'table' in row:
        require(type(row['table']) is list,'attribute table')
        covered=[]
        for t in row['table']:
            require(len(words(t))==5,'attribute range words');id,start,count,vs,vc=t
            require('material_count' not in row or id<row['material_count'],'attribute table material domain')
            require(count>0 and start+count<=len(attrs) and vs+vc<=len(row['positions']),'attribute range bounds')
            require(attrs[start:start+count]==[id]*count and all(vs<=i<vs+vc for i in indices[start*3:(start+count)*3]),'attribute range binding')
            covered.extend(range(start,start+count))
        require(not row['table'] or sorted(covered)==list(range(len(attrs))),'attribute table coverage')
    if native:
        n,f,stride,offset,vb,ib,width=words(row['bounds'])
        require(n==len(row['positions']) and f*3==len(indices) and 0<stride<=256 and offset+12<=stride and vb==n*stride and width in (2,4) and ib==f*3*width,'actual declaration/lock buffer bounds')
        require(row['initialized']==['position'] and row['unknown']==['uv','padding','other-declaration-channels'],'unknown initialization channel')
    return {k:row[k] for k in ('positions','indices','attributes','table','material_count') if k in row}


def parse(raw,language,observed):
    text=raw.decode('utf-8');require('SKIP' not in text,'unsupported is not execution')
    lines=[line[3:] for line in text.splitlines() if line.startswith('FP ')]
    rows=[load_json(line) for line in lines]
    require(rows and rows[0]=={'stage':'begin','language':language} and rows[-1]=={'stage':'end','status':0},'normal complete stream terminal')
    at=1
    def take(stage):
        nonlocal at
        require(at<len(rows)-1 and rows[at].get('stage')==stage,'ordered/missing stage '+stage)
        row=rows[at];at+=1;return row
    def fp(point):
        row=take('fp');require(row['point']==point and row['case']==current_case,'FP source site');return snapshot(row['mxcsr'],language,point,current_case)
    def hr(name):
        row=take('hr');require(row['operation']==name and type(row['value']) is int and 0<=row['value']<0x80000000,'missing/failed HRESULT '+name)
    def native_mesh(stage):
        for name in ('GetDeclaration','GetVertexBuffer','VertexBufferGetDesc','GetIndexBuffer','IndexBufferGetDesc','LockVertexBuffer','UnlockVertexBuffer','LockIndexBuffer','UnlockIndexBuffer','LockAttributeBuffer','UnlockAttributeBuffer','GetAttributeTableSize'):hr(name)
        if rows[at].get('stage')=='hr':hr('GetAttributeTable')
        row=take(stage);mesh(row,True,False)
        require((row['table']!=[])==(rows[at-2].get('operation')=='GetAttributeTable'),'attribute table HRESULT binding')
        return row
    result={'cases':{},'direct':[],'fp':[]}
    current_case=None
    if language=='native':
        cpu=take('cpu');require(len(words(cpu['vendor']))==3 and len(words(cpu['brand']))==12 and len(words(cpu['features']))==3 and len(words([cpu['identity']]))==1,'closed CPU facts')
        result['cpu']=cpu;result['fp'].append(fp('device-before'));hr('CreateDevice');result['fp'].append(fp('device-after'))
        dll=take('dll');require(re.fullmatch('[0-9a-f]{64}',dll['sha256']) and type(dll['size']) is int and dll['size']>0 and len(words(dll['rvas']))==3 and type(dll['base']) is int and dll['base']>0 and dll['import_target']==dll['base']+dll['rvas'][0],'DLL/import/direct binding');result['dll']=dll
    for id,_,_ in CASES:
        case=take('case');require(case['id']==id,'case identity/order');item={};current_case=id
        if language=='native':
            item['fp']=[fp('independent-before')];hr('D3DXLoadMeshFromXW');item['fp'].append(fp('independent-after'))
            item['raw']=native_mesh('independent-raw')
            mats=take('independent-material-raw');item['raw']['material_count']=material_count(mats['material_count']);mesh(item['raw'])
            item['fp'].append(fp('loader-before'))
            if observed:
                item['fp'].append(fp('production-raw-before'));item['production_raw']=native_mesh('production-raw');item['fp'].append(fp('production-raw-after'))
            item['fp'].append(fp('loader-after'));require(take('loader')=={'stage':'loader','success':True},'production loader succeeded')
            item['before']=native_mesh('before-observation')
            if observed:item['observation']=native_mesh('observation')
            item['final']=native_mesh('final-adjusted');mats=take('final-material-adjusted');count=material_count(mats['material_count'])
            for stage in ('before','observation','final','production_raw'):
                if stage in item:item[stage]['material_count']=count;mesh(item[stage])
            require(mesh(item['before'])==mesh(item['final']) and (not observed or mesh(item['observation'])==mesh(item['final'])),'native extra observation interference')
        else:
            item['fp']=[snapshot(case['mxcsr'],language,'case',id)]
            if observed:
                ast=[]
                while rows[at].get('stage') in ('parsed','reference'):
                    node=rows[at];at+=1
                    require(type(node['path']) is list and node['path'] and all(type(v) is int and v>=0 for v in node['path']),'ordered AST path')
                    require(node['path'] not in [n['path'] for n in ast],'duplicate AST path')
                    if node['stage']=='parsed':
                        require(type(node['kind']) is str and type(node['values']) is list,'actual AST node')
                        for value in node['values']:
                            require(type(value) is list and len(value)==2 and value[0] in ('int','float','bytes'),'AST scalar tag')
                            if value[0]=='float':finite([value[1]])
                            elif value[0]=='int':require(type(value[1]) is int,'AST integer')
                            else:require(type(value[1]) is list and all(type(v) is int and 0<=v<=255 for v in value[1]),'AST bytes')
                    ast.append(node)
                require(ast and any(n.get('kind')=='Mesh' for n in ast) and [n['path'] for n in ast]==sorted(n['path'] for n in ast),'parsed Mesh coverage/order');take('parsed-end');item['parsed']=ast
                containers=[]
                while rows[at].get('stage')=='premerge':
                    row=take('premerge');require(row['ordinal']==len(containers) and len(finite(row['matrix']))==16,'ordered applied matrices');mesh(row);containers.append(row)
                require(containers,'container coverage');take('premerge-end');item['premerge']=containers
                merged=take('merged-raw');mesh(merged);item['merged']=merged
            item['final']=take('final-adjusted');require(item['final']['id']==id,'final FP case site');mesh(item['final']);item['fp'].append(snapshot(item['final']['mxcsr'],language,'final-adjusted',id))
        result['cases'][id]=item
    for mi in range(3):
        for pi in range(5):
            for operation in (('TransformCoord','Transform') if language=='native' else ('TransformCoord',)):
                row=take('direct');require(row['operation']==operation and type(row['matrix']) is int and row['matrix']==mi and type(row['point']) is int and row['point']==pi,'direct operation/input/matrix identity')
                require(len(finite(row['words']))==(4 if operation=='Transform' else 3),'direct operation output width')
                row['fp']=[snapshot(row[k],language,k,operation=operation,matrix=mi,point=pi) for k in ('sample_a','sample_b')];result['direct'].append(row)
    if language=='rust' and observed:result['runtime_imports']=[take('runtime-imports')]
    runtime_read=take('runtime-read');words(runtime_read['words'])
    require(set(runtime_read)==({'stage','words','pointer'} if language=='rust' else {'stage','words'}) and runtime_read['words']==corpus_words(operation_corpus()),'actual runtime corpus read')
    result['operations']=[]
    domain=corpus_words(operation_corpus())
    for i in range(2):
        for kind in (('DllCall',) if language=='native' else (('RustTable' if observed else 'RustEndpoint'),'HardwareSeedWithFrozenRefinement')):
            boundary=take('witness') if language=='rust' else None
            row=admit_operation(take('operation'),kind,[1,i,0,0],domain[i*19:(i+1)*19])
            if boundary is not None:row['witness']=admit_witness(boundary,row,operation_corpus(),WITNESS_ROLES[0 if kind in ('RustTable','RustEndpoint') else 1],i,runtime_read['pointer'])
            if kind=='DllCall':require(row['target']==result['dll']['base']+result['dll']['rvas'][1],'wrapper actual DLL target')
            result['operations'].append(row)
    if language=='rust':
        read=take('merge-read');raw=inputs(lambda p:(ROOT/p).read_bytes())[1]['bytes']
        require(set(read)=={'stage','bytes','pointer'} and read['bytes']==list(raw),'same retained fixture genuinely read at runtime')
        expected=list(map(word,POINTS[0]+IDENTITY)) if observed else [0]*19
        if observed:result['merge_lineage']=take('merge-lineage');admit_lineage(result['merge_lineage'])
        boundary=take('witness')
        row=admit_operation(take('operation'),'RustTable' if observed else 'RustEndpoint',[2,0,0,0],expected)
        row['witness']=admit_witness(boundary,row,raw,WITNESS_ROLES[2],0,read['pointer'])
        result['operations'].append(row)
        if observed:result['runtime_imports'].append(take('runtime-imports'))
    require(at==len(rows)-1,'extra/unknown records')
    if language=='native':
        q,t=result['direct'][-2:];require(q['words']!=t['words'][:3] and t['words'][3]==word(3.),'nonunit-w distinguishes operations')
    return result


def admit_lineage(row):
    require(set(row)=={'stage','caller','rows','returned'} and row['stage']=='merge-lineage','closed merge pointer lineage')
    require(type(row['caller']) is list and len(row['caller'])==2 and all(type(v) is int and 0<v<2**64 for v in row['caller']),'merge opening/closing caller sites')
    rows=row['rows'];returned=row['returned']
    require(type(rows) is list and 0<len(rows)<=16 and type(returned) is list and len(returned)==6,'bounded merge pointer records')
    require(all(type(v) is int and 0<=v<2**64 for a in rows+[returned] for v in a),'strict merge pointer fields')
    previous=None
    for i,a in enumerate(rows):
        require(len(a)==10 and a[1]==i and a[6]==i+1 and a[2]>=a[1] and a[7]>=a[6] and
                a[3]>0 and a[4]>0 and a[5]>0 and 0<a[8]<=1024 and a[9]>0,'actual push source/storage bounds')
        if previous:require(a[:3]==previous[5:8] and a[8]==previous[8],'continuous Vec storage/growth lineage')
        previous=a
    require(returned[:3]==rows[-1][5:8] and returned[3]==returned[0]+returned[5] and returned[5]+12<=rows[0][8] and returned[4]>0,
            'returned mesh selected element is actual Vec storage')
    return row


def semantic(a,b):
    return {'classification':'Equal' if a==b else 'SemanticDifference','before':a,'after':b}


def operation_assessment(native,rust):
    table_source=(ROOT/'rust/crates/mds-math/src/estimate_table.rs').read_text()
    match=re.search(r'const RCP: \[u32; 2048\] = \[(.*?)\];',table_source,re.S)
    require(match is not None,'frozen RCP table source')
    table=[int(v,16) for v in re.findall(r'0x[0-9a-f]{8}',match[1])]
    require(len(table)==2048,'frozen RCP entries')
    def f(v):return struct.unpack('<f',struct.pack('<I',v))[0]
    def rnd(v):
        try:return f(word(v))
        except OverflowError:return math.copysign(math.inf,v)
    def oracle(row,seed=None):
        p=list(map(f,row['input'][:3]));m=list(map(f,row['input'][3:]))
        w=rnd(rnd(rnd(p[0]*m[3])+rnd(p[1]*m[7]))+rnd(p[2]*m[11]));w=rnd(w+m[15])
        wb=word(w);exp=wb>>23 & 255
        require(w in (1.,3.) and 0<exp<253,'bounded Identity/W3 oracle domain')
        e=f((253-exp)<<23 | table[(wb>>12)&2047]&0x7fffff) if seed is None else f(seed)
        square=rnd(e*e);scaled=rnd(w*square);double=rnd(e+e);r=rnd(double-scaled)
        output=[]
        for i in range(3):
            n=rnd(rnd(rnd(p[0]*m[i])+rnd(p[1]*m[i+4]))+rnd(p[2]*m[i+8]));n=rnd(n+m[i+12])
            output.append(word(rnd(n*r)))
        return {'values':[wb,word(e),word(r)],'output':output,
                'refinement_derived_binary32':[word(square),word(scaled),word(double)],
                'origin':'DerivedDefaultBinary32NotInstructionReconstruction'}
    observations=[]
    for row in rust['operations']:
        if row['kind']=='RustEndpoint':continue
        item={'kind':row['kind'],'owner':row['owner'],'observed':row,
              'compiled_dataflow':'UnprovedAwaitingIndependentReview','operation_environment':'Unproved',
              'instruction_reconstructed_values':'UnprovedAwaitingIndependentReview'}
        if all(v['controls']==0x1f80 for v in row['fp']):
            derived=oracle(row,row['values'][1] if row['kind']=='HardwareSeedWithFrozenRefinement' else None)
            item['numerical_oracle']={'domain':'DefaultSampledControlsOnly','derived':derived,
                'comparison':semantic({k:derived[k] for k in ('values','output')},{k:row[k] for k in ('values','output')})}
        else:item['numerical_oracle']={'domain':'UnprovedNondefaultControls'}
        observations.append(item)
    relations=[]
    for i in range(2):
        table,hardware=rust['operations'][i*2:i*2+2];dll=native['operations'][i]
        relations.append({'owner':[1,i,0,0],'table_vs_hardware_seed':semantic(table['values'][1],hardware['values'][1]),
                          'table_vs_dll_output':semantic(table['output'],dll['output']),
                          'hardware_vs_dll_output':semantic(hardware['output'],dll['output']),
                          'dll_recipe':'HeldUnproved','cause_status':'Held'})
    merge=rust['operations'][-1]
    return {'state':'CapturedAwaitingIndependentCompiledReview','proof_status':'UnprovedAwaitingIndependentReview',
            'observations':observations,'dll_observations':native['operations'],'relations':relations,
            'runtime_direct_vs_merge':{'classification':'NotComparable','reason':'DifferentPointAndOwnerDomains'},
            'merge_vs_retained_floor':semantic(merge['output'],rust['cases']['floor-identity']['merged']['positions'][0]),
            'dll_internal_closure':'HeldOptional','arithmetic_adoption':'NotAuthorized'}


def classify(native,rust):
    findings=[];differences=[];relations=[];qualifications=[]
    def held(id,name,qualification):
        findings.append({'case':id,'finding':name,'cause_status':'Held',
                         'reason':'OperationEnvironmentUnproved','fp_qualification':qualification})
    for id,_,_ in CASES:
        n,r=native['cases'][id],rust['cases'][id]
        qualification=qualify_fp([v for v in n['fp'] if v['site']['stage'] in ('loader-before','loader-after')],r['fp'])
        qualifications.append({'case':id,**qualification})
        for stage,a,b in [('production-raw/merged-raw',mesh(n['production_raw']),mesh(r['merged'])),('final-adjusted',mesh(n['final']),mesh(r['final']))]:
            if a!=b:differences.append({'case':id,'stage':stage,**semantic(a,b)})
        parsed=[]
        for node in r['parsed']:
            if node.get('kind')=='Mesh':
                values=node['values'];require(values and values[0][0]=='int','AST Mesh vertex count')
                count=values[0][1];require(0<count<=1000000 and len(values)>=1+3*count,'AST Mesh position count')
                for i in range(count):
                    parsed.append([v[1] if v[0]=='float' else word(float(v[1])) for v in values[1+3*i:4+3*i]])
        pre=[p for row in r['premerge'] for p in row['positions']]
        if parsed==pre and pre!=r['merged']['positions']:findings.append({'case':id,'finding':'ChangeAfterParsingAtMerge','qualification':'ordered positions; material-driven splits can change count on other inputs'})
        if mesh(n['production_raw'])!=mesh(n['final']):findings.append({'case':id,'finding':'ProductionRawVersusFinalPostprocessingDifference'})
        containers=r['premerge']
        reason='OrderedPremergePointsOrMatricesDoNotMatchDirectInputs'
        if len(containers)==1 and containers[0]['positions']==[list(map(word,p)) for p in POINTS[:4]]:
            matches=[mi for mi,m in enumerate(MATRICES) if containers[0]['matrix']==list(map(word,m))]
            if len(matches)==1 and len(r['merged']['positions'])==4:
                direct=[row['words'] for row in rust['direct'] if row['matrix']==matches[0] and row['point']<4]
                relations.append({'case':id,'relation':'RustDirectVersusMerged','matrix':matches[0],**semantic(direct,r['merged']['positions'])})
                continue
            reason='AppliedMatrixHasNoUniqueDirectCorrespondenceOrMergedCountDiffers'
        relations.append({'case':id,'relation':'RustDirectVersusMerged','classification':'NotComparable','reason':reason})
    ncoords=[r for r in native['direct'] if r['operation']=='TransformCoord']
    for n,r in zip(ncoords,rust['direct']):
        qualification=qualify_fp(n['fp'],r['fp'])
        qualifications.append({'matrix':n['matrix'],'point':n['point'],'operation':'TransformCoord',**qualification})
        if n['words']!=r['words']:differences.append({'stage':'direct-TransformCoord','matrix':n['matrix'],'point':n['point'],**semantic(n['words'],r['words'])})
    for id,_,mi in CASES[:3]:
        matrix=0 if mi is None else mi
        direct_rows=[row for row in ncoords if row['matrix']==matrix and row['point']<4]
        direct=[row['words'] for row in direct_rows]
        n=native['cases'][id];r=rust['cases'][id]
        q=qualify_fp([v for row in direct_rows for v in row['fp']], [v for v in n['fp'] if v['site']['stage'] in ('loader-before','loader-after')]*len(direct_rows))
        if direct!=n['production_raw']['positions']:
            held(id,'DirectCoordVersusProductionRawSupportsDifferentPaths',q)
        pre=[p for container in r['premerge'] for p in container['positions']]
        if matrix==0 and direct==n['production_raw']['positions']==pre and pre!=r['merged']['positions']:
            held(id,'CurrentNativeVersusFixedRustArithmeticDifference',qualify_fp([v for v in n['fp'] if v['site']['stage'] in ('loader-before','loader-after')],r['fp']))
    if native['cases']['floor-top']['production_raw']['positions']!=native['cases']['floor-identity']['production_raw']['positions']:
        findings.append({'finding':'TopVersusIdentityFrameInputTopologyDependence','qualification':'does not isolate Frame from explicit matrix'})
    return {'state':'CompleteSameHostDiagnostic','differences':differences,'findings':findings,
            'operation_diagnostic':operation_assessment(native,rust),
            'output_relations':relations,'causal_qualification':qualifications,
            'fp_states':{'native':native['fp']+[v for case in native['cases'].values() for v in case['fp']]+[v for row in native['direct'] for v in row['fp']],
                         'rust':[v for case in rust['cases'].values() for v in case['fp']]+[v for row in rust['direct'] for v in row['fp']]},
            'uncertainty':['OperationEnvironmentUnproved','Rust direct compiled output may be constant-folded',
                           'CPU versus DLL cause unproved','D3DX internal instructions unobserved',
                           'one host cannot select universal arithmetic policy','material-value difference unresolved',
                           'native draw/upload, GPU, pixel cause and full app unexecuted']}


def pe_exports(raw):
    require(raw[:2]==b'MZ' and len(raw)>64,'PE image')
    pe=struct.unpack_from('<I',raw,0x3c)[0]
    require(raw[pe:pe+6]==b'PE\0\0d\x86','AMD64 PE')
    count=struct.unpack_from('<H',raw,pe+6)[0];optional=pe+24
    require(struct.unpack_from('<H',raw,optional)[0]==0x20b,'PE32+')
    section=optional+struct.unpack_from('<H',raw,pe+20)[0]
    sections=[struct.unpack_from('<IIII',raw,section+i*40+8) for i in range(count)]
    def offset(rva):
        matches=[ptr+rva-va for size,va,rawsize,ptr in sections if va<=rva<va+rawsize]
        require(len(matches)==1 and matches[0]<len(raw),'PE RVA bounds');return matches[0]
    export=offset(struct.unpack_from('<I',raw,optional+112)[0])
    funcs,names=struct.unpack_from('<II',raw,export+20)
    fr,nr,orr=struct.unpack_from('<III',raw,export+28)
    fo,no,oo=offset(fr),offset(nr),offset(orr);result={}
    for i in range(names):
        nameoffset=offset(struct.unpack_from('<I',raw,no+4*i)[0]);end=raw.index(b'\0',nameoffset)
        name=raw[nameoffset:end].decode('ascii');ordinal=struct.unpack_from('<H',raw,oo+2*i)[0]
        require(ordinal<funcs,'PE export ordinal');result[name]=struct.unpack_from('<I',raw,fo+4*ordinal)[0]
    return result


def pe_code(raw):
    require(len(raw)>=256 and raw[:2]==b'MZ','bounded final PE header')
    pe=struct.unpack_from('<I',raw,60)[0];require(pe+264<=len(raw) and raw[pe:pe+6]==b'PE\0\0d\x86','final AMD64 PE')
    count=struct.unpack_from('<H',raw,pe+6)[0];optional=pe+24;size=struct.unpack_from('<H',raw,pe+20)[0]
    require(0<count<=96 and size>=144 and optional+size+count*40<=len(raw) and struct.unpack_from('<H',raw,optional)[0]==0x20b,'bounded PE32+ sections')
    base=struct.unpack_from('<Q',raw,optional+24)[0];sections=[]
    for i in range(count):
        at=optional+size+i*40;vs,va,rs,offset=struct.unpack_from('<IIII',raw,at+8);flags=struct.unpack_from('<I',raw,at+36)[0]
        require(offset+rs<=len(raw) and va+max(vs,rs)<2**32,'PE physical/virtual section bounds')
        sections.append({'name':raw[at:at+8].rstrip(b'\0').decode('ascii'),'rva':va,'size':rs,'virtual_size':vs,'offset':offset,'flags':flags})
    def region(start,end,executable=False):
        require(type(start) is int and type(end) is int and 0<=start<end<2**32,'strict code range')
        matches=[s for s in sections if s['rva']<=start<end<=s['rva']+s['size'] and (not executable or s['flags']&0x20000000)]
        require(len(matches)==1,'unique physical PE section/range')
        s=matches[0];offset=s['offset']+start-s['rva']
        return {'start_rva':start,'end_rva':end,'section':s['name'],'offset':offset,'bytes':raw[offset:offset+end-start].hex()}
    rva,length=struct.unpack_from('<II',raw,optional+112+3*8)
    require(length%12==0 and length<=12*100000 and bool(rva)==bool(length),'bounded exception directory')
    table=bytes.fromhex(region(rva,rva+length)['bytes']) if length else b'';functions=[]
    for at in range(0,len(table),12):
        first,last,unwind=struct.unpack_from('<III',table,at)
        require(first<last and unwind,'runtime function extent');region(first,last,True);functions.append((first,last))
    require(functions==sorted(set(functions)),'unique sorted runtime function extents')
    return base,sections,functions,region


DISASSEMBLER=PureWindowsPath('C:/Program Files/LLVM/bin/llvm-objdump.exe')


def map_symbols(raw,base,sections):
    text=raw.decode('utf-8-sig')
    preferred=re.findall(r'Preferred load address is\s+([0-9a-fA-F]+)',text)
    require(len(preferred)==1 and int(preferred[0],16)==base,'same-link preferred image base')
    result=[]
    for line in text.splitlines():
        match=re.fullmatch(r'\s*[0-9a-fA-F]{4}:[0-9a-fA-F]{8,16}\s+(\S+)\s+([0-9a-fA-F]{8,16})\s+(.*?)\s*',line)
        if match:
            rva=int(match[2],16)-base
            if any(s['rva']<=rva<s['rva']+s['size'] and s['flags']&0x20000000 for s in sections):
                result.append({'symbol':match[1],'rva':rva,'object':match[3]})
    return result


def range_extent(raw,target,symbols,interior=False,exports=()):
    _,sections,functions,region=pe_code(raw)
    matches=[p for p in functions if p[0]<=target<p[1]]
    if len(matches)==1:return matches[0], 'ExceptionDirectory'
    require(not matches,'unique required runtime function')
    head=region(target,target+6,True)
    if bytes.fromhex(head['bytes'])[:2]==b'\xff\x25':return (target,target+6),'ImportThunkSixBytes'
    if not symbols and exports:
        entries=[entry for entry in exports if entry['rva']==target]
        following=[entry['rva'] for entry in exports if entry['rva']>target]
        require(len(entries)==1 and following,'required CRT export candidate start/next distinct extent')
        region(target,min(following),True)
        return (target,min(following)),'ExportCandidateOnly'
    preceding=sorted({s['rva'] for s in symbols if s['rva']<=target})
    require(preceding and (interior or preceding[-1]==target),'required leaf has same-link start symbol')
    first=preceding[-1]
    following=sorted({s['rva'] for s in symbols if s['rva']>first})
    require(following,'required leaf has candidate upper bound')
    region(first,following[0],True)
    return (first,following[0]),'NextDistinctExecutableSymbolCandidateOnly'


class CensusLimit(ValueError):
    pass


def census_import_request(image,root_image,slot):
    view=image['witness'];before=image.get('pre',{});after=image.get('post',{})
    runtime=before.get('runtime',{})
    if (image.get('root_image_sha256')!=root_image or before.get('slot',{}).get('slot_rva')!=slot or
            any(before.get(k)!=after.get(k) for k in ('slot','runtime','module_sha256','module_size')) or
            before.get('module_sha256')!=view['image_sha256'] or
            type(runtime.get('target_va')) is not int or type(runtime.get('owner_base')) is not int):return None
    target=runtime['target_va']-runtime['owner_base']
    raw=image.get('raw',b'')
    if digest(raw)!=view['image_sha256']:return None
    try:extent,kind=range_extent(raw,target,view['all_same_link_symbols'],False,view.get('export_candidates',()))
    except ValueError:return None
    requests=[request for request in view.get('requests',[]) if
              request.get('role')=='ActualOwnProcessImportTarget' and request.get('resolution')=='Resolved' and
              request.get('image_sha256')==view['image_sha256'] and request.get('target_rva')==target and
              request.get('origin')=={'kind':'RuntimeImport','root_image_sha256':root_image,'slot_rva':slot} and
              (request.get('start_rva'),request.get('end_rva'))==extent and request.get('extent_kind')==kind and
              any((span['start_rva'],span['end_rva'])==(request.get('start_rva'),request.get('end_rva')) for span in view['ranges'])]
    return requests[0] if len(requests)==1 else None


class ClosureCensus:
    def __init__(self):
        self.witnesses=[]
        self.first_ordinary_violation=None
        self.unknowns=[]
        self.started=previous.time.monotonic()

    def register(self,witness):
        if not any(w is witness for w in self.witnesses):self.witnesses.append(witness)

    def check(self):
        ordinary=[w for w in self.witnesses if w.get('census_language')!='native']
        try:
            if any(w['ranges'] for w in ordinary):closure_budget(ordinary)
        except ValueError as error:
            if self.first_ordinary_violation is None:
                self.first_ordinary_violation={'error':str(error),'images':[
                    {'image_sha256':w['image_sha256'],'requests':list(w.get('requests',[])),
                     'ranges':list(w['ranges']),'pending':list(w.get('pending',[])),
                     'decoded':list(w.get('decoded',[]))} for w in self.witnesses if w.get('census_language')!='native']}
        physical={(w['image_sha256'],s['start_rva'],s['end_rva']) for w in self.witnesses for s in w['ranges']}
        sections={(w['image_sha256'],i) for w in self.witnesses for i in range(len(w['sections']))}
        sizes=[b-a for _,a,b in physical]
        values={'ranges':len(physical),'bytes':sum(sizes),'single':max(sizes,default=0),
                'sections':len(sections),'seconds':previous.time.monotonic()-self.started}
        for key,limit in CENSUS_LIMITS.items():
            if values[key]>limit:raise CensusLimit('diagnostic '+key+' ceiling reached')
        if self.first_ordinary_violation is not None:
            self.first_ordinary_violation=json.loads(json.dumps(self.first_ordinary_violation))
        return values

    def summary(self,images):
        nodes={};adjacency={};roots={};import_unknowns=[]
        def key(view,span):return view['image_sha256']+':'+str(span[0])+':'+str(span[1])
        for image in images:
            view=image['witness']
            for span in view['ranges']:
                node=key(view,(span['start_rva'],span['end_rva']));nodes[node]=span;adjacency.setdefault(node,set())
            for request in view.get('requests',[]):
                if request.get('resolution')!='Resolved':continue
                target=key(view,(request['start_rva'],request['end_rva']));origin=request.get('origin',{})
                if request.get('role')=='ActualOwnProcessImportTarget' and census_import_request(image,image.get('root_image_sha256'),origin.get('slot_rva'))!=request:
                    import_unknowns.append({'kind':'RequiredImportOrigin','request':request})
                    continue
                if origin['kind']=='RequiredTarget':
                    adjacency.setdefault(key(view,origin['caller_extent']),set()).add(target)
                else:roots.setdefault(json.dumps({'image':view['image_sha256'],'role':request['role'],'origin':origin},sort_keys=True),set()).add(target)
            for edge in view.get('edges',[]):
                if 'target_image_sha256' not in edge:continue
                callers=[n for n,s in nodes.items() if n.startswith(view['image_sha256']+':') and s['start_rva']<=edge['instruction_rva']<s['end_rva']]
                slot=edge.get('target',{}).get('slot_rva')
                owners=[(image,request) for image in images
                        if image['witness']['image_sha256']==edge['target_image_sha256']
                        for request in [census_import_request(image,view['image_sha256'],slot)] if request is not None]
                if len(owners)!=1 or owners[0][1]!=edge.get('target_import_request'):
                    import_unknowns.append({'kind':'RequiredImportReachability','image_sha256':view['image_sha256'],
                                            'instruction_rva':edge['instruction_rva'],'slot_rva':slot,
                                            'reason':'MissingWrongOrAmbiguousImportOrigin'})
                    continue
                owner,request=owners[0]
                for caller in callers:adjacency[caller].add(key(owner['witness'],(request['start_rva'],request['end_rva'])))
        reachable={}
        for root,seed in roots.items():
            seen=set();pending=list(seed)
            while pending:
                node=pending.pop()
                if node in seen:continue
                seen.add(node);pending.extend(adjacency.get(node,set())-seen)
            reachable[root]=sorted(seen)
        shared={node:[root for root,seen in reachable.items() if node in seen] for node in nodes}
        views=[image['witness'] for image in images]
        unresolved=[edge for view in views for edge in view.get('edges',[]) if edge.get('obligation')=='Unresolved']
        pending=[{'image':view['image_sha256'],'extent':span} for view in views for span in view.get('pending',[])]
        unknowns=self.unknowns+import_unknowns+[request for view in views for request in view.get('requests',[]) if request.get('resolution')!='Resolved']
        unknowns += [data for view in views for data in view.get('data_requests',[]) if data.get('resolution')!='Resolved']
        status='CENSUS_INCOMPLETE_UNRESOLVED' if not nodes or unknowns or unresolved or pending else 'CENSUS_COMPLETE_DIAGNOSTIC_ONLY'
        return {'schema':CENSUS_SCHEMA,'status':status,'admission':'NotAuthorized','limits':CENSUS_LIMITS,
                'first_ordinary_violation':self.first_ordinary_violation,'count_interpretation':'LowerBound' if status!='CENSUS_COMPLETE_DIAGNOSTIC_ONLY' else 'CompleteDiagnosticOnly',
                'physical_unique':len(nodes),'logical_requests':sum(len(v.get('requests',[])) for v in views),
                'range_bytes':sum(s['end_rva']-s['start_rva'] for s in nodes.values()),
                'decoded':sum(len(v.get('decoded',[])) for v in views),'pending':pending,'unresolved_edges':unresolved,
                'unknowns':unknowns,'root_reachability':reachable,'shared_sets':{node:r for node,r in shared.items() if len(r)>1},
                'images':[{k:v for k,v in image.items() if k!='raw'} for image in images]}


def closure_budget(witnesses):
    spans=[s for w in witnesses for s in w['ranges']]
    require(0<len(spans)<=128 and sum(s['end_rva']-s['start_rva'] for s in spans)<=512*1024 and
            all(0<s['end_rva']-s['start_rva']<=128*1024 for s in spans),'small bounded operation code regions')
    require(sum(len(w['sections']) for w in witnesses)<=96,'aggregate required PE section budget')


def request_range(witness,raw,target,role,origin,census=None):
    request={'image_sha256':digest(raw),'target_rva':target,'role':role,'origin':origin,'obligation':'Required'}
    if any(all(previous.get(k)==v for k,v in request.items()) for previous in witness['requests']):return
    try:extent,kind=range_extent(raw,target,witness['all_same_link_symbols'],origin['kind']=='RuntimeSite',witness.get('export_candidates',()))
    except ValueError as error:
        witness['requests'].append(dict(request,resolution='Unresolved',reason=str(error)))
        raise
    request['resolution']='Resolved'
    request['extent_kind']=kind;request['start_rva'],request['end_rva']=extent
    request['extent_source']={'ExceptionDirectory':'pdata','ImportThunkSixBytes':'exact_thunk',
        'NextDistinctExecutableSymbolCandidateOnly':'map_candidate','ExportCandidateOnly':'export_candidate'}[kind]
    witness['requests'].append(request)
    added=not any((s['start_rva'],s['end_rva'])==extent for s in witness['ranges'])
    if added:
        witness['ranges'].append(pe_code(raw)[3](*extent,True))
        witness.setdefault('pending',[]).append(list(extent))
    if census is None:closure_budget([witness])
    else:
        census.register(witness)
        try:census.check()
        except CensusLimit:
            if added:witness['ranges'].pop();witness['pending'].pop()
            request['resolution']='Unresolved';request['reason']='DiagnosticCeilingKnownExtentNotAcquired'
            raise



def code_ranges(raw,rows,map_raw):
    base,sections,functions,region=pe_code(raw);sites=[]
    for row in rows:
        sites.extend(site-row['base'] for site in row['sites'] if site)
    text=map_raw.decode('utf-8-sig');require('Preferred load address is' in text,'same-link map header')
    preferred=re.findall(r'Preferred load address is\s+([0-9a-fA-F]+)',text)
    require(len(preferred)==1 and int(preferred[0],16)==base,'same-link preferred image base')
    symbols=[]
    for line in text.splitlines():
        match=re.fullmatch(r'\s*[0-9a-fA-F]{4}:[0-9a-fA-F]{8,16}\s+(\S+)\s+([0-9a-fA-F]{8,16})\s+(.*?)\s*',line)
        if match and ('floor_profile' in match[1] or 'DllProbe' in match[1] or match[1]=='wmain' or
                      'mds_accessory' in match[1] and any(name in match[1] for name in ('transform_coord','load_x','merge')) or
                      'mds_math' in match[1] and 'rcp_estimate' in match[1]):
            address=int(match[2],16)-base
            if any(first<=address<last for first,last in functions):symbols.append({'symbol':match[1],'rva':address,'object':match[3]})
    require(symbols,'selected same-link symbol mappings')
    selected=set()
    for site in sites+[s['rva'] for s in symbols]:
        matches=[p for p in functions if p[0]<=site<p[1]]
        require(len(matches)==1,'runtime site has one exception-directory function extent')
        selected.add(matches[0])
    require(0<len(selected)<=128 and sum(b-a for a,b in selected)<=512*1024 and all(b-a<=128*1024 for a,b in selected),'small bounded operation code regions')
    return {'image_sha256':digest(raw),'image_size':len(raw),'preferred_base':base,'sections':sections,
            'runtime_sites_rva':sites,'same_link_symbols':symbols,
            'ranges':[region(a,b,True) for a,b in sorted(selected)],
            'compiled_dataflow':'UnprovedAwaitingIndependentReview'}


def required_code_ranges(raw,rows,map_raw,witness=None,census=None):
    base,sections,functions,_=pe_code(raw);symbols=map_symbols(map_raw,base,sections)
    if witness is None:witness={}
    witness.update({'image_sha256':digest(raw),'image_size':len(raw),'preferred_base':base,'sections':sections,
             'all_same_link_symbols':symbols,'requests':[],'ranges':[],'edges':[],'data_requests':[],
             'pending':[],'decoded':[],'semantic_origins':[],
             'compiled_dataflow':'UnprovedAwaitingIndependentReview'})
    if census is not None:census.register(witness)
    for i,row in enumerate(rows):
        boundary=row['witness'];role=boundary['role']
        require(role in WITNESS_ROLES,'consumed semantic operation role')
        extents=[]
        for j,site in enumerate(boundary['sites']):
            target=site-row['base'];matches=[p for p in functions if p[0]<=target<p[1]]
            require(len(matches)==1,'witness site has exact exception-directory boundary')
            extents.append(matches[0])
            request_range(witness,raw,target,role,{'kind':'RuntimeSite','operation':i,'slot':j,'raw_sha256':boundary['raw_sha256'],'sink':boundary['received'][2]},census)
        require(len(set(extents))==1,'entry/materialization/sink share actual witness function')
        expected=('direct_witness','hardware_witness','merge_witness')[WITNESS_ROLES.index(role)]
        owners=[s for s in symbols if s['rva']==extents[0][0] and expected in s['symbol']]
        require(len(owners)==1,'exact same-link witness role owner')
        handoff_extents=[]
        for j,site in enumerate(boundary['handoff_sites']):
            target=site-row['base'];matches=[p for p in functions if p[0]<=target<p[1]]
            require(len(matches)==1,'handoff site has exact exception-directory boundary')
            handoff_extents.append(matches[0])
            request_range(witness,raw,target,'RawInputHandoffThroughFixedSink',{'kind':'RuntimeSite','operation':i,'slot':j,'raw_sha256':boundary['raw_sha256']},census)
        require(len(set(handoff_extents))==1 and handoff_extents[0]!=extents[0],'separate actual handoff/witness function boundaries')
        handoff_owners=[s for s in symbols if s['rva']==handoff_extents[0][0] and 'floor_profile' in s['symbol'] and 'handoff' in s['symbol']]
        require(len(handoff_owners)==1,'exact same-link handoff owner')
        witness['semantic_origins'].append({'operation':i,'role':role,'extent':list(extents[0]),'same_link_owner':owners[0],
            'raw_sha256':boundary['raw_sha256'],'handoff':boundary['handoff'],'received':boundary['received'],'layout':boundary['layout'],
            'ordinal':boundary['ordinal'],'owner':boundary['owner'],'sites':boundary['sites'],
            'handoff_extent':list(handoff_extents[0]),'handoff_owner':handoff_owners[0],'handoff_sites':boundary['handoff_sites']})
        for j,site in enumerate(row['sites']):
            if site:request_range(witness,raw,site-row['base'],'ObservedOperationSite',{'kind':'RuntimeSite','operation':i,'slot':j},census)
    require(witness['ranges'],'required operation roots')
    return witness


COPY_OBLIGATIONS = [
    {'size':176,'role':'OperationReturn','status':'RequiresIndependentCallerRegionAndPathReview'},
    {'size':8192,'role':'OdSeedTable','status':'RequiresIndependentCallerRegionAndPathReview'}]


def complete_closure(images,census=None):
    if census is None:closure_budget([image['witness'] for image in images])
    else:census.check()
    root=images[0]['witness']
    require(root.get('semantic_origins') and root.get('copy_obligations')==COPY_OBLIGATIONS,'required input/sink/return/seed-copy obligations are INCOMPLETE')
    require(sum(d.get('role')=='SeedTable' and d.get('size')==8192 for d in root['data_requests'])==1,'required seed data is INCOMPLETE')
    for origin in root['semantic_origins']:
        calls=[edge for edge in root['edges'] if origin['handoff_extent'][0]<=edge['instruction_rva']<origin['handoff_extent'][1] and
               edge['target']['kind']=='DirectRva' and origin['extent'][0]<=edge['target']['rva']<origin['extent'][1] and edge['text'].startswith('call')]
        require(calls,'actual handoff-to-witness call target is INCOMPLETE')
        origin['actual_call_edges']=calls
    for image in images:
        view=image['witness']
        require(not view.get('pending') and len(view.get('decoded',[]))==len(view['ranges']) and
                {tuple(p) for p in view.get('decoded',[])}=={(s['start_rva'],s['end_rva']) for s in view['ranges']},'pending required code frontier is INCOMPLETE')
        require(all(request.get('resolution')=='Resolved' for request in view['requests']),'unresolved required range is INCOMPLETE')
        require(not any(e['obligation']=='Unresolved' for e in view['edges']),'unresolved required branch/import/dispatch data is INCOMPLETE')
        require(all(e.get('resolution') in ('InRange','Acquired','Return','Trap') and e['obligation']=='Required' for e in view['edges']),'unresolved required edge coverage is INCOMPLETE')
        require(all(d.get('resolution')=='Resolved' for d in view['data_requests']),'unresolved required data is INCOMPLETE')
        view['logical_request_count']=len(view['requests']);view['physical_range_count']=len(view['ranges'])


def follow_required_edge(directory,images,module_index,span,edge,census=None):
    image=images[module_index];view=image['witness'];raw=image['raw'];target=edge['target']
    origin={'kind':'RequiredTarget','instruction_rva':edge['instruction_rva'],
            'caller_extent':[span['start_rva'],span['end_rva']]}
    require(edge['obligation']=='Required','no unsupported edge waiver')
    if target['kind']=='DirectRva':
        if span['start_rva']<=target['rva']<span['end_rva']:edge['resolution']='InRange'
        else:
            request_range(view,raw,target['rva'],'RequiredCallOrBranch',origin,census)
            edge['resolution']='Acquired'
    elif target['kind']=='RipRelativeIatSlot':
        slot=target['slot_rva'];data=pe_code(raw)[3](slot,slot+8)
        request={'role':'RequiredImportOrDispatchSlot','origin':origin,'start_rva':slot,'size':8,'bytes':data['bytes'],'resolution':'Unresolved'}
        view['data_requests'].append(request)
        if (module_index if census is None else 'pre' in image):
            try:
                dispatch,samples=loaded_dispatch_target(directory,image,slot)
                edge['loaded_dispatch_samples']=samples
                request_range(view,raw,dispatch,'RequiredLoadedDispatchTarget',origin,census)
                if census is not None:
                    edge['obligation']='Unresolved';edge['reason']='SampledDispatchIsNotCompleteFiniteTargetSet'
                else:request['resolution']='Resolved';edge['resolution']='Acquired'
            except (ValueError,KeyError) as error:
                edge['obligation']='Unresolved';edge['reason']=str(error)
        else:
            owners=[m for m in images if 'pre' in m and m['pre']['slot']['slot_rva']==slot and
                    (census is None or m.get('root_image_sha256')==view['image_sha256'])]
            if len(owners)!=1:
                edge['obligation']='Unresolved';edge['reason']='MissingRequiredSameProcessImportTarget'
            else:
                if census is not None:
                    imported=census_import_request(owners[0],view['image_sha256'],slot)
                    if imported is None:
                        edge['obligation']='Unresolved';edge['reason']='MissingRequiredSameProcessImportTarget'
                        return
                    edge['target_import_request']=dict(imported)
                edge['target_image_sha256']=owners[0]['witness']['image_sha256']
                if census is not None:
                    edge['obligation']='Unresolved';edge['reason']='SampledDispatchIsNotCompleteFiniteTargetSet'
                else:request['resolution']='Resolved';edge['resolution']='Acquired'
    elif target['kind'] in ('Return','Trap'):edge['resolution']=target['kind']
    else:edge['obligation']='Unresolved'


def instruction_edges(stdout,witness,span):
    disassembly_bytes(stdout,witness,span);result=[];last=None
    for line in stdout.decode('utf-8').splitlines():
        match=re.fullmatch(r'\s*([0-9a-fA-F]+):\s+((?:[0-9a-fA-F]{2}\s+)+)(\S.*)',line)
        if not match:continue
        rva=int(match[1],16)-witness['preferred_base'];raw=bytes.fromhex(match[2]);text=match[3]
        mnemonic=text.split()[0].lower()
        last=(rva,raw,text,mnemonic)
        if mnemonic.startswith(('call','j','loop','ret')):
            edge={'instruction_rva':rva,'bytes':raw.hex(),'text':text,'obligation':'Required'}
            if mnemonic.startswith('ret'):edge['target']={'kind':'Return'}
            elif raw[:2] in (b'\xff\x25',b'\xff\x15') and len(raw)==6:
                slot=rva+6+struct.unpack_from('<i',raw,2)[0]
                require(0<=slot<2**32-8,'signed FF25 slot RVA bounds')
                edge['target']={'kind':'RipRelativeIatSlot','slot_rva':slot}
            else:
                target=re.fullmatch(r'(?:callq?|j[a-z]+|loop[a-z]*)\s+(?:0x)?([0-9a-fA-F]+)(?:\s+<[^>]+>)?',text)
                edge['target']=({'kind':'DirectRva','rva':int(target[1],16)-witness['preferred_base']} if target else {'kind':'Unresolved','reason':'RequiredIndirectOrUnknownBranch'})
            result.append(edge)
        elif mnemonic in ('ud2','int3'):
            result.append({'instruction_rva':rva,'bytes':raw.hex(),'text':text,'obligation':'Required','target':{'kind':'Trap'}})
    if last and not last[3].startswith(('ret','jmp')) and last[3] not in ('ud2','int3'):
        result.append({'instruction_rva':last[0],'bytes':last[1].hex(),'text':'fallthrough after '+last[2],
                       'obligation':'Required','target':{'kind':'DirectRva','rva':span['end_rva']}})
    return result


def pe_directory(raw,index):
    pe=struct.unpack_from('<I',raw,60)[0];optional=pe+24
    require(struct.unpack_from('<I',raw,optional+108)[0]>index,'required PE data directory')
    return struct.unpack_from('<II',raw,optional+112+index*8)


def export_metadata(raw):
    _,sections,_,region=pe_code(raw);rva,size=pe_directory(raw,0)
    require(40<=size<=128*1024,'bounded CRT export directory')
    directory=bytes.fromhex(region(rva,rva+size)['bytes']);functions,names=struct.unpack_from('<II',directory,20)
    require(0<functions<=8192 and names<=8192,'bounded CRT export metadata count')
    fr,nr,orr=struct.unpack_from('<III',directory,28)
    addresses=bytes.fromhex(region(fr,fr+4*functions)['bytes'])
    name_table=bytes.fromhex(region(nr,nr+4*names)['bytes']) if names else b''
    ordinals=bytes.fromhex(region(orr,orr+2*names)['bytes']) if names else b'';aliases={};retained=[]
    for i in range(names):
        at=struct.unpack_from('<I',name_table,i*4)[0];ordinal=struct.unpack_from('<H',ordinals,i*2)[0]
        require(ordinal<functions,'CRT export ordinal bounds');value=bytearray()
        for j in range(512):
            byte=bytes.fromhex(region(at+j,at+j+1)['bytes'])[0]
            if byte==0:break
            value.append(byte)
        else:require(False,'CRT export name termination')
        name=value.decode('ascii');aliases.setdefault(ordinal,[]).append(name)
        retained.append({'rva':at,'bytes':(bytes(value)+b'\0').hex(),'ordinal_index':ordinal})
    candidates={};entries=[]
    for i in range(functions):
        target=struct.unpack_from('<I',addresses,i*4)[0]
        executable=[s for s in sections if s['rva']<=target<s['rva']+s['size'] and s['flags']&0x20000000]
        forwarded=rva<=target<rva+size
        entries.append({'ordinal_index':i,'rva':target,'aliases':aliases.get(i,[]),'forwarded':forwarded,'executable':len(executable)==1})
        if target and not forwarded and len(executable)==1:candidates.setdefault(target,[]).extend(aliases.get(i,[]))
    return {'directory_rva':rva,'directory_bytes':directory.hex(),'function_table_rva':fr,'function_table_bytes':addresses.hex(),
            'name_table_rva':nr,'name_table_bytes':name_table.hex(),'ordinal_table_rva':orr,'ordinal_table_bytes':ordinals.hex(),
            'names':retained,'entries':entries},[{'rva':rva,'aliases':sorted(names)} for rva,names in sorted(candidates.items())]


def import_slots(raw,census=None):
    region=pe_code(raw)[3];rva,size=pe_directory(raw,1)
    require(size and size<=128*1024,'bounded own-image import directory')
    table=bytes.fromhex(region(rva,rva+size)['bytes']);result=[];terminated=False
    def string(at):
        data=bytearray()
        for i in range(512):
            v=bytes.fromhex(region(at+i,at+i+1)['bytes'])[0]
            if v==0:return data.decode('ascii')
            data.append(v)
        require(False,'bounded import name termination')
    for at in range(0,len(table)-19,20):
        descriptor=table[at:at+20]
        if descriptor==bytes(20):terminated=True;break
        names,_,_,dll,iat=struct.unpack('<IIIII',descriptor)
        require(names and iat,'own-image named import metadata')
        dll_name=string(dll)
        for n in range(8192):
            entry=struct.unpack('<Q',bytes.fromhex(region(names+n*8,names+(n+1)*8)['bytes']))[0]
            if not entry:break
            if entry>>63:continue
            name=string(entry+2)
            if name=='memcpy' or census is not None and name=='memset':
                region(iat+n*8,iat+(n+1)*8)
                result.append({'descriptor_rva':rva+at,'dll_rva':dll,'name_rva':entry,
                               'slot_rva':iat+n*8,'declared_dll':dll_name,'imported_symbol':name})
        else:require(False,'bounded import slot termination')
    require(terminated and 0<len(result)<=8,'required own-process copy import slots')
    return result


def relocated_code(raw,span,runtime_base):
    base,_,_,region=pe_code(raw);data=bytearray.fromhex(span['bytes']);delta=runtime_base-base
    rva,size=pe_directory(raw,5)
    if not size:
        require(delta==0,'relocation data required for moved loaded code');return bytes(data)
    require(size<=128*1024,'bounded runtime relocation directory')
    table=bytes.fromhex(region(rva,rva+size)['bytes']);at=0;seen=set()
    while at<len(table):
        require(at+8<=len(table),'relocation block header')
        page,length=struct.unpack_from('<II',table,at)
        require(length>=8 and length%2==0 and at+length<=len(table),'relocation block bounds')
        for pos in range(at+8,at+length,2):
            entry=struct.unpack_from('<H',table,pos)[0];kind=entry>>12;target=page+(entry&4095)
            if not kind:continue
            if target<span['end_rva'] and target+8>span['start_rva']:
                require(kind==10 and span['start_rva']<=target and target+8<=span['end_rva'] and target not in seen,'exact DIR64 loaded code relocation')
                seen.add(target);offset=target-span['start_rva'];value=struct.unpack_from('<Q',data,offset)[0]
                require(0<=value+delta<2**64,'loaded code relocation overflow');struct.pack_into('<Q',data,offset,value+delta)
        at+=length
    return bytes(data)


def loaded_header_binding(raw,headers,owner_base):
    pe_code(raw);pe=struct.unpack_from('<I',raw,60)[0];optional=pe+24;field=optional+24
    count=struct.unpack_from('<H',raw,pe+6)[0];size=struct.unpack_from('<H',raw,pe+20)[0]
    header_size=struct.unpack_from('<I',raw,optional+60)[0]
    require(field+8<=optional+size and optional+size+count*40<=header_size<=len(raw) and
            len(headers)==header_size,'bounded loaded PE headers')
    require(type(owner_base) is int and 0<owner_base<2**64 and
            struct.unpack_from('<Q',headers,field)[0]==owner_base and
            headers[:field]==raw[:field] and headers[field+8:]==raw[field+8:header_size],
            'loaded owner file/PE/header binding')


def runtime_images(directory,parsed,rust_raw,census=None):
    snapshots=parsed['runtime_imports'];require(len(snapshots)==2,'pre/post own-process import snapshots')
    receipt=checked(directory,'rust')[0];slots=import_slots(rust_raw,census);modules=[];by_slot={}
    for phase,snapshot in zip(('pre','post'),snapshots):
        require(set(snapshot)=={'stage','phase','process_id','image_base','image_size','slots'} and
                snapshot['stage']=='runtime-imports' and snapshot['phase']==phase and
                type(snapshot['process_id']) is int and snapshot['process_id']==receipt['pid'],'same executed Rust process import snapshot')
        require(all(row['base']==snapshot['image_base'] for row in parsed['operations']),'own executed-image runtime base')
        pe=struct.unpack_from('<I',rust_raw,60)[0]
        require(snapshot['image_size']==struct.unpack_from('<I',rust_raw,pe+24+56)[0],'own executed-image extent')
        require(len(snapshot['slots'])==len(slots),'complete required import slot snapshots')
        for i,(actual,declared) in enumerate(zip(snapshot['slots'],slots)):
            try:
                require(set(actual)=={'descriptor_rva','dll_rva','name_rva','slot_rva','target_va','owner_base','owner_size','path_utf16','sections'} and
                        all(actual[k]==declared[k] for k in ('descriptor_rva','dll_rva','name_rva','slot_rva')),'actual own-image import descriptor/name/slot')
                require(all(type(actual[k]) is int and 0<actual[k]<2**64 for k in ('target_va','owner_base','owner_size')),'strict loaded target identity')
                require(type(actual['path_utf16']) is list and actual['path_utf16'] and all(type(v) is int and 0<v<65536 for v in actual['path_utf16']),'actual loaded owner path')
                prefix=f'runtime-{phase}-{i}';raw=(directory/(prefix+'-module.bin')).read_bytes();headers=(directory/(prefix+'-headers.bin')).read_bytes()
                require((directory/(prefix+'-iat.bin')).read_bytes()==struct.pack('<Q',actual['target_va']),'own-process actual IAT slot bytes/target')
                base,sections,_,region=pe_code(raw);pe=struct.unpack_from('<I',raw,60)[0]
                image_size=struct.unpack_from('<I',raw,pe+24+56)[0]
                require(actual['owner_size']==image_size,'loaded owner file/PE/header binding')
                loaded_header_binding(raw,headers,actual['owner_base'])
                target=actual['target_va']-actual['owner_base'];region(target,target+1,True)
                selected=[(j,s) for j,s in enumerate(sections) if s['flags']&0x40000000 and max(s['size'],s['virtual_size'])]
                require(len(selected)==len(actual['sections']),'complete readable runtime section inventory')
                data=[];total=0
                for (j,s),item in zip(selected,actual['sections']):
                    at=pe+24+struct.unpack_from('<H',raw,pe+20)[0]+j*40;virtual=struct.unpack_from('<I',raw,at+8)[0]
                    length=max(virtual,s['size']);require(item==[j,s['rva'],length,s['flags']],'loaded readable section extent/flags')
                    loaded=(directory/(prefix+f'-section-{j}.bin')).read_bytes();total+=length
                    require(len(loaded)==length and length<=128*1024 and total<=(16*1024*1024 if census is not None else 512*1024),'bounded readable runtime section bytes')
                    if s['flags']&0x20000000:
                        span=region(s['rva'],s['rva']+s['size'],True)
                        require(loaded[:s['size']]==relocated_code(raw,span,actual['owner_base']) and loaded[s['size']:]==bytes(length-s['size']),'loaded runtime instructions/file/relocations')
                    data.append({'role':'LoadedExecutable' if s['flags']&0x20000000 else 'DispatchOrImportData',
                                 'rva':s['rva'],'size':length,'sha256':digest(loaded),'file':prefix+f'-section-{j}.bin','resolution':'Resolved'})
                identity={'slot':declared,'runtime':actual,'module_sha256':digest(raw),'module_size':len(raw),
                          'loaded_sections':data,'sampled_identity':'PrePostOnlyNotContinuous'}
                if phase=='pre':
                    exports,candidates=export_metadata(raw)
                    witness={'image_sha256':digest(raw),'image_size':len(raw),'preferred_base':base,'sections':sections,
                             'all_same_link_symbols':[],'requests':[],'ranges':[],'pending':[],'decoded':[],'edges':[],'data_requests':data,
                             'export_metadata':exports,'export_candidates':candidates,
                             'compiled_dataflow':'UnprovedAwaitingIndependentReview'}
                    image={'raw':raw,'file':prefix+'-module.bin','witness':witness,'pre':identity}
                    if census is not None:image['root_image_sha256']=digest(rust_raw)
                    modules.append(image);by_slot[i]=image
                    origin={'kind':'RuntimeImport','slot_rva':declared['slot_rva']}
                    if census is not None:origin['root_image_sha256']=image['root_image_sha256']
                    request_range(witness,raw,target,'ActualOwnProcessImportTarget',origin,census)
                else:
                    before=by_slot[i]['pre']
                    require(before['slot']==identity['slot'] and before['runtime']==identity['runtime'] and
                            before['module_sha256']==identity['module_sha256'] and before['module_size']==identity['module_size'],
                            'pre/post sampled import/module/target identity')
                    require([(s['rva'],s['sha256']) for s in before['loaded_sections'] if s['role']=='LoadedExecutable']==
                            [(s['rva'],s['sha256']) for s in data if s['role']=='LoadedExecutable'],'pre/post sampled loaded instructions')
                    by_slot[i]['post']=identity
            except (ValueError,OSError,KeyError,IndexError,struct.error) as error:
                if census is None:raise
                census.unknowns.append({'kind':'RequiredImportOwnerBinding','slot':declared,'phase':phase,'reason':str(error)})
    return modules


def seed_data(raw,witness):
    source=(ROOT/'rust/crates/mds-math/src/estimate_table.rs').read_text()
    entries=re.findall(r'0x[0-9a-f]{8}',re.search(r'const RCP: \[u32; 2048\] = \[(.*?)\];',source,re.S)[1])
    table=b''.join(struct.pack('<I',int(v,16)) for v in entries)
    require(len(table)==8192 and raw.count(table)==1,'unique actual frozen 8192-byte seed table')
    offset=raw.index(table);matches=[s for s in witness['sections'] if s['offset']<=offset and offset+len(table)<=s['offset']+s['size']]
    require(len(matches)==1,'physical seed table PE section');start=matches[0]['rva']+offset-matches[0]['offset']
    return {'role':'SeedTable','start_rva':start,'size':8192,'bytes':table.hex(),'resolution':'Resolved'}


def caller_windows(parsed):
    base=parsed['operations'][0]['base'];result=[]
    for i,row in enumerate(parsed['operations']):
        if row['owner'][0]==1 and row['sites'][3] and row['sites'][4]:
            result.append({'start_rva':row['sites'][3]-base,'end_rva':row['sites'][4]-base,
                           'role':'ActualCallerInputThroughReturn','operation':i})
    before,after=parsed['merge_lineage']['caller']
    result.append({'start_rva':before-base,'end_rva':after-base,'role':'ActualLoadXCallerThroughReturnedMesh','operation':len(parsed['operations'])-1})
    return result


def formatting_exclusion(edge,witness,span):
    return False


def loaded_dispatch_target(directory,image,slot):
    samples=[]
    for phase in ('pre','post'):
        identity=image[phase]
        matches=[s for s in identity['loaded_sections'] if s['rva']<=slot and slot+8<=s['rva']+s['size']]
        require(len(matches)==1,'required loaded dispatch slot extent')
        section=matches[0];raw=(directory/section['file']).read_bytes()
        require(len(raw)==section['size'] and digest(raw)==section['sha256'],'required retained loaded dispatch data')
        value=struct.unpack_from('<Q',raw,slot-section['rva'])[0]
        samples.append({'phase':phase,'slot_rva':slot,'section':section,'target_va':value})
    require(samples[0]['target_va']==samples[1]['target_va'],'unresolved changing sampled dispatch target')
    base=image['pre']['runtime']['owner_base'];target=samples[0]['target_va']-base
    pe_code(image['raw'])[3](target,target+1,True)
    return target,samples


def disassembly_argv(binary,witness,span):
    base=witness['preferred_base']
    return [str(DISASSEMBLER),'--disassemble','--start-address='+hex(base+span['start_rva']),
            '--stop-address='+hex(base+span['end_rva']),str(binary)]


def disassembly_bytes(stdout,witness,span):
    expected=bytes.fromhex(span['bytes']);cursor=span['start_rva'];count=0
    for line in stdout.decode('utf-8').splitlines():
        match=re.fullmatch(r'\s*([0-9a-fA-F]+):\s+((?:[0-9a-fA-F]{2}\s+)+)(\S.*)',line)
        if match:
            address=int(match[1],16)-witness['preferred_base'];raw=bytes.fromhex(match[2]);offset=address-span['start_rva']
            require(address==cursor and raw and offset+len(raw)<=len(expected) and expected[offset:offset+len(raw)]==raw,'disassembly exact contiguous PE instruction bytes')
            require('<unknown>' not in match[3] and '(bad)' not in match[3],'undecoded required instruction region')
            cursor+=len(raw);count+=1
    require(count and cursor==span['end_rva'],'complete bounded disassembly byte coverage')


def compiled_evidence(directory,parsed,r,capture=False,env=None):
    help_argv=[str(DISASSEMBLER),'--help']
    if capture:
        require(Path(DISASSEMBLER).is_file(),'hosted bounded disassembly tool availability prerequisite')
        require(record(directory,'instruction-help',help_argv,r['source'],env)['status']==0,'actual hosted disassembler help prerequisite')
    receipt,stdout,stderr=checked(directory,'instruction-help')
    require(receipt['argv']==help_argv and receipt['cwd']==r['source'] and not stderr,'exact hosted disassembler help receipt')
    require(all(option.encode() in stdout for option in ('--disassemble','--start-address','--stop-address')),'actual bounded disassembly capabilities prerequisite')
    tool=receipt.get('tool_binary');require(type(tool) is dict and set(tool)=={'path','sha256','size'} and
            tool['path']==str(DISASSEMBLER) and re.fullmatch('[0-9a-f]{64}',tool['sha256']) and type(tool['size']) is int and tool['size']>0,'actual hosted tool identity')
    tool_raw=(directory/'instruction-tool.bin').read_bytes()
    require(digest(tool_raw)==tool['sha256'] and len(tool_raw)==tool['size'],'retained hosted instruction tool identity')
    result={}
    for language,name,map_name in (('native','floor_profile.exe','native.map'),('rust','rust-profile.exe','rust.map')):
        raw=(directory/name).read_bytes();mapping=(directory/map_name).read_bytes()
        witness={};images=[{'raw':raw,'file':name,'witness':witness}]
        try:
            if language=='native':witness.update(code_ranges(raw,parsed[0]['operations'],mapping))
            else:required_code_ranges(raw,parsed[1]['operations'],mapping,witness)
            witness['same_link_map']={'sha256':digest(mapping),'size':len(mapping)}
            if language=='rust':
                images+=runtime_images(directory,parsed[1],raw)
                witness['caller_windows']=caller_windows(parsed[1])
                witness['data_requests'].append(seed_data(raw,witness))
                witness['copy_obligations']=[dict(row) for row in COPY_OBLIGATIONS]
            if language=='rust':
                for address in (parsed[1]['merge_lineage']['returned'][4],*[a[9] for a in parsed[1]['merge_lineage']['rows']]):
                    request_range(witness,raw,address-parsed[1]['operations'][0]['base'],'MergePointerLineage',{'kind':'RuntimeSite','role':'MergeStorage'})
            if language=='rust':closure_budget([image['witness'] for image in images])
            for module_index,image in enumerate(images):
                view=image['witness'];image_raw=image['raw']
                view.setdefault('pending',[[s['start_rva'],s['end_rva']] for s in view['ranges']]);view.setdefault('decoded',[])
                i=0
                while view['pending']:
                    extent=view['pending'][0]
                    span=next(s for s in view['ranges'] if [s['start_rva'],s['end_rva']]==extent)
                    label=language+('' if module_index==0 else '-runtime-'+str(module_index))+'-instructions-'+str(i)
                    argv=disassembly_argv(PureWindowsPath(r['evidence'])/image['file'],view,span)
                    if capture:require(record(directory,label,argv,r['source'],env)['status']==0,'bounded hosted disassembly prerequisite')
                    row,assembly,error=checked(directory,label)
                    require(row['argv']==argv and row['cwd']==r['source'] and row.get('tool_binary')==tool and not error,'exact bounded tool/image/range command')
                    disassembly_bytes(assembly,view,span)
                    if language=='rust':
                        edges=instruction_edges(assembly,view,span);view['edges'].extend(edges)
                        for edge in edges:
                            follow_required_edge(directory,images,module_index,span,edge)
                        closure_budget([item['witness'] for item in images])
                    view['decoded'].append(view['pending'].pop(0));i+=1
                    if capture:write_json(directory/(language+'-code-progress.json'),{'schema':SCHEMA,'images':[{k:v for k,v in item.items() if k!='raw'} for item in images]})
            if language=='rust':
                complete_closure(images)
                witness['runtime_images']=[{k:v for k,v in item.items() if k!='raw'} for item in images[1:]]
        finally:
            if capture:write_json(directory/(language+'-code-progress.json'),{'schema':SCHEMA,'images':[{k:v for k,v in item.items() if k!='raw'} for item in images]})
        if capture:write_json(directory/(language+'-code.json'),witness)
        require(load_json((directory/(language+'-code.json')).read_bytes())==witness,'rederived executed-image code witness')
        result[language]=witness
    return result



def census_evidence(directory,parsed,r,env,census):
    images=[]
    census.unknowns.append({'kind':'RequiredNonBranchDataTargets','reason':'BranchDecoderDoesNotProveCompleteMachineDataReferenceCoverage'})
    try:
        help_argv=[str(DISASSEMBLER),'--help']
        require(Path(DISASSEMBLER).is_file(),'hosted diagnostic disassembler unavailable')
        require(record(directory,'instruction-help',help_argv,r['source'],env)['status']==0,'diagnostic disassembler help')
        receipt,stdout,stderr=checked(directory,'instruction-help')
        require(not stderr and all(flag.encode() in stdout for flag in ('--disassemble','--start-address','--stop-address')),'bounded diagnostic tool capabilities')
        tool=receipt['tool_binary']
        tool_raw=(directory/'instruction-tool.bin').read_bytes()
        require(receipt['argv']==help_argv and receipt['cwd']==r['source'] and
                tool=={'path':str(DISASSEMBLER),'sha256':digest(tool_raw),'size':len(tool_raw)},'diagnostic retained tool and exact help command')
        for language,name,map_name in (('native','floor_profile.exe','native.map'),('rust','rust-profile.exe','rust.map')):
            raw=(directory/name).read_bytes();mapping=(directory/map_name).read_bytes();view={}
            image={'raw':raw,'file':name,'language':language,'witness':view};images.append(image)
            try:
                if language=='rust':required_code_ranges(raw,parsed[1]['operations'],mapping,view,census)
                else:
                    view.update(code_ranges(raw,parsed[0]['operations'],mapping))
                    view.update(census_language='native',requests=[],edges=[],data_requests=[],all_same_link_symbols=map_symbols(mapping,view['preferred_base'],view['sections']),pending=[[s['start_rva'],s['end_rva']] for s in view['ranges']],decoded=[])
                    for span in view['ranges']:
                        view['requests'].append({'resolution':'Resolved','start_rva':span['start_rva'],'end_rva':span['end_rva'],'role':'NativeOperationRoot','origin':{'kind':'RuntimeSite'}})
                    census.register(view);census.check()
                view['same_link_map']={'sha256':digest(mapping),'size':len(mapping)}
                if language=='rust':
                    view['copy_obligations']=[dict(row) for row in COPY_OBLIGATIONS]
                    view['data_requests'].append(seed_data(raw,view))
                    if parsed[1].get('runtime_imports'):
                        try:images.extend(runtime_images(directory,parsed[1],raw,census))
                        except (ValueError,OSError,KeyError,struct.error) as error:census.unknowns.append({'kind':'RequiredRuntimeImports','reason':str(error)})
                    else:census.unknowns.append({'kind':'RequiredRuntimeImports','reason':'ControlHasNoOwnProcessImportSnapshots'})
                    if 'merge_lineage' in parsed[1]:
                        view['caller_windows']=caller_windows(parsed[1])
                        for address in (parsed[1]['merge_lineage']['returned'][4],*[a[9] for a in parsed[1]['merge_lineage']['rows']]):
                            request_range(view,raw,address-parsed[1]['operations'][0]['base'],'MergePointerLineage',{'kind':'RuntimeSite','role':'MergeStorage'},census)
                    else:census.unknowns.append({'kind':'MergePointerLineage','reason':'ControlHasNoObservedLineage'})
            except (ValueError,OSError,KeyError,struct.error) as error:
                census.unknowns.append({'kind':'RequiredRoots','image':name,'reason':str(error)})
        for module_index,image in enumerate(images):
            view=image['witness'];attempted=set();i=0
            while any(tuple(span) not in attempted for span in view.get('pending',[])):
                extent=next(span for span in view['pending'] if tuple(span) not in attempted);attempted.add(tuple(extent))
                try:
                    census.check()
                    span=next(s for s in view['ranges'] if [s['start_rva'],s['end_rva']]==extent)
                    label='census-'+str(module_index)+'-instructions-'+str(i);i+=1
                    argv=disassembly_argv(PureWindowsPath(r['evidence'])/image['file'],view,span)
                    require(record(directory,label,argv,r['source'],env)['status']==0,'diagnostic bounded disassembly')
                    row,assembly,error=checked(directory,label)
                    require(row['argv']==argv and row['cwd']==r['source'] and row.get('tool_binary')==tool and not error,'exact diagnostic tool/image/extent receipt')
                    edges=instruction_edges(assembly,view,span);view['edges'].extend(edges)
                    for edge in edges:
                        try:follow_required_edge(directory,images,module_index,span,edge,census)
                        except (ValueError,OSError,KeyError,struct.error) as error:
                            edge['obligation']='Unresolved';edge['reason']=str(error)
                    view['decoded'].append(extent);view['pending'].remove(extent)
                except CensusLimit as error:
                    census.unknowns.append({'kind':'DiagnosticCeiling','reason':str(error)});break
                except (ValueError,OSError,KeyError,struct.error) as error:
                    census.unknowns.append({'kind':'Decode','image':image['file'],'extent':extent,'reason':str(error)})
                finally:write_json(directory/'closure-census-progress.json',census.summary(images))
        rust_images=[image for image in images if image.get('language')!='native']
        try:complete_closure(rust_images,census)
        except (ValueError,KeyError,IndexError) as error:
            census.unknowns.append({'kind':'OrdinaryClosurePredicate','reason':str(error)})
    except (ValueError,OSError,KeyError,struct.error) as error:
        census.unknowns.append({'kind':'AcquisitionPrerequisite','reason':str(error)})
    result=census.summary(images)
    receipt=write_bound_document(directory/'closure-census.json',result)
    return result,receipt


FIXTURE_TESTS = {
    'mesh_dump': {'every_fixture_equals_its_windows_dump'},
    'x_files': {'cube_text','cube_binary_matches_text',
                'several_materials_group_faces_and_resolve_references',
                'nested_frames_apply_their_transforms_in_order',
                'mesh_without_normals_or_uvs_gets_computed_normals_and_default_material',
                'normals_in_the_file_are_replaced_when_texture_coordinates_are_missing',
                'normals_in_the_file_stay_when_texture_coordinates_exist',
                'texture_names_choose_the_sphere_map_type','malformed_files_return_their_error',
                'every_truncation_of_a_valid_file_is_handled','more_than_16_bit_vertices_are_refused',
                'deep_nesting_does_not_overflow_the_stack','xmesh_reports_what_the_loaded_format_had'},
}
FIXTURE_EMITTER = 'fn emit(value: String) { ACTIVE.with(|a| if a.get() { println!("FP {value}"); }); }'


def fixture_result(label,stdout,stderr):
    require(label in FIXTURE_TESTS,'known fixture target')
    expected=FIXTURE_TESTS[label];count=len(expected)
    text=stdout.decode('utf-8').replace('\r\n','\n')
    require('\r' not in text and 'SKIP' not in text,'fixture stdout encoding/unsupported execution')
    lines=text.split('\n')
    require(len(lines)==count+6 and lines[0]==lines[-1]==lines[-2]==lines[-4]=='' and
            lines[1]==f'running {count} '+('test' if count==1 else 'tests'),'complete fixture run framing')
    names=[]
    for line in lines[2:2+count]:
        row=re.fullmatch(r'test ([a-z_][a-z_0-9]*) \.\.\. ok',line)
        require(row is not None,'fixture named ok row')
        names.append(row[1])
    require(len(set(names))==count and set(names)==expected,'complete unique fixture names')
    require(re.fullmatch(r'test result: ok[.] '+str(count)+r' passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in [0-9]+[.][0-9]{2}s',lines[-3]) is not None,'complete fixture success summary')
    quoted=False
    for line in stderr.decode('utf-8').splitlines():
        require('SKIP' not in line,'fixture stderr unsupported execution')
        if 'FP' in line:
            quote=re.fullmatch(r' *[1-9][0-9]* \| (.*)',line)
            require(not quoted and quote is not None and quote[1]==FIXTURE_EMITTER,'fixture stderr runtime telemetry or altered source excerpt')
            quoted=True
        require(re.search(r'running [0-9]+ tests?|test .* \.\.\.|test result:',line) is None,'fixture stderr forged libtest output')


def recipe(runner_temp,variant,opt,census=False):
    root=PureWindowsPath(runner_temp)
    require(root.is_absolute() and '..' not in root.parts and variant in ('control','observed') and opt in ('Od','O2'),'closed recipe inputs')
    out=root/('closure-census-evidence' if census else 'floor-profile-evidence');build=root/('closure-census-build' if census else 'floor-profile-build')
    id=variant+'-'+opt;source=out/'sources'/id;directory=out/id
    native=build/id/'native';target=build/id/'rust'
    mode=['--release'] if opt=='O2' else []
    commands={
        'configure':['cmake','-S',str(source),'-B',str(native),'-G','Visual Studio 17 2022','-A','x64','-DCMAKE_TOOLCHAIN_FILE='+str(root/'floor-profile-deps/build/generators/conan_toolchain.cmake'),'-DBUILD_TESTING=OFF','-DMIKUDANCESTUDIO_DIAG=OFF'],
        'native-build':['cmake','--build',str(native),'--config','Release','--target','floor_profile','--parallel','1','--verbose'],
        'native':[str(directory/'floor_profile.exe'),'fixed',variant],
        'rust-build':['cargo','+1.95.0','test','-p','mds-accessory','--lib','--no-run','--message-format=json']+mode,
        'rust':[str(directory/'rust-profile.exe'),'mesh::floor_profile::diagnostic','--exact','--nocapture','--test-threads=1'],
    }
    for test in ('mesh_dump','x_files'):
        commands[test]=['cargo','+1.95.0','test','-p','mds-accessory','--test',test]+mode+['--','--nocapture','--test-threads=1']
    return {'id':id,'source':str(source),'target':str(target),'evidence':str(directory),
            'native_target':str(native),'input_root':str(out/'inputs'),'commands':commands,
            'cwd':{label:str(source/'rust') if label.startswith('rust') or label in ('mesh_dump','x_files') else str(source) for label in commands}}


def admit_recipe(m,b):
    r=recipe(m['runner_temp'],b['variant'],b['optimization'])
    require(m['input_root']==r['input_root'],'closed input root')
    require(all(b[key]==r[key] for key in ('id','source','target','evidence','commands')),'closed command/source/target/evidence recipe')
    return r


def admit_command(receipt,r,label):
    require(receipt['argv']==r['commands'][label] and receipt['cwd']==r['cwd'][label],'exact command/cwd binding')
    expected={'CARGO_TARGET_DIR':r['target'],'CARGO_INCREMENTAL':'0',
              'RUSTFLAGS':RUST_FLAGS,'CL':'','_CL_':''}
    require(all(receipt['env'].get(k)==v for k,v in expected.items()),'closed compiler environment')


def admit_manifest(m):
    require(m['fp_observation_contract']==FP_CONTRACT,'fixed FP observation contract')
    require(m['schema']==SCHEMA and m['base']==BASE and m['paths']==PATHS and re.fullmatch('[0-9a-f]{40}',m['head']),'diagnostic generation/head')
    words(m['operation_corpus']['words'])
    require(m['operation_corpus']=={'sha256':digest(operation_corpus()),'size':152,'words':corpus_words(operation_corpus())},'generation operation corpus')


def cargo_binary(raw,r,opt):
    lines=[line for line in raw.splitlines(keepends=True) if line.lstrip().startswith(b'{')]
    require(lines and all(line.endswith(b'\n') for line in lines),'complete Cargo JSON')
    rows=[load_json(line) for line in lines]
    require(all(type(row) is dict and type(row.get('reason')) is str for row in rows),'Cargo object')
    require([row for row in rows if row['reason']=='build-finished']==[{'reason':'build-finished','success':True}] and rows[-1]=={'reason':'build-finished','success':True},'Cargo terminal')
    artifacts=[row for row in rows if row['reason']=='compiler-artifact' and row.get('target',{}).get('name')=='mds_accessory']
    require(len(artifacts)==1,'exact Cargo package target')
    row=artifacts[0];source=PureWindowsPath(r['source'])/'rust/crates/mds-accessory';t=row['target']
    package=row.get('package_id');require(type(package) is str and package.startswith('path+file:///') and package.count('#')==1 and package.endswith('#0.1.0'),'Cargo package identity')
    from urllib.parse import quote,unquote
    encoded=package[len('path+file:///'):].split('#')[0]
    package_path=unquote(encoded,errors='strict')
    require(quote(package_path,safe='/:')==encoded and package_path==source.as_posix(),'Cargo package source')
    require(PureWindowsPath(row['manifest_path'])==source/'Cargo.toml' and PureWindowsPath(t['src_path'])==source/'src/lib.rs' and t['kind']==['lib'] and t['crate_types']==['lib'] and t['test'] is True,'Cargo target source/kind')
    profile={'opt_level':'3' if opt=='O2' else '0','debuginfo':0 if opt=='O2' else 2,'debug_assertions':opt=='Od','overflow_checks':opt=='Od','test':True}
    require(row['profile']==profile and type(row['profile']['debuginfo']) is int and all(type(row['profile'][key]) is bool for key in ('debug_assertions','overflow_checks','test')),'actual Cargo profile')
    exe=row['executable'];path=PureWindowsPath(exe)
    require(path.parent==PureWindowsPath(r['target'])/('release' if opt=='O2' else 'debug')/'deps' and re.fullmatch('mds_accessory-[0-9a-f]+[.]exe',path.name) and exe in row['filenames'],'Cargo executable membership')
    return exe


def command_words(line):
    result=[];token='';quoted=False;at=0;started=False
    while at<len(line):
        char=line[at]
        if char=='\\':
            end=at
            while end<len(line) and line[end]=='\\':end+=1
            count=end-at
            if end<len(line) and line[end]=='"':
                token+='\\'*(count//2)
                if count%2:token+='"'
                else:quoted=not quoted
                at=end+1
            else:token+='\\'*count;at=end
            started=True;continue
        if char=='"':quoted=not quoted;started=True
        elif char.isspace() and not quoted:
            if started:result.append(token);token='';started=False
        else:token+=char;started=True
        at+=1
    require(not quoted,'unterminated Windows command quote')
    if started:result.append(token)
    require(result and not any(v.startswith('@') for v in result),'unexpanded response file')
    return result


def _compiler_progress(line,indent):
    token=line[len(indent):] if line.startswith(indent) else ''
    return token.lower() if re.fullmatch(r'[^\\/\s]+[.]cpp',token,re.I) else None


def native_commands(stdout,stderr,r):
    require(not stderr.strip(),'unordered native stderr')
    require(r['commands']['native-build'][-3:]==['--parallel','1','--verbose'],'serial native recipe')
    lines=stdout.decode(errors='strict').splitlines()
    root=PureWindowsPath(r['native_target']);project_root=root/'floor_profile.vcxproj'
    require(lines and lines[0]=="Change Dir: '"+root.as_posix()+"'",'native build directory banner')
    launches=[line for line in lines if line.startswith('Run Build Command(s): ')]
    require(len(launches)==1,'one native launch banner')
    launch=command_words(launches[0][len('Run Build Command(s): '):])
    require(PureWindowsPath(launch[0]).is_absolute() and PureWindowsPath(launch[0]).name.lower()=='msbuild.exe' and
            launch[1:]==['floor_profile.vcxproj','/p:Configuration=Release','/p:Platform=x64','/p:VisualStudioVersion=17.0','/m:1','/v:n'],'serial native launch banner')
    result=[];stack=[];task=None;active=None;indent=None;owner=None;warnings=[];summary=False;started=False
    at=0
    while at<len(lines):
        line=lines[at];at+=1
        prefix=re.match(r'^ {0,5}(\d+)>(.*)$',line)
        number=prefix[1] if prefix else None
        text=prefix[2] if prefix else line.lstrip()
        space=line[:len(line)-len(line.lstrip())]
        start=re.fullmatch(r'Project "(.+[.]vcxproj)"(?: \((\d+)\) is building "(.+[.]vcxproj)" \((\d+)\))? on node (\d+) \(default targets\)[.]',text)
        if start:
            require(not summary and active is None and start[5]=='1','serial project start')
            if start[2]:
                require(stack and (start[2],PureWindowsPath(start[1]))==stack[-1] and number in (None,start[2]),'serial project parent')
                child=(start[4],PureWindowsPath(start[3]))
                require(child[1].parent==root and child not in stack,'serial child project')
                stack.append(child)
            else:
                require(not started and not stack and PureWindowsPath(start[1])==project_root,'native root project')
                stack.append((number or '1',project_root));started=True
            task=None;continue
        done=re.fullmatch(r'Done Building Project "(.+[.]vcxproj)" \(default targets\)[.]',text)
        if done:
            require(stack and PureWindowsPath(done[1])==stack[-1][1] and number in (None,stack[-1][0]),'matching project completion')
            require(active is None or owner==stack[-1],'pending project completion')
            active=None;owner=None;stack.pop();task=None;continue
        if text=='Checking Build System':
            require(active is None and owner is None and task=='CustomBuild' and len(stack)==2 and
                    number==stack[0][0] and winpath(stack[0][1],root)==winpath(project_root,root) and
                    winpath(stack[1][1],root)==winpath(root/'ZERO_CHECK.vcxproj',root),'closed build-system progress')
            continue
        if number:
            require(stack and number==stack[-1][0],'out-of-owner project activity')
        if text=='Build succeeded.':
            require(started and not stack and active is None and not summary,'closed native build summary')
            summary=True;continue
        warning=re.fullmatch(r'([A-Za-z]:.+)\((\d+),(\d+)\): warning (C4018|C4200): (.+) \[(.+[.]vcxproj)\]',text)
        if warning:
            if summary:
                require(number is None and text in warnings,'matching warning summary');continue
            require(active is not None and task=='ClCompile' and owner==stack[-1] and PureWindowsPath(warning[6])==owner[1],'compiler warning owner')
            sources=[winpath(v,r['native_target']) for v in active[1:] if v.lower().endswith('.cpp')]
            source=PureWindowsPath(warning[1]);location=warning[1]+'('+warning[2]+','+warning[3]+'):'
            if warning[4]=='C4018':
                require(source in sources and warning[5] in ("'<': signed/unsigned mismatch","'>': signed/unsigned mismatch"),'closed C4018 diagnostic')
            else:
                require(source==PureWindowsPath(r['source'])/'include/mikudancestudio/subrecord_layout.hpp' and (warning[2],warning[3])==('206','11') and
                        warning[5]=='nonstandard extension used: zero-sized array in struct/union','closed C4200 diagnostic')
                progress=set()
                while at<len(lines):
                    basename=_compiler_progress(lines[at],indent)
                    if basename is None:break
                    require(not basename.startswith(('-', '@')) and not any(char in basename for char in '"\':<>|?*') and
                            basename not in progress and sum(path.name.lower()==basename for path in sources)==1,'C4200 compiler progress identity')
                    progress.add(basename);at+=1
                require(at+7<=len(lines),'truncated C4200 diagnostic')
                context=lines[at:at+7]
                compiled=re.fullmatch(re.escape(indent)+r"\(compiling source file '([^']+)'\)",context[0])
                require(compiled is not None,'C4200 compiled source record')
                compiled_source=winpath(compiled[1],r['native_target'])
                require(compiled_source in sources and compiled_source==PureWindowsPath(r['source'])/'src/model/model_skinning.cpp','C4200 compiled source identity')
                require(context[1:]==[indent+'    '+location,
                    indent+'    This member will be ignored by a defaulted constructor or copy/move assignment operator',
                    indent+'    '+location,
                    indent+'    the template instantiation context (the oldest one first) is',
                    indent+'        '+str(compiled_source)+'(667,20):',
                    indent+"        see reference to class template instantiation 'mikudancestudio::mdl::SkinnedVertex<0>' being compiled"],'closed C4200 context')
                at+=7
            warnings.append(text);continue
        header=re.fullmatch(r'(\w+):',text)
        if header:
            require(stack and not summary,'native task owner')
            if active is not None:
                require(owner==stack[-1] and len(space)<len(indent),'ambiguous native task boundary')
                if header[1]==task:continue
            active=None;owner=None;task=header[1];continue
        project=re.fullmatch(r'(\S+[.]vcxproj) -> (.+)',text)
        if project:
            require(stack and winpath(project[1],root)==winpath(stack[-1][1],root),'matching project output')
            if active is not None:
                require(owner==stack[-1] and task in ('Lib','Link') and winpath(project[2],root)==winpath(option(active[1:],'/OUT'),root),'matching command output')
            active=None;owner=None;continue
        match=re.fullmatch(r'("?)([A-Za-z]:[^"\r\n]*[\\/](cl|link|lib)[.]exe)\1\s+(.+)',text,re.I)
        if match:
            require(stack and not summary and match[3].lower()=={'ClCompile':'cl','Lib':'lib','Link':'link'}.get(task),'native task/tool identity')
            require(active is None or owner==stack[-1],'native command owner')
            active=[match[2]]+command_words(match[4]);indent=space;owner=stack[-1];result.append(active);continue
        if not line.strip():continue
        if active is None:
            require(not re.match(r'(?:"?[/-][A-Za-z]|"?@|"?[A-Za-z]:.*[.](?:cpp|obj|lib)|\S+[.](?:cpp|obj|lib)(?:["\s]|$)|\(compiling source file|This member|the template instantiation|see reference|.*warning C|.*\(\d+,\d+\):)',text,re.I),'orphan native argument or diagnostic')
            continue
        continuation=line[len(indent):] if not number and line.startswith(indent) else ''
        progress=_compiler_progress(line,indent) if not number and task=='ClCompile' else None
        if progress is not None:
            require(progress in [PureWindowsPath(v).name.lower() for v in active[1:] if v.lower().endswith('.cpp')],'unrelated compiler progress');continue
        if task=='Link' and re.fullmatch(r'\s+Creating library .+[.]lib and object .+[.]exp',line):continue
        require(task in ('ClCompile','Lib','Link') and continuation and not continuation[0].isspace(),'ambiguous native command content')
        args=command_words(continuation)
        suffixes={'ClCompile':('.cpp',),'Lib':('.obj',),'Link':('.obj','.lib')}[task]
        require(all(v.startswith(('/','-')) or (v.lower().endswith(suffixes) and not any(c in v for c in '"<>|?*')) for v in args),'ambiguous native continuation')
        active.extend(args)
    require(started and not stack and summary and active is None,'truncated native command or project')
    return [row for i,row in enumerate(result) if row not in result[:i]]


def winpath(path,cwd):
    return PureWindowsPath(ntpath.normpath(str(PureWindowsPath(cwd)/path)))


def option(args,name):
    values=[]
    for i,arg in enumerate(args):
        if arg.lower().startswith(name.lower()):
            value=arg[len(name):]
            if value.startswith(':'):value=value[1:]
            if not value:
                require(i+1<len(args),'option value');value=args[i+1]
            values.append(value)
    require(values,'missing option '+name)
    return values[-1]


def archive_members(raw):
    require(raw.startswith(b'!<arch>\n'),'COFF archive signature')
    at=8;result=[]
    while at<len(raw):
        require(at+60<=len(raw) and raw[at+58:at+60]==b'`\n','COFF archive header')
        size=int(raw[at+48:at+58].strip());start=at+60;end=start+size
        require(size>=0 and end<=len(raw),'COFF archive member bounds')
        name=raw[at:at+16].strip()
        if name not in (b'/',b'//'):result.append(raw[start:end])
        at=end+(size%2)
    require(at==len(raw),'COFF archive end')
    return result


def native_provenance(commands,r,opt,objects,archive):
    cwd=r['native_target'];source=PureWindowsPath(r['source']);root=PureWindowsPath(cwd)
    def tool(row):return PureWindowsPath(row[0]).name.lower()
    def compile(path):
        matches=[row for row in commands if tool(row)=='cl.exe' and any(winpath(v,cwd)==source/path for v in row[1:] if v.lower().endswith('.cpp'))]
        require(len(matches)==1,'exact source compilation '+path)
        args=matches[0][1:];require('/c' in [v.lower() for v in args],'compile-only command')
        options=[v.lower() for v in args if re.fullmatch(r'(?i)[/-]O(?:d|[012x])',v)]
        require(options and options[-1][1:]==opt.lower(),'effective ordered optimization')
        obj=option(args,'/Fo');obj=winpath(obj,cwd)
        if not obj.suffix:obj=obj/(PureWindowsPath(path).stem+'.obj')
        expected=root/('mikudancestudio_core.dir' if path==ACCESSORY else 'floor_profile.dir')/'Release'/(PureWindowsPath(path).stem+'.obj')
        require(obj==expected,'exact CMake target object')
        relative=obj.relative_to(root).as_posix()
        require(relative in objects,'exact compiled retained object')
        return obj,objects[relative]
    accessory,accessory_bytes=compile(ACCESSORY);native,native_bytes=compile('native.cpp')
    lib=root/'Release/mikudancestudio_core.lib'
    libraries=[row for row in commands if tool(row)=='lib.exe' and winpath(option(row[1:],'/OUT'),cwd)==lib]
    require(len(libraries)==1 and accessory in [winpath(v,cwd) for v in libraries[0][1:] if v.lower().endswith('.obj')],'core archive object membership')
    require(any(member==accessory_bytes for member in archive_members(archive)),'compiled accessory object bytes in core archive')
    exe=root/'Release/floor_profile.exe'
    links=[row for row in commands if tool(row)=='link.exe' and winpath(option(row[1:],'/OUT'),cwd)==exe]
    require(len(links)==1,'exact final executable link')
    args=links[0][1:]
    require(native in [winpath(v,cwd) for v in args if v.lower().endswith('.obj')] and lib in [winpath(v,cwd) for v in args if v.lower().endswith('.lib')],'final link exact harness object and core archive')
    require('/map' in [v.lower() for v in args],'selected same-link native map')
    return str(exe)


def source_expected(base,observed,input_root,opt,census=False):
    runtime=PureWindowsPath(str(input_root)).parent/(('observed' if observed else 'control')+'-'+opt.lstrip('/'))/'operations.bin'
    changes,patches=generated(lambda p:(base/p).read_bytes(),observed,input_root,runtime,census)
    raw=changes['CMakeLists.txt'];replacement=raw.replace(b'@OPT@',opt.encode())
    patches['CMakeLists.txt'].append({'kind':'optimization','original_hex':raw.hex(),'original_sha256':digest(raw),'generated_sha256':digest(replacement),'option':opt})
    changes['CMakeLists.txt']=replacement
    expected=c.source_inventory(base)
    for path,raw in changes.items():expected[path]={'sha256':digest(raw),'mode':expected.get(path,{}).get('mode',0o644)}
    return changes,patches,expected


def source_tree(raw):
    require(type(raw) is bytes and raw.endswith(b'\0'),'complete source tree frame')
    entries={}
    for row in raw[:-1].split(b'\0'):
        fields=row.split(b'\t');require(len(fields)==2,'source tree row framing')
        meta,name=fields;parts=meta.split(b' ')
        require(len(parts)==3,'source tree metadata framing')
        mode,kind,oid=parts;path=name.decode('utf-8');h.safe_name(path)
        require(mode in (b'100644',b'100755') and kind==b'blob' and re.fullmatch(b'[0-9a-f]{40}',oid) and path not in entries,'source tree mode/blob/unique path')
        entries[path]=[mode.decode(),oid.decode()]
    h.tree_hash(entries)
    return entries


def source_commit(raw,revision,entries=None,parents=None):
    require(type(raw) is bytes and h.git_hash('commit',raw)==revision,'retained ancestry commit hash')
    headers,separator,_=raw.partition(b'\n\n');require(separator,'source commit header termination')
    lines=headers.decode('utf-8').splitlines()
    trees=[line[5:] for line in lines if line.startswith('tree ')]
    require(len(trees)==1 and lines[0]=='tree '+trees[0] and re.fullmatch('[0-9a-f]{40}',trees[0]),'source commit tree header')
    actual=[line[7:] for line in lines if line.startswith('parent ')]
    require(all(re.fullmatch('[0-9a-f]{40}',p) for p in actual),'source commit parent identity')
    if entries is not None:require(trees==[h.tree_hash(entries)],'complete source commit/tree identity')
    if parents is not None:require(actual==parents,'ordinary linear descent from frozen generation parent')
    return trees[0]


def source_history_bound(chain,head,admitted):
    require(type(chain) is list and all(type(revision) is str for revision in chain),'typed generation ancestry')
    fixed=chain.count(ACCEPTED_MAIN['merge']) if admitted else 0
    require(0<len(chain)<=(32 if admitted else 16)+fixed and fixed==int(admitted) and len(set(chain))==len(chain) and chain[-1]==head,'bounded ordinary generation ancestry')


def source_ancestry(m,commits):
    chain=m['generation_ancestry']
    admitted=m.get('source_admission') in (LEGACY_SOURCE_ADMISSION,SOURCE_ADMISSION,MAIN_SOURCE_ADMISSION)
    require(m.get('source_admission') in (None,LEGACY_SOURCE_ADMISSION,SOURCE_ADMISSION,MAIN_SOURCE_ADMISSION),'closed source admission tag')
    source_history_bound(chain,m['head'],admitted)
    parent=PARENT
    for revision in chain:
        require(type(revision) is str and re.fullmatch('[0-9a-f]{40}',revision),'ancestry commit identity')
        parents=[parent]
        if admitted and revision==ACCEPTED_MAIN['merge']:
            require(parent==ACCEPTED_MAIN['renderer'],'accepted renderer terminal generation')
            parents.append(ACCEPTED_MAIN['main'])
        source_commit(commits[revision],revision,parents=parents)
        parent=revision


def generation_ancestry(out,m):
    source_ancestry(m,{revision:(out/'ancestry'/(revision+'.commit')).read_bytes() for revision in m['generation_ancestry']})


def fixed_import_frames():
    return {'fixed-import/'+name+suffix for name in ('parent','origin') for suffix in ('.commit','.tree')}|{
        'fixed-import/bodies/'+path for path in FIXED_IMPORT_BLOBS}


def verify_fixed_import(frames):
    trees={name:source_tree(frames['fixed-import/'+name+'.tree']) for name in ('parent','origin')}
    for name in trees:
        require(h.tree_hash(trees[name])==FIXED_IMPORT[name+'_tree'],'fixed import origin tree')
        source_commit(frames['fixed-import/'+name+'.commit'],FIXED_IMPORT[name],trees[name],
                      [FIXED_IMPORT['parent']] if name=='origin' else None)
    old={p:['100644',oids[0]] for p,oids in FIXED_IMPORT_BLOBS.items()}
    new={p:['100644',oids[1]] for p,oids in FIXED_IMPORT_BLOBS.items()}
    require(all(trees['parent'].get(p)==row for p,row in old.items()) and
            trees['origin']==trees['parent']|new,'exact fixed three-path origin overlay')
    bodies={p:frames['fixed-import/bodies/'+p] for p in new}
    require(all(h.git_hash('blob',raw)==new[p][1] for p,raw in bodies.items()),'fixed import authenticated bodies')
    return old,new,bodies


def current_import_frames():
    return {'current-import/origin.commit','current-import/origin.tree'}|{
        'current-import/bodies/'+path for path in CURRENT_IMPORT_ENTRIES}


def verify_current_import(frames):
    origin=source_tree(frames['current-import/origin.tree'])
    require(h.tree_hash(origin)==CURRENT_IMPORT['origin_tree'],'fixed current main origin tree')
    source_commit(frames['current-import/origin.commit'],CURRENT_IMPORT['origin'],origin,CURRENT_IMPORT['origin_parents'])
    require(all(origin.get(p)==row for p,row in CURRENT_IMPORT_ENTRIES.items()),'fixed current main import entries')
    bodies={p:frames['current-import/bodies/'+p] for p in CURRENT_IMPORT_ENTRIES}
    require(all(h.git_hash('blob',raw)==CURRENT_IMPORT_ENTRIES[p][1] for p,raw in bodies.items()),'authenticated current main import bodies')
    return CURRENT_IMPORT_ENTRIES,bodies


def verify_current_transition(frames,raw,previous,tail,renderer):
    source_commit(raw,CURRENT_IMPORT['applied'],tail,[CURRENT_IMPORT['preceding']])
    source_commit(frames['ancestry/'+CURRENT_IMPORT['preceding']+'.commit'],CURRENT_IMPORT['preceding'],previous)
    origin=source_tree(frames['current-import/origin.tree'])
    changed={p for p in set(previous)|set(tail) if previous.get(p)!=tail.get(p)}
    require(h.tree_hash(tail)==CURRENT_IMPORT['applied_tree'] and
            changed==set(CURRENT_IMPORT_ENTRIES) and tail==previous|CURRENT_IMPORT_ENTRIES,
            'one exact current main import overlay')
    require(not renderer&origin.keys() and
            tail==origin|{p:previous[p] for p in renderer},'complete current main and renderer union')
    restored={p:row for p,row in tail.items() if p not in CURRENT_IMPORT_ENTRIES}|{
        p:previous[p] for p in CURRENT_IMPORT_ENTRIES if p in previous}
    require(restored==previous,'current main import inverse to preceding generation')


def main_import_frames():
    return {'main-import/origin.commit','main-import/origin.tree'}|{
        'main-import/bodies/'+path for path in MAIN_IMPORT_ENTRIES}


def verify_main_import(frames):
    previous=source_tree(frames['current-import/origin.tree'])
    origin=source_tree(frames['main-import/origin.tree'])
    require(h.tree_hash(origin)==MAIN_IMPORT['origin_tree'],'fixed new main origin tree')
    source_commit(frames['main-import/origin.commit'],MAIN_IMPORT['origin'],origin,MAIN_IMPORT['origin_parents'])
    changed={p for p in set(previous)|set(origin) if previous.get(p)!=origin.get(p)}
    require(changed==set(MAIN_IMPORT_ENTRIES) and origin==previous|MAIN_IMPORT_ENTRIES,'exact new main three-path origin overlay')
    bodies={p:frames['main-import/bodies/'+p] for p in MAIN_IMPORT_ENTRIES}
    require(all(h.git_hash('blob',raw)==MAIN_IMPORT_ENTRIES[p][1] for p,raw in bodies.items()),'authenticated new main import bodies')
    return MAIN_IMPORT_ENTRIES,bodies


def verify_main_transition(frames,raw,previous,tail,renderer):
    source_commit(raw,MAIN_IMPORT['applied'],tail,[MAIN_IMPORT['preceding']])
    source_commit(frames['ancestry/'+MAIN_IMPORT['preceding']+'.commit'],MAIN_IMPORT['preceding'],previous)
    origin=source_tree(frames['main-import/origin.tree'])
    old_origin=source_tree(frames['current-import/origin.tree'])
    changed={p for p in set(previous)|set(tail) if previous.get(p)!=tail.get(p)}
    require(h.tree_hash(tail)==MAIN_IMPORT['applied_tree'] and
            changed==set(MAIN_IMPORT_ENTRIES) and tail==previous|MAIN_IMPORT_ENTRIES,
            'one exact new main import overlay')
    require(not renderer&origin.keys() and tail==origin|{p:previous[p] for p in renderer},'complete new main and renderer union')
    restored={p:row for p,row in tail.items() if p not in MAIN_IMPORT_ENTRIES}|{
        p:old_origin[p] for p in MAIN_IMPORT_ENTRIES if p in old_origin}
    require(restored==previous,'new main import inverse to preceding generation')


def verify_source_data(m,frames,base,tooling,imports,current):
    require(m.get('source_admission') in (LEGACY_SOURCE_ADMISSION,SOURCE_ADMISSION,MAIN_SOURCE_ADMISSION),'required fixed source admission tag')
    new_main=m['source_admission']==MAIN_SOURCE_ADMISSION
    current_main=m['source_admission'] in (SOURCE_ADMISSION,MAIN_SOURCE_ADMISSION)
    require(m['base']==BASE and m['paths'] in (PATHS,CENSUS_PATHS),'frozen measured source contract')
    chain=m['generation_ancestry'];commits={revision:frames['ancestry/'+revision+'.commit'] for revision in chain}
    source_ancestry(m,commits)
    tail_revisions=chain[chain.index(ACCEPTED_MAIN['merge'])+1:]
    expected_frames=fixed_import_frames()|{name+suffix for name in ACCEPTED_MAIN for suffix in ('.commit','.tree')}|{'base.commit','head.commit','head.tree','paths'}|{'ancestry/'+revision+'.commit' for revision in chain}|{'tail/'+revision+'.tree' for revision in tail_revisions}
    if current_main:expected_frames|=current_import_frames()
    if new_main:expected_frames|=main_import_frames()
    require(set(frames)==expected_frames,'closed complete source frame set')
    old_fixed,new_fixed,fixed_bodies=verify_fixed_import(frames)
    trees={name:source_tree(frames[name+'.tree']) for name in ACCEPTED_MAIN}
    for name,revision in ACCEPTED_MAIN.items():
        source_commit(frames[name+'.commit'],revision,trees[name],
                      [ACCEPTED_MAIN['renderer'],ACCEPTED_MAIN['main']] if name=='merge' else None)
    require(h.tree_hash(trees['merge'])==ACCEPTED_MERGE_TREE,'fixed accepted merge tree')
    delta=lambda a,b:{p for p in set(a)|set(b) if a.get(p)!=b.get(p)}
    renderer=delta(trees['common'],trees['renderer'])
    require(len(renderer)==27 and renderer<=trees['renderer'].keys() and not renderer&trees['main'].keys(),'complete disjoint renderer additions')
    require(trees['merge']==trees['main']|{p:trees['renderer'][p] for p in renderer},'complete fixed parent union')
    imported=delta(trees['renderer'],trees['merge'])
    require(len(imported)==82 and len(imported-trees['renderer'].keys())==73 and imported<=trees['merge'].keys() and not imported&renderer,'complete main import additions/modifications')
    require(set(imports)==imported,'complete main import bodies')
    for path,raw in imports.items():require(h.git_hash('blob',raw)==trees['merge'][path][1],'authenticated main import body')
    union=set(PATHS+CENSUS_PATHS)
    paths=frames['paths'].decode('utf-8').splitlines()
    require(len(paths)==len(set(paths)) and set(paths)==(set(MAIN_IMPORT_ENTRIES) if new_main else set())|(set(CURRENT_IMPORT_ENTRIES) if current_main else set())|set(FIXED_IMPORT_BLOBS)|imported|(set(CENSUS_PATHS) if m['paths']==CENSUS_PATHS else union),'complete acquired source delta')
    require(set(tooling)==union and union<=renderer,'complete seven current tooling bodies')
    base_entries={p:[mode,h.git_hash('blob',raw)] for p,(mode,raw) in base.items()}
    source_commit(frames['base.commit'],BASE,base_entries)
    require(h.tree_hash(base_entries)==BASE_TREE,'frozen measured base tree')
    require(trees['merge']==base_entries|{p:trees['merge'][p] for p in imported|union},'full frozen base/import/tooling provenance')
    entries=base_entries|{p:trees['merge'][p] for p in imported}|{p:['100644',h.git_hash('blob',raw)] for p,raw in tooling.items()}|new_fixed
    current_entries,current_bodies=verify_current_import(frames) if current_main else ({},{})
    entries|=current_entries
    main_entries,main_bodies=verify_main_import(frames) if new_main else ({},{})
    entries|=main_entries
    previous=trees['merge'];fixed_count=0;current_count=0;main_count=0
    for revision in tail_revisions:
        tail=source_tree(frames['tail/'+revision+'.tree'])
        source_commit(commits[revision],revision,tail)
        if revision==FIXED_IMPORT['applied']:
            fixed_count+=1
            source_commit(commits[revision],revision,tail,[FIXED_IMPORT['preceding']])
            require(h.tree_hash(tail)==FIXED_IMPORT['applied_tree'] and
                    all(previous.get(p)==row for p,row in old_fixed.items()) and
                    delta(previous,tail)==set(new_fixed) and tail==previous|new_fixed and
                    tail|old_fixed==previous,'one exact fixed import overlay and inverse')
        elif current_main and revision==CURRENT_IMPORT['applied']:
            current_count+=1
            verify_current_transition(frames,commits[revision],previous,tail,renderer)
        elif new_main and revision==MAIN_IMPORT['applied']:
            main_count+=1
            verify_main_transition(frames,commits[revision],previous,tail,renderer)
        else:require(delta(previous,tail)<=set(m['paths']),'allowed ordinary renderer tail paths')
        previous=tail
    require(fixed_count==1,'exactly one fixed import tail transition')
    require(current_count==int(current_main),'exactly one current main import tail transition')
    require(main_count==int(new_main),'exactly one new main import tail transition')
    require(previous==entries,'complete current controller source bodies')
    source_commit(frames['head.commit'],m['head'],entries)
    require(source_tree(frames['head.tree'])==entries,'actual current HEAD tree frame')
    bodies={p:raw for p,(_,raw) in base.items()}|imports|tooling|fixed_bodies|current_bodies|main_bodies
    expected={p:{'sha256':digest(bodies[p]),'mode':int(mode,8)&0o777} for p,(mode,_) in entries.items()}
    require(current==expected,'complete current checkout source identity')
    return entries


def retained_source_admission(out,m,complete=True):
    root=out/'controller';frames={p.relative_to(root).as_posix():p.read_bytes() for p in root.rglob('*') if p.is_file() and (p.suffix in ('.commit','.tree') or any(prefix in p.relative_to(root).as_posix() for prefix in ('fixed-import/bodies/','current-import/bodies/','main-import/bodies/')))}
    frames['paths']=(root/'paths').read_bytes()
    base={p:('100755' if row['mode']&0o111 else '100644',(out/'sources/base'/p).read_bytes()) for p,row in m['base_inventory'].items()}
    tooling={p:(out/'tooling'/p).read_bytes() for p in sorted(set(PATHS+CENSUS_PATHS))}
    for p,raw in tooling.items():require(raw==(ROOT/p).read_bytes(),'source-bound current reader tooling')
    imports={p.relative_to(root/'imports').as_posix():p.read_bytes() for p in (root/'imports').rglob('*') if p.is_file()}
    before=load_json((out/'controller-source-before.json').read_bytes())
    if complete:require(before==load_json((out/'controller-source-after.json').read_bytes()),'current source before/after identity')
    entries=verify_source_data(m,frames,base,tooling,imports,before)
    require(checkout_inventory(entries)==before,'source-bound current reader checkout')
    return entries


def checkout_inventory(entries):
    result={}
    for path,(mode,_) in entries.items():
        source=ROOT/path
        require(not source.is_symlink() and source.is_file() and source.stat().st_nlink==1,'ordinary current checkout member')
        actual=source.stat().st_mode&0o777
        if sys.platform=='win32':actual=int(mode,8)&0o777
        result[path]={'sha256':digest(source.read_bytes()),'mode':actual}
    return result


def acquire_source_admission(out,m,env):
    root=out/'controller';root.mkdir()
    def acquire(label,argv,dest):
        require(record(out,label,argv,ROOT,env)['status']==0,'controller source identity command')
        dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(out/(label+'.stdout'),dest)
    if m['source_admission'] in (SOURCE_ADMISSION,MAIN_SOURCE_ADMISSION):
        acquire('current-import-origin-commit',['git','cat-file','commit',CURRENT_IMPORT['origin']],root/'current-import/origin.commit')
        acquire('current-import-origin-tree',['git','ls-tree','-rz','--full-tree',CURRENT_IMPORT['origin']],root/'current-import/origin.tree')
        for path,(_,oid) in CURRENT_IMPORT_ENTRIES.items():
            acquire('current-import-body-'+digest(path.encode()),['git','cat-file','blob',oid],root/'current-import/bodies'/path)
    if m['source_admission']==MAIN_SOURCE_ADMISSION:
        acquire('main-import-origin-commit',['git','cat-file','commit',MAIN_IMPORT['origin']],root/'main-import/origin.commit')
        acquire('main-import-origin-tree',['git','ls-tree','-rz','--full-tree',MAIN_IMPORT['origin']],root/'main-import/origin.tree')
        for path,(_,oid) in MAIN_IMPORT_ENTRIES.items():
            acquire('main-import-body-'+digest(path.encode()),['git','cat-file','blob',oid],root/'main-import/bodies'/path)
    for name in ('parent','origin'):
        revision=FIXED_IMPORT[name]
        acquire('fixed-import-'+name+'-commit',['git','cat-file','commit',revision],root/'fixed-import'/(name+'.commit'))
        acquire('fixed-import-'+name+'-tree',['git','ls-tree','-rz','--full-tree',revision],root/'fixed-import'/(name+'.tree'))
    for path,(_,oid) in FIXED_IMPORT_BLOBS.items():
        acquire('fixed-import-body-'+digest(path.encode()),['git','cat-file','blob',oid],root/'fixed-import/bodies'/path)
    for name,revision in ACCEPTED_MAIN.items():
        acquire('controller-'+name+'-commit',['git','cat-file','commit',revision],root/(name+'.commit'))
        acquire('controller-'+name+'-tree',['git','ls-tree','-rz','--full-tree',revision],root/(name+'.tree'))
    shutil.copyfile(out/'base.commit',root/'base.commit');shutil.copyfile(out/'head.commit',root/'head.commit')
    shutil.copyfile(out/'git-paths.stdout',root/'paths')
    acquire('controller-current-tree',['git','ls-tree','-rz','--full-tree','HEAD'],root/'head.tree')
    for revision in m['generation_ancestry']:
        dest=root/'ancestry'/(revision+'.commit');dest.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(out/'ancestry'/(revision+'.commit'),dest)
    chain=m['generation_ancestry'];require(ACCEPTED_MAIN['merge'] in chain,'required accepted-main generation')
    for revision in chain[chain.index(ACCEPTED_MAIN['merge'])+1:]:
        acquire('controller-tail-'+revision,['git','ls-tree','-rz','--full-tree',revision],root/'tail'/(revision+'.tree'))
    renderer=source_tree((root/'renderer.tree').read_bytes());merged=source_tree((root/'merge.tree').read_bytes())
    for path in sorted(set(renderer)|set(merged)):
        if renderer.get(path)!=merged.get(path):
            require(path in merged,'main source deletion prohibited')
            acquire('controller-import-'+digest(path.encode()),['git','cat-file','blob',merged[path][1]],root/'imports'/path)
    entries=source_tree((root/'head.tree').read_bytes())
    before=checkout_inventory(entries);write_json(out/'controller-source-before.json',before)
    return retained_source_admission(out,m,False)


def finish_source_admission(out,m,env):
    if env.get('MDS_CENSUS_CUSTODY'):
        census_custody(out)
        env=env.copy()
        env['MDS_CENSUS_DEADLINE']=str(previous.time.monotonic()+600)
    for label,argv in [('controller-final-head',['git','rev-parse','HEAD']),('controller-final-status',['git','status','--porcelain']),('controller-final-tree',['git','ls-tree','-rz','--full-tree','HEAD'])]:
        require(record(out,label,argv,ROOT,env)['status']==0,'final controller source identity command')
    require((out/'controller-final-head.stdout').read_text().strip()==m['head'] and not (out/'controller-final-status.stdout').read_bytes(),'final clean exact workflow HEAD')
    require((out/'controller-final-tree.stdout').read_bytes()==(out/'controller/head.tree').read_bytes(),'final actual HEAD tree unchanged')
    entries=source_tree((out/'controller/head.tree').read_bytes())
    write_json(out/'controller-source-after.json',checkout_inventory(entries))
    retained_source_admission(out,m)
    if env.get('MDS_CENSUS_CUSTODY'):
        # Synchronous source reads share the success bound; they are not preempted.
        require(previous.time.monotonic()<float(env['MDS_CENSUS_DEADLINE']),'diagnostic source finalization wall time ceiling reached')


def verify_sources(out,m):
    require('source_admission' in m or not (out/'controller').exists(),'current source admission cannot fall back to legacy')
    base=out/'sources/base';base_inv=c.source_inventory(base)
    require(base_inv==m['base_inventory'],'complete base source closure')
    entries={name:['100755' if row['mode']&0o111 else '100644',h.git_hash('blob',(base/name).read_bytes())] for name,row in base_inv.items()}
    h.commit_proof(out/'base.commit',BASE,entries)
    commit=(out/'base.commit').read_text();require(commit.splitlines()[0]=='tree '+BASE_TREE,'base tree identity')
    if 'source_admission' in m:
        entries=retained_source_admission(out,m)
        h.commit_proof(out/'head.commit',m['head'],entries)
    else:
        for path in PATHS:
            raw=(out/'tooling'/path).read_bytes();require(raw==(ROOT/path).read_bytes() and path not in entries,'six new tooling paths')
            entries[path]=['100644',h.git_hash('blob',raw)]
        h.commit_proof(out/'head.commit',m['head'],entries)
    generation_ancestry(out,m)
    require(input_manifest(inputs(lambda p:(base/p).read_bytes()))==m['inputs'],'closed input manifest')
    for row in inputs(lambda p:(base/p).read_bytes()):require((out/'inputs'/(row['id']+'.x')).read_bytes()==row['bytes'],'retained exact input bytes')
    require((base/'rust/crates/mds-math/src/estimate_table.rs').read_bytes()==(ROOT/'rust/crates/mds-math/src/estimate_table.rs').read_bytes(),'oracle uses authenticated unchanged table source')
    for build in m['builds']:
        variant,opt=build['variant'],build['optimization']
        changes,patches,expected=source_expected(base,variant=='observed',PureWindowsPath(m['input_root']),'/'+opt)
        require(build['patches']==patches and build['before']==expected==build['after'],'insertion/inverse/source-end binding')
        source=out/'sources'/build['id']
        if sys.platform=='win32':
            for path,row in expected.items():c.TRANSPORT_MODES[str((source/path).resolve())]=row['mode']
        require(c.source_inventory(source)==expected,'generated source drift')
        for path,rows in patches.items():
            raw=(source/path).read_bytes()
            for patch in reversed(rows):
                if patch.get('kind')=='optimization':
                    require(digest(raw)==patch['generated_sha256'],'optimization generated hash');raw=bytes.fromhex(patch['original_hex']);require(digest(raw)==patch['original_sha256'],'optimization inverse hash')
                else:raw=inverse(raw,patch)
            require(raw==(base/path).read_bytes(),'full file inverse')


def replay(out,archive=None):
    if archive:
        inventory=c.transport(archive,out)
        require(set(inventory)==set(previous.evidence_inventory(out))|{'seal.json'},'exact completed archive membership')
    seal=load_json((out/'seal.json').read_bytes())
    require(seal['schema']==SCHEMA and seal['files']==previous.evidence_inventory(out),'complete generation seal')
    m=load_json((out/'manifest.json').read_bytes())
    admit_manifest(m)
    verify_sources(out,m)
    require([b['id'] for b in m['builds']]==[v+'-'+opt for opt in ('Od','O2') for v in ('control','observed')],'actual build matrix')
    parsed={}
    for b in m['builds']:
        r=admit_recipe(m,b)
        directory=out/b['id'];opt=b['optimization'];source=r['source'];target=r['target']
        for label in ('configure','native-build','rust-build','mesh_dump','x_files','native','rust'):
            receipt,stdout,stderr=checked(directory,label)
            admit_command(receipt,r,label)
            if label in ('mesh_dump','x_files'):fixture_result(label,stdout,stderr)
            if label in ('native','rust'):
                binary=(directory/('floor_profile.exe' if label=='native' else 'rust-profile.exe')).read_bytes()
                require(receipt['executed_binary']=={'path':r['commands'][label][0],'sha256':digest(binary),'size':len(binary)},'executed retained binary receipt')
        _,build_stdout,build_stderr=checked(directory,'native-build')
        commands=native_commands(build_stdout,build_stderr,r)
        require(commands==b['actual_native_commands'],'retained parsed compile/archive/link commands')
        objects={}
        for path,row in b['objects'].items():
            h.safe_name(path);raw=(directory/'objects'/path).read_bytes();require(len(raw)==row['size'] and digest(raw)==row['sha256'],'compiled object bytes');objects[path]=raw
        original=native_provenance(commands,r,opt,objects,(directory/'mikudancestudio_core.lib').read_bytes())
        _,cargo_stdout,_=checked(directory,'rust-build')
        executable=cargo_binary(cargo_stdout,r,opt)
        require(b['original_native_binary']=={'path':original,'sha256':b['binaries']['floor_profile.exe']['sha256']} and b['original_rust_binary']=={'path':executable,'sha256':b['binaries']['rust-profile.exe']['sha256']},'derived produced/executed binary identity')
        require(set(b['binaries'])=={'floor_profile.exe','rust-profile.exe','d3dx9_43.dll'},'exact retained runtime binaries')
        for name,row in b['binaries'].items():
            raw=(directory/name).read_bytes();require(digest(raw)==row['sha256'] and len(raw)==row['size'],'binary/source binding');pe_exports(raw) if name=='d3dx9_43.dll' else require(raw[:2]==b'MZ','actual executable PE')
        _,nout,nerr=checked(directory,'native');require(not nerr,'native stderr');native=parse(nout,'native',b['variant']=='observed')
        _,rout,_=checked(directory,'rust');require(b'test result: ok. 1 passed; 0 failed; 0 ignored;' in rout,'one actual Rust unit probe with no ignored tests');rust=parse(rout,'rust',b['variant']=='observed')
        corpus_words((directory/'operations.bin').read_bytes())
        require(set(b['runtime_corpus'])=={'sha256','size','created_ns'} and b['runtime_corpus']['sha256']==digest(operation_corpus()) and b['runtime_corpus']['size']==152,'runtime corpus identity')
        creation=b['runtime_corpus']['created_ns'];require(type(creation) is int,'runtime corpus creation time')
        for label in ('native-build','rust-build'):require(checked(directory,label)[0]['end_ns']<=creation,'corpus created after both compilers completed')
        for label in ('native','rust'):require(creation<=checked(directory,label)[0]['start_ns'],'corpus existed before actual runtime read')
        if b['variant']=='observed':
            require(compiled_evidence(directory,(native,rust),r)==b['compiled_capture'],'required bounded executed-code capture')
        dll=native['dll'];raw=(directory/'d3dx9_43.dll').read_bytes();exports=pe_exports(raw)
        require(digest(raw)==dll['sha256'] and len(raw)==dll['size'] and dll['rvas']==[exports[n] for n in ('D3DXLoadMeshFromXW','D3DXVec3TransformCoord','D3DXVec3Transform')],'actual loaded DLL bytes/exports')
        parsed[b['id']]=(native,rust)
    results={}
    for opt in ('Od','O2'):
        control,observed=[parsed[v+'-'+opt] for v in ('control','observed')]
        for language in range(2):
            require([{k:row[k] for k in ('operation','matrix','point','words')} for row in control[language]['direct']]==[{k:row[k] for k in ('operation','matrix','point','words')} for row in observed[language]['direct']],'control/observed direct output invariance')
            for id,_,_ in CASES:
                a,b=control[language]['cases'][id],observed[language]['cases'][id]
                require(mesh(a['final'])==mesh(b['final']) ,'control/observed bitwise initialized final state')
            a,b=[p[language]['cases'] for p in (control,observed)]
            require(mesh(a['floor-top']['final'])!=mesh(a['floor-affine']['final']) and mesh(b['floor-top']['final'])!=mesh(b['floor-affine']['final']),'genuine normal-exit affine sensitivity')
            require([(row['owner'],row['output']) for row in control[language]['operations']]==[(row['owner'],row['output']) for row in observed[language]['operations']],'runtime control/observed endpoint invariance')
        results[opt]=classify(*observed)
    result={'schema':SCHEMA,'fp_observation_contract':FP_CONTRACT,'head':m['head'],'results':results,'hosted':'ExecutedWindowsOnly','profile_adoption':'NotAuthorized'}
    require(load_json((out/'result.json').read_bytes())==result,'rederived diagnostic result')
    return result


def run(out,build_root,toolchain,census_mode=False):
    require(sys.platform=='win32' and os.environ.get('GITHUB_ACTIONS')=='true','explicit hosted Windows execution only')
    require(build_root and toolchain and toolchain.is_file() and not out.exists() and not build_root.exists() and not out.is_relative_to(ROOT) and not build_root.is_relative_to(ROOT) and not out.is_relative_to(build_root) and not build_root.is_relative_to(out),'fresh external evidence/build roots')
    runner_temp=os.environ['RUNNER_TEMP']
    r=recipe(runner_temp,'control','Od',census_mode)
    require(PureWindowsPath(str(out))==PureWindowsPath(r['evidence']).parent and PureWindowsPath(str(build_root))==PureWindowsPath(runner_temp)/('closure-census-build' if census_mode else 'floor-profile-build') and PureWindowsPath(str(toolchain))==PureWindowsPath(runner_temp)/'floor-profile-deps/build/generators/conan_toolchain.cmake','fixed hosted roots/toolchain')
    out.mkdir(parents=True)
    if census_mode:write_json(out/'writer-custody.json',{'schema':CUSTODY_SCHEMA,'state':'no_writer_started','receipts':[]})
    build_root.mkdir(parents=True);env=os.environ.copy()
    if census_mode:
        env['MDS_CENSUS_DEADLINE']=str(previous.time.monotonic()+1200)
        env['MDS_CENSUS_CUSTODY']=str(out)
    scope=CENSUS_PATHS if census_mode else PATHS
    for label,argv in [('git-head',['git','rev-parse','HEAD']),('git-status',['git','status','--porcelain']),('git-paths',['git','diff','--name-only',CENSUS_BASE if census_mode else BASE,'HEAD']),('source-archive',['git','-c','tar.umask=0022','archive',BASE]),('base-commit',['git','cat-file','commit',BASE]),('head-commit',['git','cat-file','commit','HEAD'])]:
        require(record(out,label,argv,ROOT,env)['status']==0,'source identity command')
    head=(out/'git-head.stdout').read_text().strip()
    require(head==os.environ.get('GITHUB_SHA') and not (out/'git-status.stdout').read_bytes(),'clean exact workflow HEAD')
    shutil.copyfile(out/'source-archive.stdout',out/'base-source.tar');base=out/'sources/base'
    base_modes=c.safe_tar(out/'base-source.tar',base)
    for path,row in base_modes.items():c.TRANSPORT_MODES[str((base/path).resolve())]=row['mode']
    for name in ('base','head'):shutil.copyfile(out/(name+'-commit.stdout'),out/(name+'.commit'))
    require(record(out,'git-first-parent-ancestry',['git','rev-list','--first-parent','--reverse',PARENT+'..HEAD'],ROOT,env)['status']==0,'first-parent renderer generation ancestry command')
    chain=(out/'git-first-parent-ancestry.stdout').read_text().splitlines();(out/'ancestry').mkdir()
    source_history_bound(chain,head,True)
    for revision in chain:
        require(re.fullmatch('[0-9a-f]{40}',revision),'producer ancestry commit identity')
        label='ancestor-'+revision
        require(record(out,label,['git','cat-file','commit',revision],ROOT,env)['status']==0,'ancestor source identity command')
        shutil.copyfile(out/(label+'.stdout'),out/'ancestry'/(revision+'.commit'))
    for path in sorted(set(PATHS+CENSUS_PATHS)):
        dest=out/'tooling'/path;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(ROOT/path,dest)
    input_root=Path(r['input_root']);input_root.mkdir();rows=inputs(lambda p:(base/p).read_bytes())
    for row in rows:(input_root/(row['id']+'.x')).write_bytes(row['bytes'])
    m={'schema':CENSUS_SCHEMA if census_mode else SCHEMA,'fp_observation_contract':FP_CONTRACT,'runner_temp':runner_temp,'base':BASE,'head':head,'paths':scope,'input_root':str(input_root),'inputs':input_manifest(rows),'base_inventory':c.source_inventory(base),'builds':[],
       'operation_corpus':{'sha256':digest(operation_corpus()),'size':152,'words':corpus_words(operation_corpus())},'generation_ancestry':chain,'source_admission':MAIN_SOURCE_ADMISSION,
       'configuration_differences':'Native Release in both modes, appended /Od or /O2 on core and console; Rust dev versus release defaults, opt-level/debug assertions/overflow/debuginfo differ. Observed copies add private sink calls. Both copies include coarse private MXCSR snapshots with operation ordering unproved.'}
    acquire_source_admission(out,m,env)
    if census_mode:m['manifest_representation']=CENSUS_MANIFEST_REPRESENTATION
    parsed={};variant_results={};document_receipts={}
    for opt in ('Od','O2'):
        for variant in ('control','observed'):
            r=recipe(runner_temp,variant,opt,census_mode);commands=r['commands']
            id=r['id'];directory=Path(r['evidence']);directory.mkdir();source=Path(r['source'])
            census=ClosureCensus() if census_mode else None
            if census_mode:env['MDS_CENSUS_DEADLINE']=str(census.started+CENSUS_LIMITS['seconds'])
            try:
                shutil.copytree(base,source)
                changes,patches,expected=source_expected(base,variant=='observed',input_root,'/'+opt,census_mode)
                for path,raw in changes.items():(source/path).write_bytes(raw)
                for path,row in expected.items():c.TRANSPORT_MODES[str((source/path).resolve())]=row['mode']
                require(c.source_inventory(source)==expected,'generated source initial closure')
                if census_mode:
                    write_json(directory/'source-before.json',expected)
                    write_json(directory/'source-inverses.json',patches)
                native_target=Path(r['native_target']);target=Path(r['target'])
                e=env|{'CARGO_TARGET_DIR':str(target),'CARGO_INCREMENTAL':'0','CARGO_TERM_COLOR':'never','RUSTFLAGS':RUST_FLAGS,'CL':'','_CL_':''}
                for label in ('configure','native-build'):
                    require(record(directory,label,commands[label],source,e,2400)['status']==0,'native '+label+' failure is not SemanticDifference')
                shutil.copyfile(native_target/'Release/floor_profile.exe',directory/'floor_profile.exe')
                actual=native_commands((directory/'native-build.stdout').read_bytes(),(directory/'native-build.stderr').read_bytes(),r)
                shutil.copyfile(native_target/'Release/mikudancestudio_core.lib',directory/'mikudancestudio_core.lib')
                require(record(directory,'rust-build',commands['rust-build'],source/'rust',e)['status']==0,'Rust build')
                executable=cargo_binary((directory/'rust-build.stdout').read_bytes(),r,opt)
                shutil.copyfile(executable,directory/'rust-profile.exe')
                shutil.copyfile(native_target/'Release/floor_profile.map',directory/'native.map')
                shutil.copyfile(Path(executable).with_suffix('.map'),directory/'rust.map')
                (directory/'operations.bin').write_bytes(operation_corpus());creation=previous.time.time_ns()
                binaries={}
                for name in ('floor_profile.exe','rust-profile.exe'):
                    raw=(directory/name).read_bytes();binaries[name]={'sha256':digest(raw),'size':len(raw)}
                b={'id':id,'variant':variant,'optimization':opt,'source':str(source),'target':str(target),'evidence':str(directory),'commands':commands,'patches':patches,'before':expected,'actual_native_commands':actual,'binaries':binaries,'original_native_binary':{'path':str(native_target/'Release/floor_profile.exe'),'sha256':digest((native_target/'Release/floor_profile.exe').read_bytes())},'original_rust_binary':{'path':executable,'sha256':digest(Path(executable).read_bytes())}}
                b['runtime_corpus']={'sha256':digest(operation_corpus()),'size':152,'created_ns':creation}
                m['builds'].append(b);write_json(out/'manifest.json',m)
                require(record(directory,'native',commands['native'],source,e,300)['status']==0,'native normal exit required')
                native=parse((directory/'native.stdout').read_bytes(),'native',variant=='observed')
                shutil.copyfile(native['dll']['path'],directory/'d3dx9_43.dll')
                require(record(directory,'rust',commands['rust'],source/'rust',e,300)['status']==0,'Rust probe normal exit')
                rust=parse((directory/'rust.stdout').read_bytes(),'rust',variant=='observed')
                for test in ('mesh_dump','x_files'):
                    require(record(directory,test,commands[test],source/'rust',e)['status']==0,'unchanged fixture contract '+test)
                    fixture_result(test,(directory/(test+'.stdout')).read_bytes(),(directory/(test+'.stderr')).read_bytes())
                require(c.source_inventory(source)==expected,'source end drift')
                objects={}
                for object_path in sorted(native_target.rglob('*.obj')):
                    relative=object_path.relative_to(native_target).as_posix()
                    retained=directory/'objects'/relative;retained.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(object_path,retained)
                    raw=retained.read_bytes();objects[relative]={'sha256':digest(raw),'size':len(raw)}
                require(any(path.endswith('/accessory.obj') for path in objects) and any(path.endswith('/native.obj') for path in objects),'actual core and console object files')
                raw=(directory/'d3dx9_43.dll').read_bytes();binaries['d3dx9_43.dll']={'sha256':digest(raw),'size':len(raw)}
                b.update(after=c.source_inventory(source),objects=objects)
                write_json(out/'manifest.json',m)
                if census_mode:
                    summary,receipt=census_evidence(directory,(native,rust),r,e,census)
                    variant_results[id]=summary['status']
                    document_receipts[id+'/closure-census.json']=receipt
                    if receipt['kind']=='complete':
                        b['closure_census']={'graph_schema':CENSUS_SCHEMA,'status':summary['status'],
                            **{key:receipt[key]|{'name':id+'/'+receipt[key]['name']} for key in ('binding','original')}}
                    del summary
                    write_json(out/'manifest.json',m)
                elif variant=='observed':
                    b['compiled_capture']=compiled_evidence(directory,(native,rust),r,True,e)
                    write_json(out/'manifest.json',m)
                parsed[id]=(native,rust)
            except (ValueError,OSError,KeyError,IndexError,struct.error) as error:
                if not census_mode:raise
                variant_results[id]='CENSUS_INCOMPLETE_UNRESOLVED'
                write_json(directory/'variant-failure.json',{'schema':CENSUS_SCHEMA,'error':str(error),'status':variant_results[id]})
            finally:
                if census_mode:
                    custody=census_custody(out)
                    if source.exists():write_json(directory/'source-after.json',c.source_inventory(source))
                    receipts=[name for name in custody['receipts'] if Path(name).parent==Path(id)]
                    write_json(directory/'variant-closure.json',{'schema':CENSUS_SCHEMA,'writers_closed':True,'command_count':len(receipts),'classification':'closed_commands' if receipts else 'no_writer_started','status':variant_results.get(id,'CENSUS_INCOMPLETE_UNRESOLVED')})
                    write_json(out/'manifest.json',m)
    finish_source_admission(out,m,env)
    if census_mode:
        return finish_census_documents(out,m,variant_results,document_receipts)
    result={'schema':SCHEMA,'fp_observation_contract':FP_CONTRACT,'head':head,'results':{opt:classify(*parsed['observed-'+opt]) for opt in ('Od','O2')},'hosted':'ExecutedWindowsOnly','profile_adoption':'NotAuthorized'}
    write_json(out/'result.json',result);write_json(out/'seal.json',{'schema':SCHEMA,'files':previous.evidence_inventory(out)})
    return replay(out)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run',action='store_true')
    parser.add_argument('--closure-census',action='store_true')
    parser.add_argument('--custody-check',action='store_true')
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--archive',type=Path)
    parser.add_argument('--build-root',type=Path)
    parser.add_argument('--toolchain',type=Path)
    parser.add_argument('--bundle',type=Path)
    args=parser.parse_args();out=args.out.resolve()
    if args.custody_check:
        require(not any((args.run,args.closure_census,args.archive,args.build_root,args.toolchain,args.bundle)),'custody check only')
        print(json.dumps(census_custody(out),sort_keys=True));return
    require(not args.closure_census or args.run,'diagnostic acquisition requires explicit hosted --run')
    if args.run:
        require(args.archive is None,'hosted run creates its own complete generation')
        result=run(out,args.build_root.resolve() if args.build_root else None,args.toolchain,args.closure_census)
        if args.bundle:result=result|{'bundle':c.bundle(out,args.bundle.resolve())}
    else:
        require(not any((args.build_root,args.toolchain,args.bundle)),'default replay cannot request effects')
        readonly();result=replay(out,args.archive)
    print(json.dumps(result,sort_keys=True))


if __name__=='__main__':
    try:main()
    except (ValueError,KeyError,IndexError,OSError,struct.error,tarfile.TarError) as error:
        print(json.dumps({'result':'IncompleteDiagnostic' if '--run' in sys.argv else 'InvalidEvidence','error':str(error)}),file=sys.stderr);sys.exit(1)
