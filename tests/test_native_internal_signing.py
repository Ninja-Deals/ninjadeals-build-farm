import unittest
from pathlib import Path
import yaml


class NativeInternalSigningWorkflowTest(unittest.TestCase):
    def setUp(self):
        workflow = yaml.safe_load(Path('.github/workflows/public-farm-mobile.yml').read_text())
        self.steps = workflow['jobs']['build']['steps']

    def test_internal_signing_is_required_before_gradle_and_scoped_away_from_release(self):
        step = next(s for s in self.steps if s.get('name') == 'Configure registered native Android internal signing')
        self.assertIn("profile == 'internal'", step['if'])
        self.assertIn("app_kind == 'native_android'", step['if'])
        self.assertEqual('bash android/scripts/configure-ci-debug-signing.sh', step['run'])
        self.assertEqual(4, len(step['env']))
        self.assertTrue(all(v.startswith('${{ secrets.NINJADEALS_INTERNAL_') for v in step['env'].values()))
        self.assertLess(self.steps.index(step), next(i for i, s in enumerate(self.steps) if s.get('name') == 'Build native Android artifact with Gradle'))
        self.assertGreater(self.steps.index(step), next(i for i, s in enumerate(self.steps) if s.get('name') == 'Setup Java for Android'))

    def test_private_signing_directory_is_removed_even_when_build_fails(self):
        step = next(s for s in self.steps if s.get('name') == 'Remove native Android internal signing files')
        self.assertTrue(step['if'].startswith('always()'))
        self.assertIn('"$RUNNER_TEMP"/ninja-debug-signing-*', step['run'])
        self.assertIn('rm -rf -- "$NINJA_DEBUG_SIGNING_DIR"', step['run'])

    def test_existing_release_signing_custody_remains_separate(self):
        step = next(s for s in self.steps if s.get('name') == 'Configure native Android release signing')
        self.assertIn("profile == 'staging'", step['if'])
        self.assertIn("profile == 'production'", step['if'])
        self.assertNotIn('NINJADEALS_INTERNAL_', step['run'])


if __name__ == '__main__':
    unittest.main()
