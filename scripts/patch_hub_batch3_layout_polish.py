from pathlib import Path

path = Path("src/openjarvis/tools/serena_hub.py")
text = path.read_text(encoding="utf-8")

replacements = {
    ".stage { position: relative; overflow: hidden; padding: 22px; }":
    ".stage { position: relative; overflow: auto; padding: 22px; }",

    """.widget-grid {
  position: absolute;
  left: 24px;
  right: 24px;
  bottom: 24px;
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 14px;
}""":
    """.widget-grid {
  position: relative;
  margin-top: 18px;
  padding-right: 150px;
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 14px;
}""",

    """<link rel="stylesheet" href="assets/hub.css">""":
    """<link rel="icon" href="data:,">
  <link rel="stylesheet" href="assets/hub.css">""",
}

for old, new in replacements.items():
    if old not in text:
        print(f"[WARN] Pattern not found: {old[:60]}...")
    else:
        text = text.replace(old, new)

path.write_text(text, encoding="utf-8")
print("[OK] Patched Batch 3 dynamic web layout polish")