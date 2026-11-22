"""Manual visual QA harness; its window stays above the editor for inspection."""

from pathlib import Path
import sys
import json
from illusive_print.app import IllusivePrintApp, create_root
from tests.support import make_photos


def main():
    root = create_root()
    root.attributes("-topmost", True)
    app = IllusivePrintApp(root)
    root.title("Illusive print — проверка")
    paths = make_photos(Path("tmp/verification/photos"))
    app.add_paths(paths[:3] if "--editor" in sys.argv else paths[:1])
    app.copy_vars[0].set("1" if "--editor" in sys.argv else "10")
    if "--exact" in sys.argv:
        app.mode_var.set("Задать размер фото")
        app.paper_var.set("10 × 15 см")
        app.print_var.set("Свой размер")
        app.size_lock_var.set(False)
        app.print_w_var.set("40")
        app.print_h_var.set("40")
        app.gap_var.set("5")
    if "--editor" in sys.argv:
        app.mode_var.set("Задать размер фото")
        app.print_var.set("Свой размер")
        app.size_lock_var.set(False)
        app.print_w_var.set("150")
        app.print_h_var.set("110")
        app.gap_var.set("5")
        app.global_curve = ((0, 0), (128, 150), (255, 255))
        app.photos[0].curve = ((0, 0), (110, 145), (255, 255))
        app.saturation_var.set(12)
        app.gamma_var.set("1,08")
        app.update_curve_badges()
    app.refresh()
    root.geometry("+20+20")
    if "--editor" in sys.argv:
        root.after(600, app.open_curves)
        previous = [None]
        def report_state():
            state = {"selected": app.selected, "curve": app.photos[0].curve,
                     "offset": [app.photos[0].offset_x, app.photos[0].offset_y],
                     "mode": app.photos[0].mode, "gamma": app.gamma_var.get()}
            if state != previous[0]:
                print("QA state:", json.dumps(state), flush=True)
                previous[0] = state
            root.after(500, report_state)
        root.after(900, report_state)
    root.after(500, lambda: print("QA geometry:", root.winfo_geometry(), "screen:",
                                 root.winfo_screenwidth(), root.winfo_screenheight(), flush=True))
    root.mainloop()


if __name__ == "__main__":
    main()
