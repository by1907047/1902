"""Verify the compile-only DMF exception is explicit and narrowly scoped."""
from pathlib import Path
import unittest
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1] / 'NCM-Driver-for-Windows'
NS = {'m': 'http://schemas.microsoft.com/developer/msbuild/2003'}

class BuildPolicyTests(unittest.TestCase):
    def test_only_release_x64_dmf_has_opt_in_exception(self):
        path = ROOT/'dmf/Dmf/Solution/DmfKModules.Library/DmfKModules.Library.vcxproj'
        tree = ET.parse(path)
        rows = []
        for group in tree.findall('m:ItemDefinitionGroup', NS):
            for item in group.findall('m:ClCompile/m:TreatWarningAsError', NS):
                if 'SidelineCompileOnly' in item.attrib.get('Condition', ''):
                    rows.append((group.attrib.get('Condition'), item.attrib['Condition'], item.text))
        self.assertEqual(rows, [("'$(Configuration)|$(Platform)'=='Release|x64'",
                                 "'$(SidelineCompileOnly)'=='true'", 'false')])
        for name in ('host', 'adapter', 'common'):
            self.assertNotIn('SidelineCompileOnly', (ROOT/f'projects/{name}/{name}.vcxproj').read_text())

    def test_build_script_records_results_and_keeps_analysis(self):
        script = (ROOT/'scripts/build-1902.cmd').read_text()
        commands = [line.lower() for line in script.splitlines() if line.lower().startswith('call msbuild')]
        self.assertEqual(len(commands), 2)
        for command in commands:
            for flag in ('/p:signmode=off', '/p:runcodeanalysis=true',
                         '/p:sidelinecompileonly=true', '/nr:false'):
                self.assertIn(flag, command)
        self.assertIn('echo NCM_BUILD_EXIT=0', script)
        self.assertIn('echo NCM_BUILD_EXIT=%NCM_BUILD_EXIT%', script)

if __name__ == '__main__':
    unittest.main()
