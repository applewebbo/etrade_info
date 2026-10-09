import subprocess
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class TestDistPackaging:
    def test_zip_includes_every_root_python_module(self):
        """Regression test: releases.py and gl_parser.py were once missing from
        the packaged zip because the dist recipe copied an explicit file list
        instead of every root module, crashing the shipped app at startup."""
        subprocess.run(["just", "dist"], check=True, cwd=ROOT)

        zip_path = ROOT / "dist" / "EtradePortfolio.zip"
        with zipfile.ZipFile(zip_path) as zf:
            packaged_names = {Path(n).name for n in zf.namelist()}

        required = {f.name for f in ROOT.glob("*.py") if f.name != "conftest.py"}
        assert required <= packaged_names
