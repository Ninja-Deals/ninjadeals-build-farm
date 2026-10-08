from pathlib import Path
import unittest
import ast
import tempfile
import subprocess
import yaml

class EarningsQualificationWorkflowTests(unittest.TestCase):
    def test_explicit_disposable_workflow_has_no_production_transport_or_messages(self):
        path=Path('.github/workflows/public-farm-earnings-qualification.yml')
        raw=path.read_text();workflow=yaml.safe_load(raw)
        trigger=workflow.get('on',workflow.get(True))
        self.assertEqual(set(trigger),{'workflow_dispatch'})
        self.assertEqual(set(trigger['workflow_dispatch']['inputs']),{'source_ref','build_run_id','harness_ref'})
        job=workflow['jobs']['qualify']
        self.assertEqual(job['runs-on'],'ubuntu-24.04-arm')
        self.assertEqual(job['timeout-minutes'],90)
        for forbidden in ('staging.ninja.deals','SSH_PRIVATE_KEY','OCI_','issues/','gh issue','deployment_mode','production-retained'):
            self.assertNotIn(forbidden,raw)
        checkout=next(step for step in job['steps'] if step.get('name')=='Checkout exact private source')
        self.assertFalse(checkout['with']['persist-credentials'])
        self.assertEqual(checkout['with']['ref'],'${{ inputs.harness_ref || inputs.source_ref }}')
        self.assertEqual(checkout['with']['fetch-depth'],0)
        self.assertIn('--harness-ref "$HARNESS"',raw)
        self.assertIn('HARNESS: ${{ inputs.harness_ref || inputs.source_ref }}',raw)
        names=[step.get('name','') for step in job['steps']]
        self.assertLess(names.index('Prove unchanged application before source execution'),names.index('Install bounded fixture and browser tooling'))
        early=next(step for step in job['steps'] if step.get('name')=='Prove unchanged application before source execution')['run']
        self.assertNotIn('import earnings_',early)
        self.assertIn('"--no-renames"',early)
        self.assertIn('"merge-base","--is-ancestor"',early)
        upload=job['steps'][-1]
        self.assertEqual(set(upload['with']['path'].splitlines()),{'evidence/qualification.json','evidence/browser-summary.json','evidence/synthetic-*.png'})
        self.assertNotIn('compose.json',upload['with']['path'])

    def test_trusted_inline_guard_rejects_application_changes_before_imports(self):
        workflow=yaml.safe_load(Path('.github/workflows/public-farm-earnings-qualification.yml').read_text())
        raw=next(s['run'] for s in workflow['jobs']['qualify']['steps'] if s.get('name')=='Prove unchanged application before source execution')
        code=raw.split("python3 - <<'PY'\n",1)[1].rsplit('\nPY',1)[0]
        tree=ast.parse(code);tree.body=tree.body[:-1]
        namespace={};exec(compile(tree,'trusted-farm-guard','exec'),namespace)
        verify=namespace['verify_harness_revision']
        with tempfile.TemporaryDirectory() as d:
            repo=Path(d)
            def git(*args):return subprocess.check_output(['git','-C',str(repo),*args],text=True).strip()
            git('init','-q');git('config','user.name','fixture');git('config','user.email','fixture@example.invalid')
            (repo/'app-source').write_text('unchanged');git('add','.');git('commit','-qm','base');source=git('rev-parse','HEAD')
            test=repo/'tests/web-e2e/creator-earnings/safe-reporter.ts';test.parent.mkdir(parents=True);test.write_text('reviewed')
            git('add','.');git('commit','-qm','diagnostics');harness=git('rev-parse','HEAD')
            self.assertTrue(verify(repo,source,harness)['app_source_is_ancestor'])
            test.write_text('dirty')
            with self.assertRaises(ValueError):verify(repo,source,harness)
            git('add','.')
            with self.assertRaises(ValueError):verify(repo,source,harness)
            git('reset','--hard',harness)
            for name in ['cmd/healthcheck/main.go','services/earnings/main.go','frontend/package.json','.dockerignore','go.work','infra/compose/services.yml']:
                p=repo/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('changed');git('add','.');git('commit','-qm','changed')
                with self.assertRaises(ValueError):verify(repo,source,git('rev-parse','HEAD'))
                git('reset','--hard',harness)
            test.unlink();git('mv','app-source','tests/web-e2e/creator-earnings/safe-reporter.ts');git('add','.');git('commit','-qm','rename')
            with self.assertRaises(ValueError):verify(repo,source,git('rev-parse','HEAD'))

if __name__=='__main__':unittest.main()
