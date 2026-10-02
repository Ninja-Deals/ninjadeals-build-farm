"""Execute release request validation and image receipt generation offline."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

import yaml

WORKFLOW = Path('.github/workflows/public-farm-build.yml')


class ProductionReleaseTest(unittest.TestCase):
    def setUp(self):
        self.workflow = yaml.safe_load(WORKFLOW.read_text())
        self.jobs = self.workflow['jobs']
        script = next(s['run'] for s in self.jobs['setup']['steps'] if s.get('id') == 'request')
        self.validation = script.split("python3 - <<'PY'\n", 1)[1].rsplit('\nPY', 1)[0]

    def validate(self, **overrides):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'output'
            env = dict(os.environ, REQUESTED_SOURCE='a'*40, REQUESTED_SERVICES='frontend',
                       PAYLOAD_SERVICES='null', BUILD_ONLY='false', DEPLOYMENT_MODE='apply',
                       GITHUB_OUTPUT=str(output))
            env.update(overrides)
            result = subprocess.run([sys.executable, '-c', self.validation], env=env,
                                    capture_output=True, text=True, timeout=10)
            data = dict(line.split('=', 1) for line in output.read_text().splitlines()) if output.exists() else {}
            return result, data

    def test_apply_dry_run_and_build_only_are_distinct_valid_modes(self):
        for mode, only in [('apply', 'false'), ('dry-run', 'false'), ('apply', 'true')]:
            result, data = self.validate(DEPLOYMENT_MODE=mode, BUILD_ONLY=only)
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual(mode, data['deployment_mode'])
            self.assertEqual(only, data['build_only'])

    def test_all_retained_services_and_subsets_are_accepted(self):
        result, data = self.validate(REQUESTED_SERVICES='', REQUESTED_SOURCE='')
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(22, len(json.loads(data['matrix'])['service']))
        self.assertIn('interaction', data['services'])
        result, data = self.validate(REQUESTED_SERVICES='identity, frontend,interaction')
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual('identity,frontend,interaction', data['services'])

    def test_invalid_request_rejected_before_any_source_build_or_deploy(self):
        for values in ({'REQUESTED_SERVICES':'ranking'}, {'REQUESTED_SERVICES':'frontend-2'},
                       {'REQUESTED_SERVICES':'frontend,frontend'}, {'REQUESTED_SERVICES':'frontend,'},
                       {'REQUESTED_SERVICES':'$(touch injected)'}, {'REQUESTED_SOURCE':'main'},
                       {'REQUESTED_SOURCE':'a'*39}, {'DEPLOYMENT_MODE':'clean-data'},
                       {'BUILD_ONLY':'yes'}, {'REQUESTED_SERVICES':'','PAYLOAD_SERVICES':'"frontend"'},
                       {'REQUESTED_SERVICES':'','PAYLOAD_SERVICES':'[]'},
                       {'REQUESTED_SERVICES':'','PAYLOAD_SERVICES':'0'},
                       {'REQUESTED_SERVICES':'','PAYLOAD_SERVICES':'{}'}):
            with self.subTest(values=values):
                result, data = self.validate(**values)
                self.assertNotEqual(0, result.returncode)
                self.assertEqual({}, data)

    def test_repository_dispatch_list_is_allowlisted(self):
        result, data = self.validate(REQUESTED_SERVICES='', PAYLOAD_SERVICES='["frontend","bff"]')
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual('frontend,bff', data['services'])

    def test_pinned_source_and_digest_artifacts_are_used_for_every_build(self):
        setup_checkout = next(s for s in self.jobs['setup']['steps'] if s.get('uses') == 'actions/checkout@v6')
        self.assertIn("'main'", setup_checkout['with']['ref'])
        for job in ('build', 'deploy'):
            checkout = next(s for s in self.jobs[job]['steps'] if s.get('uses') == 'actions/checkout@v6')
            self.assertEqual('${{ needs.setup.outputs.source_ref }}', checkout['with']['ref'])
            self.assertFalse(checkout['with']['persist-credentials'])
        upload = next(s for s in self.jobs['build']['steps'] if s.get('uses') == 'actions/upload-artifact@v4')
        self.assertEqual('release-${{ matrix.service }}', upload['with']['name'])
        self.assertEqual('error', upload['with']['if-no-files-found'])
        download = next(s for s in self.jobs['deploy']['steps'] if s.get('uses') == 'actions/download-artifact@v4')
        self.assertNotIn('run-id', download['with'])
        self.assertEqual('release-*', download['with']['pattern'])

    def test_production_job_runs_for_dry_run_and_apply_only_build_only_skips(self):
        deploy = self.jobs['deploy']
        self.assertEqual("needs.setup.outputs.build_only != 'true'", deploy['if'])
        self.assertEqual(['setup', 'build'], deploy['needs'])
        self.assertEqual('production', deploy['environment'])
        self.assertEqual({'group':'production-retained','cancel-in-progress':False}, deploy['concurrency'])
        script = next(s['run'] for s in deploy['steps'] if s.get('name') == 'Prepare, review and deploy retained production')
        self.assertIn('--mode "$DEPLOYMENT_MODE"', script)
        self.assertIn('--services "$SELECTED_SERVICES"', script)
        text = WORKFLOW.read_text()
        for forbidden in ('LEGACY_STAGING_DEPLOY_ENABLED', 'docker compose', ':latest', 'bastion session list', '--clean-data', 'issues/comments'):
            self.assertNotIn(forbidden, text)
        self.assertEqual({'setup', 'build', 'deploy'}, set(self.jobs))
        self.assertNotIn('SSH_KEY', deploy['env'])
        key_step = next(s for s in deploy['steps'] if s.get('name') == 'Materialize existing deploy key')
        self.assertIn('SSH_KEY="$RUNNER_TEMP/production-deploy-key"', key_step['run'])
        self.assertIn('>> "$GITHUB_ENV"', key_step['run'])
        cleanup = next(s for s in deploy['steps'] if s.get('name') == 'Remove owned temporary key')
        self.assertIn('"$RUNNER_TEMP/production-deploy-key"', cleanup['run'])
        names = [s.get('name') for s in deploy['steps']]
        preflight = 'Verify production deployment preservation contracts'
        self.assertLess(names.index(preflight), names.index('Set up OCI CLI'))
        self.assertLess(names.index(preflight), names.index('Materialize existing deploy key'))
        self.assertEqual("python3 -m unittest discover -s scripts/deploy -p 'test_production_*.py'",
                         next(s['run'] for s in deploy['steps'] if s.get('name') == preflight))

    def test_actual_build_command_generates_service_bound_digest_receipt(self):
        git_bash = Path('C:/Program Files/Git/bin/bash.exe')
        bash = str(git_bash) if git_bash.exists() else shutil.which('bash')
        jq_dir = Path('C:/Users/yuvar/.cache/ninja-back-tools')
        if not bash: self.skipTest('bash unavailable')
        script = next(s['run'] for s in self.jobs['build']['steps'] if s.get('name','').startswith('Build and Push'))
        for service in ('frontend', 'interaction', 'reputation'):
            with self.subTest(service=service), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                docker = root / 'docker'
                docker.write_text('''#!/usr/bin/env bash
set -euo pipefail
printf '%s\\n' "$@" > "$DOCKER_CALL"
while [ "$1" != --metadata-file ]; do shift; done
printf '{"containerimage.digest":"sha256:%s"}' "$(printf b%.0s {1..64})" > "$2"
''')
                docker.chmod(0o755)
                path = directory + os.pathsep + (str(jq_dir) + os.pathsep if jq_dir.exists() else '') + os.environ['PATH']
                env = dict(os.environ, SERVICE=service, PRIVATE_SOURCE='a'*40, GITHUB_RUN_ID='123',
                           GITHUB_RUN_ATTEMPT='2', RUNNER_TEMP=directory, OLA_KEY='unused', VAPID_KEY='unused',
                           DOCKER_CALL=str(root/'call'), PATH=path)
                result = subprocess.run([bash, '-c', script], env=env, capture_output=True, text=True, timeout=15)
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertEqual({'service':service, 'source_ref':'a'*40,
                                  'image':f'ghcr.io/ninja-deals/ninjadeals-main/{service}@sha256:'+'b'*64},
                                 json.loads((root/'release'/f'{service}.json').read_text()))
                self.assertNotIn(':latest', (root/'call').read_text())
                self.assertIn(f'{service}-'+ 'a'*40 + '-123-2', (root/'call').read_text())


if __name__ == '__main__':
    unittest.main()
