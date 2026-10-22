"""Native iOS production signing and App Store Connect upload contract (no secrets, no runner)."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

import yaml

WORKFLOW = Path('.github/workflows/public-farm-native-ios.yml')
BASH = os.environ.get('NJD_TEST_BASH', shutil.which('bash'))
SHA = 'a' * 40


class NativeIOSReleaseWorkflowTest(unittest.TestCase):
    def setUp(self):
        self.text = WORKFLOW.read_text(encoding='utf-8')
        self.workflow = yaml.safe_load(self.text)
        self.steps = self.workflow['jobs']['build']['steps']
        self.names = [step.get('name') for step in self.steps]

    def step(self, name):
        return self.steps[self.names.index(name)]

    def resolve(self, **env):
        script = self.step('Resolve and validate inputs')['run']
        program = script.split("<<'PY'\n", 1)[1].rsplit('\nPY', 1)[0]
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / 'output'
            output.write_text('', encoding='utf-8')
            done = subprocess.run([sys.executable, '-c', program], capture_output=True, text=True,
                                  env={**os.environ, 'GITHUB_OUTPUT': str(output), **env})
            values = dict(line.split('=', 1) for line in output.read_text(encoding='utf-8').splitlines())
        return done, values

    def custody_check(self, **env):
        script = self.step('Check native iOS release custody')['run']
        clean = {k: v for k, v in os.environ.items() if not k.startswith(('IOS_', 'NINJADEALS_'))}
        return subprocess.run([BASH, '-c', script], capture_output=True, text=True, env={**clean, **env})

    def test_upload_is_explicit_production_only_and_pinned_to_an_exact_build(self):
        done, values = self.resolve(PROFILE_PAYLOAD='production', SHA_PAYLOAD=SHA, BUILD_PAYLOAD='8123',
                                    UPLOAD_PAYLOAD='true')
        self.assertEqual(0, done.returncode, done.stderr)
        self.assertEqual(('true', 'true', SHA), (values['upload'], values['signed'], values['sha']))
        done, values = self.resolve(PROFILE_INPUT='production', REF_INPUT=SHA, BUILD_INPUT='8123', UPLOAD_INPUT='true')
        self.assertEqual((0, 'true', SHA), (done.returncode, values.get('upload'), values.get('sha')))
        for case, env in {
            'staging': dict(PROFILE_PAYLOAD='staging', SHA_PAYLOAD=SHA, BUILD_PAYLOAD='1', UPLOAD_PAYLOAD='true'),
            'branch ref': dict(PROFILE_INPUT='production', REF_INPUT='main', BUILD_INPUT='1', UPLOAD_INPUT='true'),
            'shallow build number': dict(PROFILE_PAYLOAD='production', SHA_PAYLOAD=SHA, UPLOAD_PAYLOAD='true'),
            'unknown flag': dict(PROFILE_PAYLOAD='production', UPLOAD_PAYLOAD='yes'),
            'shell in ref': dict(PROFILE_PAYLOAD='production', REF_PAYLOAD="main' ; echo x '"),
            'prerelease version': dict(PROFILE_PAYLOAD='production', SHA_PAYLOAD=SHA, BUILD_PAYLOAD='1',
                                       VERSION_PAYLOAD='1.0.0-rc1', UPLOAD_PAYLOAD='true'),
        }.items():
            with self.subTest(case=case):
                done, values = self.resolve(**env)
                self.assertNotEqual(0, done.returncode)
                self.assertNotIn('upload', values)
        for env in (dict(PROFILE_PAYLOAD='production'), dict(PROFILE_INPUT='production', UPLOAD_INPUT='false')):
            with self.subTest(env=env):
                self.assertEqual('false', self.resolve(**env)[1]['upload'])

    @unittest.skipUnless(BASH, 'bash is required to execute the custody preflight')
    def test_custody_preflight_names_every_missing_secret_before_checkout(self):
        self.assertLess(self.names.index('Check native iOS release custody'), self.names.index('Checkout private monorepo'))
        signing = dict(IOS_TEAM_ID='ABCDE12345', IOS_DISTRIBUTION_CERTIFICATE_BASE64='x',
                       IOS_DISTRIBUTION_CERTIFICATE_PASSWORD='x', IOS_APP_PROVISIONING_PROFILE_BASE64='x',
                       IOS_SHARE_PROVISIONING_PROFILE_BASE64='x')
        google = dict(NINJADEALS_PRODUCTION_IOS_GOOGLE_CLIENT_ID='x', NINJADEALS_PRODUCTION_GOOGLE_SERVER_CLIENT_ID='x')
        upload = dict(IOS_ASC_KEY_ID='ABC123DEFG', IOS_ASC_ISSUER_ID='x', IOS_ASC_PRIVATE_KEY_BASE64='x',
                      IOS_ASC_APP_APPLE_ID='1')
        self.assertEqual(0, self.custody_check(PROFILE='production', UPLOAD='true', **signing, **google, **upload).returncode)
        self.assertEqual(0, self.custody_check(PROFILE='staging', UPLOAD='false', **signing).returncode)
        done = self.custody_check(PROFILE='production', UPLOAD='true', **signing)
        self.assertEqual(2, done.returncode)
        for name in (*google, *upload):
            self.assertIn(name, done.stdout)
        done = self.custody_check(PROFILE='production', UPLOAD='true', **signing, **google, **dict(upload, IOS_ASC_KEY_ID='../x'))
        self.assertEqual(2, done.returncode)

    def test_no_widget_keychain_or_export_options_custody_is_required(self):
        for retired in ('IOS_WIDGET_PROVISIONING_PROFILE_BASE64', 'IOS_BUILD_KEYCHAIN_PASSWORD',
                        'IOS_EXPORT_OPTIONS_PLIST_BASE64'):
            self.assertNotIn(retired, self.text)
        signing = self.step('Configure isolated Apple signing custody')
        self.assertIn('openssl rand', signing['run'])
        self.assertIn('ios/scripts/distribution.py export-options --profile "$PROFILE"', signing['run'])
        cleanup = self.step('Remove ephemeral signing material')['run']
        for directory in ('Library/Developer/Xcode/UserData/Provisioning Profiles',
                          'Library/MobileDevice/Provisioning Profiles'):
            self.assertIn(directory, signing['run'])
            self.assertIn(directory, cleanup)

    def test_signing_keychain_is_added_without_dropping_the_user_search_list(self):
        # Replacing the list hid the login keychain from the package Keychain tests that run
        # after signing setup (run 39729186753), so a production build failed its static gate.
        signing = self.step('Configure isolated Apple signing custody')['run']
        self.assertIn('security list-keychains -d user -s "$keychain" "${existing_keychains[@]}"', signing)
        self.assertNotIn('security list-keychains -d user -s "$keychain"\n', signing)

    def test_checkout_is_the_exact_commit_without_a_persisted_token(self):
        checkout = self.step('Checkout private monorepo')['with']
        self.assertEqual('${{ steps.inputs.outputs.sha || steps.inputs.outputs.ref }}', checkout['ref'])
        self.assertIs(checkout['persist-credentials'], False)

    def test_production_archive_receives_both_google_client_ids(self):
        env = self.step('Build signed device artifact')['env']
        self.assertEqual('${{ secrets.NINJADEALS_PRODUCTION_IOS_GOOGLE_CLIENT_ID }}', env['NJD_IOS_GOOGLE_CLIENT_ID'])
        self.assertEqual('${{ secrets.NINJADEALS_PRODUCTION_GOOGLE_SERVER_CLIENT_ID }}',
                         env['NJD_IOS_GOOGLE_SERVER_CLIENT_ID'])

    def test_upload_uses_a_temporary_key_removed_by_always_run_cleanup(self):
        upload = self.step('Upload production IPA to App Store Connect')
        self.assertEqual("steps.inputs.outputs.upload == 'true'", upload['if'])
        self.assertIn('keys="$RUNNER_TEMP/ninjadeals-asc-keys"', upload['run'])
        self.assertIn('umask 077', upload['run'])
        self.assertIn('ios/scripts/distribution.py upload', upload['run'])
        self.assertNotIn('upload-app', upload['run'])
        self.assertGreater(self.names.index(upload['name']), self.names.index('Upload native iOS artifact and dSYM archive'))
        cleanup = self.step('Remove ephemeral signing material')
        self.assertTrue(cleanup['if'].startswith('always()'))
        self.assertIn('"$RUNNER_TEMP/ninjadeals-asc-keys"', cleanup['run'])
        self.assertIn('"$RUNNER_TEMP/ninjadeals-ios-profiles"', cleanup['run'])
        self.assertEqual(self.names[-1], cleanup['name'])

    def test_public_artifacts_are_build_outputs_only(self):
        paths = self.step('Upload native iOS artifact and dSYM archive')['with']['path'].strip().splitlines()
        self.assertEqual(['${{ runner.temp }}/native-ios/*.ipa', '${{ runner.temp }}/native-ios/*.zip',
                          '${{ runner.temp }}/native-ios/build-metadata.json'], paths)

    def test_simulator_smoke_is_an_unsigned_read_only_production_build(self):
        # The staging BFF is retired: Smoke reads production anonymously and
        # never receives custody, fixtures or the staging app.
        self.assertNotIn('staging.ninja.deals', self.text)
        self.assertNotIn('com.ninjadeals.app.staging', self.text)
        build = self.step('Build unsigned simulator artifact')
        self.assertIn('--profile production', build['run'])
        self.assertIn('--unsigned-simulator', build['run'])
        smoke = self.step('Boot, install and launch simulator artifact')
        self.assertIn('Production-iphonesimulator/NinjaDeals.app', smoke['run'])
        self.assertIn('bundle=com.ninjadeals.app\n', smoke['run'])
        self.assertIn('--backend production', smoke['run'])
        self.assertIn('--severity smoke', smoke['run'])
        self.assertNotIn('--coordinate-fixtures', smoke['run'])
        for step in (build, smoke):
            self.assertNotIn('secrets.', str(step.get('env', {})))
        expected = self.step('Verify attributable Smoke runtime metadata')['run']
        for pinned in ("'backend': 'production'", "'backend_url': 'https://ninja.deals'",
                       "'app_bundle_identifier': 'com.ninjadeals.app'", "'plans': 'Smoke'",
                       "'selected_methods': 'LaunchJourneyTests/"
                       "test_US_IOS_001__supported_ios_launch_reaches_an_owned_native_experience'"):
            self.assertIn(pinned, expected)
        build_metadata = self.step('Verify attributable build metadata')['run']
        self.assertIn("'production' if os.environ['PROFILE'] == 'simulator'", build_metadata)

    @unittest.skipUnless(BASH, 'bash is required to stage the public Smoke evidence')
    def test_public_smoke_evidence_is_metadata_plus_only_a_passing_junit(self):
        # The xcresult and xcodebuild logs (raw or redacted) and failure text can
        # quote private source; a passing JUnit lists only test names.
        stage = self.step('Stage public Smoke evidence')
        self.assertTrue(stage['if'].startswith('always()'))
        self.assertEqual("${{ steps.smoke.outcome }}", stage['env']['SMOKE_OUTCOME'])
        self.assertEqual('smoke', self.step('Boot, install and launch simulator artifact')['id'])
        upload = self.step('Upload native iOS Smoke runtime evidence')['with']
        self.assertEqual('${{ runner.temp }}/native-ios-smoke-public', upload['path'].strip())
        for outcome, junit in (('success', True), ('failure', False)):
            with self.subTest(outcome=outcome), tempfile.TemporaryDirectory() as temp:
                lane = Path(temp) / 'native-ios-smoke/ios-e2e'
                for relative in ('metadata.env', 'retention.json', 'junit/smoke.xml',
                                 'publish/device-metadata.json', 'publish/Smoke.xcodebuild.log',
                                 'private/Smoke.xcodebuild.log', 'private/Smoke.xcresult/Info.plist'):
                    (lane / relative).parent.mkdir(parents=True, exist_ok=True)
                    (lane / relative).write_text('x', encoding='utf-8')
                done = subprocess.run([BASH, '-c', stage['run']], capture_output=True, text=True,
                                      env={**os.environ, 'RUNNER_TEMP': temp, 'SMOKE_OUTCOME': outcome})
                self.assertEqual(0, done.returncode, done.stderr)
                public = Path(temp) / 'native-ios-smoke-public'
                published = sorted(path.relative_to(public).as_posix() for path in public.rglob('*') if path.is_file())
                expected = ['metadata.env', 'publish/device-metadata.json'] + (['junit/smoke.xml'] if junit else [])
                self.assertEqual(sorted(expected), published)


class NativeIOSDiagnoseWorkflowTest(unittest.TestCase):
    def test_xcode_lane_smoke_matches_the_production_release_smoke(self):
        text = Path('.github/workflows/public-farm-native-ios-diagnose.yml').read_text(encoding='utf-8')
        self.assertNotIn('staging', text.lower())
        self.assertIn('--profile production --output-dir "$RUNNER_TEMP/native-ios" --unsigned-simulator', text)
        self.assertIn('Production-iphonesimulator/NinjaDeals.app', text)
        self.assertIn('--backend production', text)


if __name__ == '__main__':
    unittest.main()
