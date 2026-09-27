"""Offline safety checks for explicitly scoped build-only workflow requests."""
import fnmatch
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

import yaml


class IsolatedReputationBuildTest(unittest.TestCase):
    def setUp(self):
        self.workflow = yaml.safe_load(Path('.github/workflows/public-farm-build.yml').read_text())
        self.jobs = self.workflow['jobs']
        self.validation = next(s['run'] for s in self.jobs['setup']['steps'] if s.get('id') == 'isolated')
        self.source = 'a' * 40

    def validate(self, *, service='reputation', source=None, build_only='true', event='workflow_dispatch'):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'output'
            env = dict(os.environ, EVENT_NAME=event, REQUESTED_SERVICES=service,
                       REQUESTED_SOURCE=self.source if source is None else source,
                       BUILD_ONLY=build_only, GITHUB_OUTPUT=str(output))
            result = subprocess.run(['bash', '-c', self.validation], env=env, capture_output=True, text=True, timeout=5)
            return result, output.read_text() if output.exists() else ''

    def test_reputation_and_existing_single_services_are_isolated(self):
        for service in ('identity', 'deal', 'notification', 'discovery', 'bff', 'pricing', 'frontend', 'user-profile', 'reputation'):
            with self.subTest(service=service):
                result, output = self.validate(service=service)
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertEqual(f'isolated_build=true\nsource_ref={self.source}\n', output)

    def test_invalid_requests_fail_before_matrix_or_build(self):
        for args in ({'service': 'reputation,bff'}, {'service': 'all'}, {'source': ''},
                     {'source': 'main'}, {'source': self.source[:-1]}, {'build_only': 'false'},
                     {'event': 'push'}, {'event': 'repository_dispatch'}):
            with self.subTest(args=args):
                result, output = self.validate(**args)
                self.assertNotEqual(0, result.returncode)
                self.assertEqual('', output)

    def test_reputation_build_emits_pinned_tag_and_digest_without_latest(self):
        step = next(s for s in self.jobs['build']['steps'] if s.get('name', '').startswith('Build and Push'))
        script = step['run'].replace('${{ matrix.service }}', 'reputation')
        script = re.sub(r'\$\{\{ secrets\.[A-Z_]+ \}\}', 'unused', script)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            docker = root / 'docker'
            docker.write_text('''#!/usr/bin/env python3
import json, os, pathlib, sys
args=sys.argv[1:]
pathlib.Path(os.environ['DOCKER_CALL']).write_text(json.dumps(args))
pathlib.Path(args[args.index('--metadata-file')+1]).write_text(json.dumps({'containerimage.digest':'sha256:'+'b'*64}))
''')
            docker.chmod(0o755)
            env = dict(os.environ, ISOLATED_BUILD='true', PRIVATE_SOURCE=self.source,
                       GITHUB_RUN_ID='123', GITHUB_RUN_ATTEMPT='1', RUNNER_TEMP=directory,
                       DOCKER_CALL=str(root / 'call.json'), PATH=directory + os.pathsep + os.environ['PATH'])
            result = subprocess.run(['bash', '-c', script], env=env, capture_output=True, text=True, timeout=5)
            self.assertEqual(0, result.returncode, result.stderr)
            args = json.loads((root / 'call.json').read_text())
            image = f'ghcr.io/ninja-deals/ninjadeals-main/reputation:reputation-{self.source}-123-1'
            self.assertEqual(image, args[args.index('-t')+1])
            self.assertEqual('services/reputation/Dockerfile', args[args.index('-f')+1])
            self.assertIn('image_digest=sha256:' + 'b'*64, result.stdout)
            self.assertNotIn(':latest', result.stdout + ' '.join(args))

    def test_isolated_builds_skip_deployment_and_oci_jobs(self):
        for name, job in self.jobs.items():
            if name not in ('setup', 'build'):
                self.assertIn("needs.setup.outputs.isolated_build != 'true'", job['if'])

    def test_workflow_and_regression_only_push_does_not_start_service_builds(self):
        triggers = self.workflow.get('on', self.workflow.get(True))
        ignored = triggers['push']['paths-ignore']
        for path in ('.github/workflows/public-farm-build.yml', 'tests/test_isolated_reputation_build.py'):
            self.assertTrue(any(fnmatch.fnmatchcase(path, pattern) for pattern in ignored))


if __name__ == '__main__':
    unittest.main()
