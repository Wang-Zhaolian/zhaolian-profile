"""Native desktop bundle; build on the target operating system."""
from pathlib import Path
import re
import sys

root = Path(SPECPATH)
version = re.search(r'__version__ = "([^"]+)"', (root / 'src/academic_profile/__init__.py').read_text(encoding='utf-8')).group(1)
mac = sys.platform == 'darwin'
product = '昭濂个人履历库'
executable_name = product if mac else f'ZhaolianProfile-{version}'
datas = [(str(root / 'templates/index.html'), 'templates'), (str(root / 'static'), 'static'),
         (str(root / 'schemas'), 'schemas'), (str(root / 'THIRD_PARTY_NOTICES.md'), '.'),
         (str(root / 'docs/third-party-licenses'), 'third-party-licenses')]
if not mac:
    datas.append((str(root / 'scripts/office_to_pdf.ps1'), 'scripts'))
analysis = Analysis([str(root / 'start.pyw')], pathex=[str(root / 'src')], binaries=[], datas=datas,
    hiddenimports=['waitress', 'waitress.server', 'jwt.algorithms', 'jsonschema.validators',
        'cryptography.hazmat.primitives.ciphers.aead', 'docx', 'yaml',
        'reportlab.pdfbase._fontdata', 'reportlab.pdfbase.cidfonts', 'reportlab.platypus']
        + (['keyring.backends.macOS'] if mac else []),
    hookspath=[], hooksconfig={}, runtime_hooks=[], excludes=['pytest'], noarchive=False)
pyz = PYZ(analysis.pure)
exe = EXE(pyz, analysis.scripts, [], exclude_binaries=True, name=executable_name,
    icon=str(root / ('static/branding/zhaolian-app.png' if mac else 'static/branding/app.ico')),
    version=None if mac else str(root / 'scripts/windows_version_info.txt'),
    console=False, debug=False, strip=False, upx=False, argv_emulation=False)
collection = COLLECT(exe, analysis.binaries, analysis.datas, strip=False, upx=False, name=executable_name)
if mac:
    app = BUNDLE(collection, name=product + '.app',
        icon=str(root / 'static/branding/zhaolian-app.png'),
        bundle_identifier='com.wangzhaolian.zhaolian-profile',
        info_plist={'CFBundleShortVersionString': version, 'CFBundleVersion': version,
            'NSHighResolutionCapable': True, 'LSMinimumSystemVersion': '13.0'})
