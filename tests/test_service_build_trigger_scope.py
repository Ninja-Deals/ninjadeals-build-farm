import fnmatch
import unittest
from pathlib import Path

import yaml


class ServiceBuildTriggerScopeTest(unittest.TestCase):
    def setUp(self):
        workflow = yaml.safe_load(Path('.github/workflows/public-farm-build.yml').read_text())
        # PyYAML's YAML 1.1 loader parses the GitHub key `on` as boolean true.
        self.triggers = workflow.get('on', workflow.get(True))

    def push_triggers(self, paths):
        ignored = self.triggers['push']['paths-ignore']
        return any(not any(fnmatch.fnmatchcase(path, pattern) for pattern in ignored) for path in paths)

    def test_signing_maintenance_does_not_trigger_service_build_or_deploy(self):
        self.assertFalse(self.push_triggers(['tests/test_native_internal_signing.py']))
        self.assertFalse(self.push_triggers(['.github/workflows/public-farm-mobile.yml']))
        self.assertFalse(self.push_triggers([
            '.github/workflows/public-farm-mobile.yml',
            '.github/workflows/public-farm-build.yml',
            'tests/test_native_internal_signing.py',
            'tests/nested/test_signing.py',
        ]))

    def test_non_maintenance_push_and_explicit_build_requests_are_preserved(self):
        self.assertTrue(self.push_triggers(['build-service.sh', 'tests/test_native_internal_signing.py']))
        self.assertEqual(['main'], self.triggers['push']['branches'])
        self.assertEqual(['trigger-build'], self.triggers['repository_dispatch']['types'])
        self.assertEqual({'services', 'source_ref', 'build_only', 'deployment_mode'}, set(self.triggers['workflow_dispatch']['inputs']))


if __name__ == '__main__':
    unittest.main()
