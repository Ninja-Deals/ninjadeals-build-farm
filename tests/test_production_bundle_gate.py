import unittest
from pathlib import Path
import yaml


class ProductionBundleGateTest(unittest.TestCase):
    def setUp(self):
        workflow = yaml.safe_load(Path('.github/workflows/public-farm-mobile.yml').read_text())
        self.steps = workflow['jobs']['build']['steps']

    def test_pinned_bundletool_is_prepared_before_production_build(self):
        step = next(s for s in self.steps if s.get('name') == 'Prepare pinned native Android production bundle inspection')
        self.assertIn("profile == 'production'", step['if'])
        self.assertIn("app_kind == 'native_android'", step['if'])
        self.assertIn('bundletool-all-1.18.3.jar', step['run'])
        self.assertIn('a099cfa1543f55593bc2ed16a70a7c67fe54b1747bb7301f37fdfd6d91028e29', step['run'])
        self.assertIn('sha256sum -c', step['run'])
        self.assertIn('NINJA_BUNDLETOOL_JAR=', step['run'])
        self.assertIn('NINJA_PRODUCTION_UPLOAD_CERT_SHA256=', step['run'])
        self.assertLess(self.steps.index(step), next(i for i, s in enumerate(self.steps) if s.get('name') == 'Build native Android artifact with Gradle'))

    def test_actual_uploaded_artifact_gets_manifest_native_and_exact_signer_gate(self):
        step = next(s for s in self.steps if s.get('name') == 'Enforce native Android production artifact policy')
        self.assertIn('inspect_production_bundle.py', step['run'])
        self.assertIn('--bundletool "$NINJA_BUNDLETOOL_JAR"', step['run'])
        self.assertIn('--upload-cert-sha256 "$NINJA_PRODUCTION_UPLOAD_CERT_SHA256"', step['run'])
        self.assertNotIn('jarsigner -verify -strict', step['run'])


if __name__ == '__main__':
    unittest.main()
