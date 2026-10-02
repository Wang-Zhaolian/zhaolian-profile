# PyInstaller onedir bundle for the Windows desktop shortcut.
from pathlib import Path

root = Path(SPECPATH)
source = root / "src"
analysis = Analysis(
    [str(root / "start.pyw")],
    pathex=[str(source)],
    binaries=[],
    datas=[
        (str(root / "templates"), "templates"),
        (str(root / "static"), "static"),
        (str(root / "schemas"), "schemas"),
        (str(root / "profiles"), "profiles"),
        (str(root / "data"), "data"),
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
    pyz, analysis.scripts, [], exclude_binaries=True, name="AcademicProfile-0.1.1",
    icon=str(root / "static" / "branding" / "app.ico"),
    debug=False, bootloader_ignore_signals=False, strip=False, upx=True,
    console=False,
)
collection = COLLECT(
    exe, analysis.binaries, analysis.datas, strip=False, upx=True,
    name="AcademicProfile-0.1.1",
)
