import unittest
from pathlib import Path
import yaml
import os,json,tempfile,base64,subprocess,sys

class QAFarmTests(unittest.TestCase):
 def test_qa_gate_before_signing_and_fixed_tasks(self):
  w=yaml.safe_load(Path('.github/workflows/public-farm-mobile.yml').read_text())
  steps=w['jobs']['build']['steps']; names=[s.get('name') for s in steps]
  self.assertLess(names.index('Validate isolated QA public inputs'),names.index('Configure registered native Android internal signing'))
  build=next(s for s in steps if s.get('name')=='Build native Android artifact with Gradle')['run']
  self.assertIn('tasks=(:qualifyCreatorEarnings :tests-e2e:assembleDebug)',build)
  self.assertIn('"${tasks[@]}"',build)
  upload=next(s for s in steps if s.get('name')=='Upload mobile artifact')
  self.assertIn("qa != 'true'",upload['if'])
  self.assertTrue(any(s.get('name')=='Upload verified isolated QA artifacts' and "success()" in s['if'] for s in steps))

 def test_execute_input_guard_rejects_invalid_qa_before_source_scripts(self):
  steps=yaml.safe_load(Path('.github/workflows/public-farm-mobile.yml').read_text())['jobs']['resolve']['steps']
  source=steps[0]['run'].split("python3 <<'PY'\n",1)[1].rsplit('\nPY',1)[0]
  qa={'enabled':True,'run_id':'qa-farm-test','origin':'https://localhost:18443/','ca_pem_base64':base64.b64encode(b'-----BEGIN CERTIFICATE-----\nYQ==\n-----END CERTIFICATE-----\n').decode()}
  # Structure guard only: cryptographic validation occurs after exact checkout, before signing.
  def run(change=None, envchange=None):
   with tempfile.TemporaryDirectory() as d:
    env=os.environ.copy();env.update({'QA_PAYLOAD':json.dumps(qa|(change or {})),'REF_PAYLOAD':'a'*40,'SHA_PAYLOAD':'a'*40,'PROFILE_PAYLOAD':'internal','PLATFORMS_PAYLOAD':'"android"','GITHUB_OUTPUT':str(Path(d)/'output')})
    env.update(envchange or {})
    return subprocess.run([sys.executable,'-c',source],env=env,capture_output=True)
  self.assertEqual(run().returncode,0)
  for change in ({'enabled':False},{'origin':'https://evil/'},{'run_id':'qa-x'},{'ca_pem_base64':'bad'},{'private_key':'never'}):
   self.assertNotEqual(run(change).returncode,0)
  for env in ({'REF_PAYLOAD':'main'},{'SHA_PAYLOAD':'b'*40},{'PROFILE_PAYLOAD':'production'},{'GRADLE_TASK_PAYLOAD':':app:installInternalDebug'},{'PLATFORMS_PAYLOAD':'"all"'}):
   self.assertNotEqual(run(envchange=env).returncode,0)

if __name__=='__main__': unittest.main()
