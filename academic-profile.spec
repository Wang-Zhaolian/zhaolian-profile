# PyInstaller onedir bundle for the Windows desktop shortcut.
from pathlib import Path

root = Path(SPECPATH)
source = root / "src"
analysis = Analysis(
    [str(root / "start.pyw")],
    pathex=[str(source)],
    binaries=[],
    datas=[
        (str(root / "templates" / "index.html"), "templates"),
        (str(root / "static"), "static"),
        (str(root / "schemas"), "schemas"),
        (str(root / "THIRD_PARTY_NOTICES.md"), "."),
        (str(root / "docs" / "third-party-licenses"), "third-party-licenses"),
        (str(root / "scripts" / "office_to_pdf.ps1"), "scripts"),
    ],
    hiddenimports=[
        "waitress", "waitress.server", "waitress.adjustments",
        "reportlab.pdfbase._fontdata", "reportlab.pdfbase.cidfonts",
        "reportlab.platypus", "flask.json.provider", "jwt", "jwt.algorithms",
        "docx", "yaml", "jsonschema.validators",
    ],
    hookspath=[], hooksconfig={}, runtime_hooks=[], excludes=["pytest"],
    noarchive=False,
)
pyz = PYZ(analysis.pure)
exe = EXE(
    pyz, analysis.scripts, [], exclude_binaries=True, name="ZhaolianProfile-0.3.0",
    icon=str(root / "static" / "branding" / "app.ico"),
    version=str(root / "scripts" / "windows_version_info.txt"),
    debug=False, bootloader_ignore_signals=False, strip=False, upx=True,
    console=False,
)
collection = COLLECT(
    exe, analysis.binaries, analysis.datas, strip=False, upx=True,
    name="ZhaolianProfile-0.3.0",
)
