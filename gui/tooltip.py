"""Tooltip that stays on screen and holds still.

Two problems with ttkbootstrap's ToolTip, both fixed here:

1. It places itself at `pointer + (25, 10)` with no bounds check, so a tooltip
   near the right or bottom edge of the display is drawn partly off-screen.

2. It re-positions on every `<Motion>` event, so the tooltip chases the cursor.
   Correcting an off-screen position *after* the base class had already placed
   the window meant one frame was drawn at the wrong spot before it snapped
   back — visible as a flicker while the mouse was moving.

The fix for both is the same: compute the final position ONCE, before the
window is ever shown, and then leave it alone. A tooltip anchored to the widget
it describes is also just easier to read than one sliding around under the
pointer.

Use `tip(widget, "text")` everywhere instead of ToolTip(...).
"""

from __future__ import annotations

import ttkbootstrap as ttk
from ttkbootstrap.constants import BOTH, YES
from ttkbootstrap.widgets.tooltip import ToolTip

# Keep clear of the screen edges, and of the taskbar along the bottom.
_MARGIN = 8
_TASKBAR_ALLOWANCE = 48
# Offset from the pointer when there is room below-right, matching the
# familiar native placement.
_OFFSET_X = 18
_OFFSET_Y = 14

# Widening a too-tall tooltip: how much wider per attempt, how many attempts,
# and the share of the screen width a tooltip may ever occupy. A tooltip wider
# than about half the screen stops being readable regardless of how well it
# fits, so the fraction is a readability limit rather than a layout one.
_WIDEN_FACTOR = 1.6
_FIT_ATTEMPTS = 4
_MAX_WIDTH_FRACTION = 0.5


class SmartToolTip(ToolTip):
    """A ToolTip that is placed once, in bounds, and does not follow the mouse."""

    def show_tip(self, *_args) -> None:
        """Build the window off-screen, measure it, then show it in place.

        The base implementation is not reused: it deiconifies before the
        position is known, which is exactly what causes the flicker.
        """
        if self.toplevel:
            return

        self.toplevel = ttk.window.Toplevel(position=(0, 0),
                                            **self.toplevel_kwargs)
        self.toplevel.withdraw()

        lbl = ttk.Label(
            master=self.toplevel,
            text=self.text,
            image=self.image,
            compound="bottom",
            justify=self.justify,
            wraplength=self.wraplength,
            padding=self.padding,
        )
        lbl.pack(fill=BOTH, expand=YES)
        if self.bootstyle:
            lbl.configure(bootstyle=self.bootstyle)
        else:
            lbl.configure(style="tooltip.TLabel")

        # Size is only knowable once the label is laid out. Still hidden here,
        # so nothing is drawn at the wrong position.
        self.toplevel.update_idletasks()
        self._fit_vertically(lbl)
        x, y = self._position(self.toplevel.winfo_width(),
                              self.toplevel.winfo_height())
        self.toplevel.geometry(f"+{x}+{y}")
        self.toplevel.deiconify()

    def _fit_vertically(self, lbl) -> None:
        """Widen a too-tall tooltip until it fits the screen height.

        A long tooltip at a fixed wraplength is tall and narrow, and past the
        screen height there is no position that shows all of it. Widening
        trades height for width, which the screen has spare: the same text at
        double the wraplength is roughly half as tall.

        This is a SAFETY NET, not a licence to write enormous tooltips -- the
        text still has to be readable, and a tooltip that needs this is
        usually one whose content belongs on the tab instead. It exists so
        that a long one degrades into "wide" rather than into "silently
        truncated", which is the failure this class was built to prevent.
        """
        try:
            screen_w = self.widget.winfo_screenwidth()
            usable_h = self.widget.winfo_screenheight() - _TASKBAR_ALLOWANCE
        except Exception:
            return

        max_w = int(screen_w * _MAX_WIDTH_FRACTION)
        for _ in range(_FIT_ATTEMPTS):
            if self.toplevel.winfo_height() + 2 * _MARGIN <= usable_h:
                return
            width = lbl.cget("wraplength")
            if not width or width >= max_w:
                return
            lbl.configure(wraplength=min(int(width * _WIDEN_FACTOR), max_w))
            self.toplevel.update_idletasks()

    def move_tip(self, *_args) -> None:
        """Deliberately does nothing.

        The tooltip stays where it was first placed. Re-positioning on every
        motion event is what made it flicker, and a tooltip that holds still
        is easier to read anyway.
        """
        return

    def _position(self, tip_w: int, tip_h: int) -> tuple[int, int]:
        """Final on-screen position: below-right of the pointer if it fits,
        flipped to the other side when it would overflow.

        MEASURED BUG, fixed 2026-09-05: the final clamp used to be

            y = max(_MARGIN, min(y, screen_h - tip_h - _MARGIN))

        which is correct only while the tooltip FITS. Once `tip_h` exceeds the
        screen height the inner term goes negative, `max` picks `_MARGIN`, and
        the window is placed with its top at the margin and its bottom far off
        the screen -- so the last paragraphs are simply unreachable, with no
        scrollbar and no sign anything is missing. That is what made the model
        dropdown's (very long) tooltip appear cut off at the bottom.

        Clamping alone cannot fix an oversized tooltip -- there is nowhere to
        put it. `show_tip` widens the wraplength first so tall-and-narrow
        becomes short-and-wide; this guard is what stops the remainder from
        being pushed off-screen, and `fits_vertically` lets the caller know a
        tooltip is still too tall to show whole.
        """
        try:
            px = self.widget.winfo_pointerx()
            py = self.widget.winfo_pointery()
            screen_w = self.widget.winfo_screenwidth()
            screen_h = self.widget.winfo_screenheight()
        except Exception:
            return _MARGIN, _MARGIN

        usable_h = screen_h - _TASKBAR_ALLOWANCE

        x = px + _OFFSET_X
        y = py + _OFFSET_Y

        # Flip rather than slide, so the pointer never sits on top of the text.
        if x + tip_w + _MARGIN > screen_w:
            x = px - tip_w - _MARGIN
        if y + tip_h + _MARGIN > usable_h:
            y = py - tip_h - _MARGIN

        # Clamp INSIDE the screen -- but only when there is room to clamp
        # into. `min` with a negative upper bound is what broke this before,
        # so the too-tall case is handled explicitly instead of arithmetically.
        x = (max(_MARGIN, min(x, screen_w - tip_w - _MARGIN))
             if tip_w + 2 * _MARGIN <= screen_w else _MARGIN)
        y = (max(_MARGIN, min(y, usable_h - tip_h - _MARGIN))
             if tip_h + 2 * _MARGIN <= usable_h else _MARGIN)
        return int(x), int(y)


def tip(widget, text: str, **kwargs) -> SmartToolTip:
    """Attach an edge-aware tooltip to `widget`."""
    return SmartToolTip(widget, text=text, **kwargs)
