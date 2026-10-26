"""Compile each wrong behavior and require a real native/Rust output difference."""
import json
from pathlib import Path
import re
from trace import compare


def once(source, old, new):
    if source.count(old) == 1:
        return source.replace(old,new)
    tokens = re.findall(r'"(?:\\.|[^"\\])*"|[A-Za-z_]\w*|\d+|[^\s]',old)
    pattern = r'\s*'.join(r',?\s*\)' if token == ')' else re.escape(token) for token in tokens)
    matches = list(re.finditer(pattern,source))
    if len(matches) != 1:
        raise ValueError(f'mutation anchor count {len(matches)}: {old!r}')
    return re.sub(pattern,lambda _:new,source,count=1)


def run_mutations(root, here, out, inputs, run, rust_command, suffix, native):
    solver = (root / 'rust/crates/mds-bullet/src/core/solver.rs').read_text()
    contact = (root / 'rust/crates/mds-bullet/src/core/contact_solver.rs').read_text()
    runner = (here / 'runner.rs').read_text()
    # These complete cases cover lazy registration, reversed bounds, zero impulse,
    # warmstart, both modes, factors, large normal impulse and consecutive solves.
    selected = {1,3,4,9,15,49,51,52,57,63}
    selected_lines = [line for line in inputs.read_text().splitlines() if int(line.split('\t')[0]) in selected]
    mutation_inputs = out / 'mutation-inputs.tsv';mutation_inputs.write_text('\n'.join(selected_lines)+'\n')
    baseline = run([native,mutation_inputs,out / 'mutation-baseline.trace'])
    mutations = []
    def add(name, s=solver, c=contact, r=runner):mutations.append((name,s,c,r))
    joint_start = solver.index('            for index in 0..self.joint_rows.len()')
    callback_start = solver.index('            for (joint, constraint) in joints.iter().enumerate()')
    contact_start = solver.index('            for index in 0..self.normals.len()')
    iterate_end = solver.index('\n        }\n    }\n\n    pub fn writeback',contact_start)
    contact_block = solver[contact_start:iterate_end]
    add('ten-joint-then-ten-contact',s=solver[:contact_start] + solver[iterate_end:iterate_end+10] + '\n        for iteration in 0..10 {\n' + contact_block + solver[iterate_end:])
    setup_call = '        build_rows(\n'
    begin = solver.index(setup_call); finish = solver.index('\n        solver\n',begin)
    build = solver[begin:finish]
    setup_loop = solver.index('        for joint in joints.iter_mut()')
    add('contact-setup-first',s=solver[:setup_loop]+build+'\n'+solver[setup_loop:begin]+solver[finish:])
    add('callback-preregister',s=solver[:begin]+'        for j in joints.iter() { for i in j.bodies { solver.bodies.get_or_init(bodies, i); } }\n'+solver[begin:])
    add('callback-omit',s=solver[:callback_start]+'            let _ = (bodies,joints);\n'+solver[contact_start:])
    add('duplicate-body',s=once(solver,'if let Some(id) = self.companions[original] {','if let Some(id) = None::<usize> {'))
    add('duplicate-writeback',s=solver.replace('state.linear_velocity.add(solver_body.delta_linear)','state.linear_velocity.add(solver_body.delta_linear).add(solver_body.delta_linear)'))
    for factor in ['0.0','1.0']:
        add('warmstart-'+factor,c=once(contact,'point.applied_impulse * 0.85','point.applied_impulse * '+factor))
    # The runner saves the actual previous solve's joint impulses and seeds the next.
    carry = once(runner,'  for step in 0..steps{','  let mut previous_impulses=Vec::new();\n  for step in 0..steps{')
    carry = once(carry,';emit(&mut trace,&format!("{case}\\t{step}\\t0\\t-1\\t-1")',';for (row,&impulse) in s.joint_rows.iter_mut().zip(&previous_impulses){row.applied_impulse=impulse;}emit(&mut trace,&format!("{case}\\t{step}\\t0\\t-1\\t-1")')
    carry = once(carry,'let mut end=snapshot(&s,&bodies,&manifolds);','previous_impulses=s.joint_rows.iter().map(|r|r.applied_impulse).collect();let mut end=snapshot(&s,&bodies,&manifolds);')
    add('carry-joint-impulse',r=carry)
    add('normal-upper-clamp',s=once(solver,'&mut self.normals[index].numeric,\n                    self.mode,\n                    true,','&mut self.normals[index].numeric,\n                    self.mode,\n                    false,'))
    add('wrong-mode',s=once(solver,'            mode,','            mode: { let _ = mode; SolverMode::Scalar },'))
    add('wrong-angular-factor',s=solver.replace('SolverMode::Simd => row.angular_components[0].scale(impulse),','SolverMode::Simd => product(row.angular_components[0], a.angular_factor.scale(impulse)),').replace('SolverMode::Simd => row.angular_components[1].scale(impulse),','SolverMode::Simd => product(row.angular_components[1], b.angular_factor.scale(impulse)),').replace('            mode,','            mode,'))
    add('friction-skip',s=once(solver,'if normal.numeric.applied_impulse > 0.0 {','if true {'))
    add('friction-order',s=once(solver,'for index in 0..self.frictions.len() {','for index in (0..self.frictions.len()).rev() {'))
    add('lateral-writeback',s=once(solver,'manifolds[mi].points[pi].applied_impulse = row.numeric.applied_impulse;','manifolds[mi].points[pi].applied_impulse = row.numeric.applied_impulse;\n            manifolds[mi].points[pi].lateral_impulses[0] = self.frictions[mi].numeric.applied_impulse;'))
    add('lifetime-writeback',s=once(solver,'manifolds[mi].points[pi].applied_impulse = row.numeric.applied_impulse;','manifolds[mi].points[pi].applied_impulse = row.numeric.applied_impulse;\n            manifolds[mi].points[pi].lifetime += 1;'))
    separate = once(runner,'GroupSolver::setup(&bodies,&mut joints,&mut manifolds,dt,mode)','GroupSolver::setup(&bodies,&mut joints,&mut [],dt,mode)')
    separate = once(separate,'s.writeback(&mut bodies,&mut manifolds);','s.writeback(&mut bodies,&mut manifolds);let mut contacts=GroupSolver::setup(&bodies,&mut [],&mut manifolds,dt,mode);contacts.iterate(&bodies,&[],|_,_|{});contacts.writeback(&mut bodies,&mut manifolds);')
    add('separate-full-solves',r=separate)
    reports = []
    for name, s, c, r in mutations:
        directory=out / 'mutations' / name;directory.mkdir(parents=True,exist_ok=True)
        sp=directory / 'solver.rs';cp=directory / 'contact_solver.rs';sp.write_text(s);cp.write_text(c)
        for relative in re.findall(r'#\[path = "([^"]+)"\]',r):
            path=sp if relative.endswith('/solver.rs') else cp if relative.endswith('/contact_solver.rs') else (here / relative).resolve()
            r=r.replace(json.dumps(relative),json.dumps(path.as_posix()))
        rp=directory / 'runner.rs';rp.write_text(r)
        label=str(directory / 'mutant')
        run(rust_command(rp,label))
        trace=directory / 'actual.trace';actual=run([Path(label+suffix),mutation_inputs,trace])
        (directory / 'actual.tsv').write_bytes(actual)
        difference=compare(out / 'mutation-baseline.trace',trace)
        if actual == baseline and difference is None:
            raise AssertionError(f'{name}: compiled mutation survived behavioral comparison')
        report={'mutation':name,'compiled':True,'stdout_equal':actual==baseline,'first_trace_difference':difference,'status':'CAUGHT'}
        reports.append(report);(directory / 'result.json').write_text(json.dumps(report,indent=2)+'\n')
        trace.unlink()
        print(name,'CAUGHT',difference)
    (out / 'mutations.json').write_text(json.dumps(reports,indent=2)+'\n')
