from pathlib import Path
import unittest
import yaml

class EarningsQualificationWorkflowTests(unittest.TestCase):
    def test_explicit_disposable_workflow_has_no_production_transport_or_messages(self):
        path=Path('.github/workflows/public-farm-earnings-qualification.yml')
        raw=path.read_text();workflow=yaml.safe_load(raw)
        trigger=workflow.get('on',workflow.get(True))
        self.assertEqual(set(trigger),{'workflow_dispatch'})
        self.assertEqual(set(trigger['workflow_dispatch']['inputs']),{'source_ref','build_run_id'})
        job=workflow['jobs']['qualify']
        self.assertEqual(job['runs-on'],'ubuntu-24.04-arm')
        self.assertEqual(job['timeout-minutes'],90)
        for forbidden in ('staging.ninja.deals','SSH_PRIVATE_KEY','OCI_','issues/','gh issue','deployment_mode','production-retained'):
            self.assertNotIn(forbidden,raw)
        checkout=next(step for step in job['steps'] if step.get('name')=='Checkout exact private source')
        self.assertFalse(checkout['with']['persist-credentials'])
        self.assertEqual(checkout['with']['ref'],'${{ inputs.source_ref }}')
        upload=job['steps'][-1]
        self.assertEqual(upload['with']['path'],'evidence/qualification.json')
        self.assertNotIn('compose.json',upload['with']['path'])

if __name__=='__main__':unittest.main()
