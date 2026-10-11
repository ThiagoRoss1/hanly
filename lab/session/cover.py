"""A window that stands in for another application covering the tour page.

It is a separate process with its own text, kept on top, so the tour's
ownership guard must refuse to read anything under it. Run as
``python -m lab.session.cover LEFT TOP WIDTH HEIGHT``; the lab stops it.
"""

from __future__ import annotations

import sys


def main() -> None:
    import tkinter

    left, top, width, height = (int(value) for value in sys.argv[1:5])
    root = tkinter.Tk()
    root.overrideredirect(True)
    root.geometry(f"{width}x{height}+{left}+{top}")
    root.configure(background="#2a5aa0")
    root.attributes("-topmost", True)
    tkinter.Label(
        root,
        text="Another application\n다른 프로그램 창",
        font=("Malgun Gothic", 28),
        fg="white",
        bg="#2a5aa0",
    ).pack(expand=True)

    def stay_on_top() -> None:
        root.attributes("-topmost", True)
        root.lift()
        root.after(200, stay_on_top)

    stay_on_top()
    root.mainloop()


if __name__ == "__main__":
    main()
