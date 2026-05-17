import json
import re
from pathlib import Path

BASE = Path(__file__).resolve().parent
cfg = json.loads((BASE / "brand_config.json").read_text(encoding="utf-8"))
script_path = BASE / "hsm_splitter_app.py"
spec_path = BASE / "HSM_Splitter.spec"
version_path = BASE / "version_info.txt"

exe_name = cfg.get("exe_name", "HSM_Splitter")
window_title = cfg.get("window_title", "HSM Splitter")

script_text = script_path.read_text(encoding="utf-8")
script_text = re.sub(r'self\.root\.title\(".*?"\)', f'self.root.title("{window_title}")', script_text, count=1)
script_path.write_text(script_text, encoding="utf-8")

spec_text = spec_path.read_text(encoding="utf-8")
spec_text = re.sub(r"name='[^']+'", f"name='{exe_name}'", spec_text, count=2)
spec_path.write_text(spec_text, encoding="utf-8")

print("Branding applied.")
