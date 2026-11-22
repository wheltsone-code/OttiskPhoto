"""Interactive native-driver properties check. Never creates a print job."""
import json
from pathlib import Path
import sys

from illusive_print.core import Layout
from illusive_print.windows_print import WindowsPrinter


def main():
    backend = WindowsPrinter()
    name = sys.argv[1] if len(sys.argv) > 1 else backend.default()
    settings = backend.configure(name, Layout())
    result = backend.properties(0, name, settings)
    report = {"printer": name, "native_properties_opened": True, "cancelled": result is None,
              "paper": vars(backend.inspect(name, result if result is not None else settings)),
              "spool_created": False}
    folder = Path("tmp/verification")
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "native-driver.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
