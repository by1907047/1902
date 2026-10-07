"""Evaluate INF binding/install semantics; does not install a package."""
import re
import sys
import unittest
from pathlib import Path

STEM = 'SidelineAppleNcm1902'
path = Path(sys.argv.pop(1))
raw = path.read_bytes()
source = raw.decode('utf-16') if raw[:2] in (b'\xff\xfe', b'\xfe\xff') else raw.decode('utf-8-sig')
sections = {}
name = None
for line in source.splitlines():
    # These fixtures have no semicolon inside quoted fields.
    line = line.split(';', 1)[0].strip()
    if not line:
        continue
    if line.startswith('[') and line.endswith(']'):
        name = line[1:-1].replace('$ARCH$', 'amd64').lower()
        sections[name] = []
    elif name:
        sections[name].append(line)

def values(section):
    return {k.strip().lower(): v.strip() for row in sections.get(section.lower(), [])
            if '=' in row for k, v in [row.split('=', 1)]}

strings = values('Strings')
def resolve(text):
    def subst(match):
        key = match.group(1).lower()
        return strings[key].strip('"') if key in strings else match.group(0)
    return re.sub(r'%([^%]+)%', subst, text).replace('$ARCH$', 'amd64')

def model_rows(target_build=26200):
    result = []
    for row in sections.get('manufacturer', []):
        _, rhs = row.split('=', 1)
        base, *decorations = [resolve(x.strip()) for x in rhs.split(',')]
        for decoration in decorations:
            parts = decoration.lower().split('.')
            if parts[0] != 'ntamd64':
                continue
            if len(parts) > 1:
                if len(parts) != 6 or parts[1:3] != ['10', '0']:
                    raise ValueError('Unsupported TargetOSVersion fixture')
                if target_build < int(parts[5]):
                    continue
            for model in sections.get((base+'.'+decoration).lower(), []):
                _, rhs = model.split('=', 1)
                install, *ids = [resolve(x.strip()) for x in rhs.split(',')]
                result.append((install, ids))
    return result

class PackageTests(unittest.TestCase):
    def test_does_not_target_older_windows_than_the_build_kit(self):
        self.assertEqual(model_rows(26099), [])
        self.assertEqual(len(model_rows(26100)), 1)
        self.assertEqual(len(model_rows(26200)), 1)
    def test_only_1902_parent_can_bind(self):
        rows = model_rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual([x.upper() for x in rows[0][1]], ['USB\\VID_05AC&PID_1902'])
        for ids, expected in [(['USB\\VID_05AC&PID_1902&REV_1701','USB\\VID_05AC&PID_1902'], True),
                              (['USB\\VID_05AC&PID_1905'], False),
                              (['USB\\MS_COMP_WINNCM'], False),
                              (['USB\\VID_05AC&PID_1902&MI_00'], False)]:
            binds = any(i.upper() in {h.upper() for h in ids} for _, supported in rows for i in supported)
            self.assertEqual(binds, expected)

    def test_install_uses_independent_service_binary_and_catalog(self):
        for install, _ in model_rows():
            services = values(install+'.NT.Services')
            service, flags, section = [resolve(x.strip()) for x in services['addservice'].split(',')]
            self.assertEqual(service, STEM)
            self.assertEqual(int(flags, 0), 2)
            svc = values(section)
            binary = resolve(svc['servicebinary'])
            self.assertEqual(binary, '%13%\\'+STEM+'.sys')
            self.assertEqual(int(svc['servicetype'], 0), 1)
            wdf_service, wdf_section = [x.strip() for x in values(install+'.NT.Wdf')['kmdfservice'].split(',')]
            self.assertEqual(wdf_service, STEM)
            self.assertIn('kmdflibraryversion', values(wdf_section))
            reg_section = values(install+'.NT')['addreg']
            ndi_services = [row.split(',')[-1].strip().strip('"') for row in sections[reg_section.lower()]
                            if re.match(r'HKR\s*,\s*Ndi\s*,\s*Service\s*,', row, re.I)]
            self.assertEqual(ndi_services, [STEM])
            copy_section = values(install+'.NT')['copyfiles']
            self.assertEqual(sections[copy_section.lower()], [STEM+'.sys'])
        self.assertEqual(resolve(values('Version')['catalogfile']), STEM+'.cat')
        self.assertEqual(values('DestinationDirs')['defaultdestdir'], '13')
        self.assertIn((STEM+'.sys').lower(), values('SourceDisksFiles'))

if __name__ == '__main__':
    unittest.main()
