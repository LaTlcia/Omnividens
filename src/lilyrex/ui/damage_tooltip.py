"""A passive Tk hover preview; damage calculations belong to the service layer."""
from __future__ import annotations

from dataclasses import dataclass
import math
import tkinter as tk
from tkinter import font as tkfont
from typing import Any, Callable

from lilyrex.domain.models import DamageEstimate, PreviewResult
from .formula_view import FormulaView


@dataclass(frozen=True)
class TooltipTheme:
    bg: str = "#23243a"
    header: str = "#2d2e4a"
    border: str = "#3a3b5c"
    text: str = "#ffffff"
    muted: str = "#aab0dc"
    font_name: str = "Arial"


class DamageTooltip:
    """One reusable, non-focusing tooltip, driven exclusively by the Tk thread."""

    WIDTH = 340
    FORMULA_WIDTH = 480
    LEAVE_DELAY_MS = 240
    MAX_TARGETS = 5
    ATTRIBUTES = {1: "火", 2: "水", 3: "風", 4: "光", 5: "闇"}

    def __init__(
        self,
        root: tk.Misc,
        *,
        theme: TooltipTheme | None = None,
        icon_provider: Callable[[int], Any] | None = None,
        delay_ms: int = 180,
    ) -> None:
        self.root = root
        self.theme = theme or TooltipTheme()
        self.icon_provider = icon_provider
        self.delay_ms = max(0, int(delay_ms))
        self._key: tuple | None = None
        self._provider: Callable[[], PreviewResult] | None = None
        self._after_id: str | None = None
        self._leave_id: str | None = None
        self._position = (0, 0)
        self._visible = False
        self._destroyed = False
        self._last_result: PreviewResult | None = None
        self._image: Any = None
        self.formula_view: FormulaView | None = None

        self.window = tk.Toplevel(root, takefocus=False)
        self.window.withdraw()
        self.window.overrideredirect(True)
        try:
            # Same non-activating macOS help-window style used by IDLE tooltips.
            self.window.tk.call("::tk::unsupported::MacWindowStyle", "style",
                                self.window._w, "help", "noActivates")
        except tk.TclError:
            pass  # The command is absent on Windows and X11.
        self.window.configure(bg=self.theme.border)
        self.window.transient(root.winfo_toplevel())
        self.window.protocol("WM_DELETE_WINDOW", self.hide)
        self.window.bind("<Enter>", lambda _event: self._cancel_leave())
        self.window.bind("<Leave>", lambda _event: self.leave())
        self._font = tkfont.Font(
            root=self.window, family=self.theme.font_name, size=9
        )
        self._title_font = tkfont.Font(
            root=self.window, family=self.theme.font_name, size=11, weight="bold"
        )
        self._content = tk.Frame(self.window, bg=self.theme.bg, takefocus=False)
        self._content.pack(fill=tk.BOTH, expand=True, padx=1, pady=1)

    @property
    def visible(self) -> bool:
        return self._visible and not self._destroyed

    def request(
        self,
        key: tuple,
        provider: Callable[[], PreviewResult],
        x_root: int,
        y_root: int,
    ) -> None:
        """Delay a new card; moving within the same card never restarts its timer."""
        if self._destroyed:
            return
        self._cancel_leave()
        self._position = (int(x_root), int(y_root))
        if key == self._key:
            self._provider = provider
            if self.visible:
                self._place()
            return
        self.hide()
        self._key, self._provider = key, provider
        self._after_id = self.root.after(self.delay_ms, self._show)

    def refresh(self) -> None:
        """Re-evaluate the current card without mouse movement or a new window."""
        if not self.visible or self._provider is None:
            return
        result = self._evaluate()
        if result != self._last_result:
            self._render(result)
            self._place()

    def hide(self) -> None:
        self._cancel_leave()
        if self._after_id is not None:
            try:
                self.root.after_cancel(self._after_id)
            except tk.TclError:
                pass
            self._after_id = None
        self._key = self._provider = None
        self._last_result = None
        self._visible = False
        self.formula_view = None
        if not self._destroyed:
            try:
                self.window.withdraw()
            except tk.TclError:
                pass

    def leave(self) -> None:
        """Allow crossing the gap from a card to this popup before dismissing."""
        self._cancel_leave()
        if not self.visible:
            self.hide()
            return
        self._leave_id = self.root.after(self.LEAVE_DELAY_MS, self._dismiss_if_outside)

    def _cancel_leave(self) -> None:
        if self._leave_id is not None:
            try:
                self.root.after_cancel(self._leave_id)
            except tk.TclError:
                pass
            self._leave_id = None

    def _pointer_inside(self) -> bool:
        if not self.visible:
            return False
        try:
            x, y = self.window.winfo_pointerxy()
            left, top = self.window.winfo_rootx(), self.window.winfo_rooty()
            return left <= x < left + self.window.winfo_width() and top <= y < top + self.window.winfo_height()
        except tk.TclError:
            return False

    def _dismiss_if_outside(self) -> None:
        self._leave_id = None
        if not self._pointer_inside():
            self.hide()

    def destroy(self) -> None:
        if self._destroyed:
            return
        self.hide()
        self._destroyed = True
        try:
            self.window.destroy()
        except tk.TclError:
            pass

    def _evaluate(self) -> PreviewResult:
        try:
            assert self._provider is not None
            result = self._provider()
            if not isinstance(result, PreviewResult):
                raise TypeError("preview provider must return PreviewResult")
            return result
        except Exception:
            # Neither an exception message nor a fake zero is an estimate.
            return PreviewResult(0, 0, error="暂时无法计算；等待下一帧数据。")

    def _show(self) -> None:
        self._after_id = None
        if self._destroyed or self._provider is None:
            return
        self._render(self._evaluate())
        self._place()
        self.window.deiconify()
        self.window.lift()
        self._visible = True

    def _label(
        self, parent: tk.Misc, text: str, *, color: str | None = None,
        bold: bool = False, size: int = 9, bg: str | None = None,
    ) -> tk.Label:
        return tk.Label(
            parent, text=text, anchor="w", justify=tk.LEFT, bd=0,
            bg=bg or self.theme.bg, fg=color or self.theme.text,
            font=(self.theme.font_name, size, "bold" if bold else "normal"),
            takefocus=False,
        )

    def _lines(self, text: str, width: int, maximum: int, *, title: bool = False) -> str:
        """Bound CJK and Latin text by pixels so a long note cannot cover the screen."""
        font = self._title_font if title else self._font
        rows: list[str] = []
        row = ""
        for char in text:
            if char == "\n" or (row and font.measure(row + char) > width):
                rows.append(row)
                row = "" if char == "\n" else char
                if len(rows) == maximum:
                    last = rows[-1]
                    while last and font.measure(last + "…") > width:
                        last = last[:-1]
                    rows[-1] = last + "…"
                    return "\n".join(rows)
            else:
                row += char
        if row or not rows:
            rows.append(row)
        return "\n".join(rows[:maximum])

    @staticmethod
    def _number(value: float) -> str:
        return f"{value:,.0f}" if math.isfinite(value) else "—"

    @staticmethod
    def _valid(estimate: DamageEstimate) -> bool:
        values = (estimate.expected, estimate.minimum, estimate.maximum,
                  estimate.attack, estimate.defense)
        return all(math.isfinite(v) for v in values)

    def _render(self, result: PreviewResult) -> None:
        scroll_position = self.formula_view.text.yview()[0] if self.formula_view is not None else 0.0
        first_visible = self.formula_view.text.index('@0,0') if self.formula_view is not None else '1.0'
        self._last_result = result
        for child in self._content.winfo_children():
            child.destroy()
        self._image = None
        self.formula_view = None
        screen_w = self.window.winfo_screenwidth()
        width = min(self.FORMULA_WIDTH if result.calculation else self.WIDTH, max(160, screen_w - 16))
        text_width = width - 28

        header = tk.Frame(self._content, bg=self.theme.header)
        header.pack(fill=tk.X)
        self._label(header, "预计伤害 · 当前状态下次使用 · 每个目标", color=self.theme.muted,
                    size=8, bg=self.theme.header).pack(anchor="w", padx=10, pady=(6, 0))
        self._label(
            header, self._lines(result.card_name or "伤害预估", text_width, 2, title=True),
            bold=True, size=11, bg=self.theme.header,
        ).pack(anchor="w", padx=10, pady=(2, 3))
        meta = tk.Frame(header, bg=self.theme.header)
        meta.pack(fill=tk.X, padx=10, pady=(0, 6))
        if result.attribute in self.ATTRIBUTES and self.icon_provider is not None:
            try:
                self._image = self.icon_provider(result.attribute)
            except Exception:
                self._image = None
            if self._image is not None:
                tk.Label(meta, image=self._image, bd=0, bg=self.theme.header,
                         takefocus=False).pack(side=tk.LEFT, padx=(0, 5))
        lower, upper = result.targets
        target_text = "单体" if (lower, upper) == (1, 1) else (f"范围 {lower}体" if lower == upper else f"范围 {lower}–{upper}体")
        parts = [self.ATTRIBUTES.get(result.attribute, "属性未知"),
                 result.attack_label, target_text]
        self._label(meta, "  ·  ".join(p for p in parts if p), color=self.theme.muted,
                    size=8, bg=self.theme.header).pack(side=tk.LEFT)

        body = tk.Frame(self._content, bg=self.theme.bg)
        body.pack(fill=tk.X, padx=10, pady=(7, 4))
        if result.error or not result.estimates:
            self._label(
                body, self._lines(result.error or "暂无可估算的敌方前卫。", text_width, 4),
                color="#ffcf8a",
            ).pack(anchor="w", pady=4)
        else:
            for estimate in result.estimates[:self.MAX_TARGETS]:
                self._target_row(body, estimate, text_width)
            first = result.estimates[0]
            if self._valid(first):
                tk.Frame(body, height=1, bg=self.theme.border).pack(fill=tk.X, pady=(6, 5))
                bounds = f"{math.floor(first.minimum):,} – {math.ceil(first.maximum):,}"
                self._label(body, f"首行范围（被动取期望）  {bounds}", size=8,
                            color=self.theme.muted).pack(anchor="w")
                magical = any(s in result.attack_label.lower() for s in ("特殊", "魔", "magical"))
                atk, defense = ("Sp.ATK", "Sp.DEF") if magical else ("ATK", "DEF")
                self._label(
                    body, f"有效 {atk} {self._number(first.attack)}  /  {defense} {self._number(first.defense)}",
                    size=8, color=self.theme.muted,
                ).pack(anchor="w", pady=(2, 0))

        if result.calculation:
            tk.Frame(self._content, height=1, bg=self.theme.border).pack(fill=tk.X, padx=10)
            self._label(self._content, "完整计算公式 · 移入浮窗后滚轮查看", color="#8ce1d5",
                        size=8).pack(anchor="w", padx=10, pady=(5, 0))
            self.window.update_idletasks()
            # Leave room for desktop menu bars; macOS clamps help windows below
            # its menu even when their requested y position is only 8 pixels.
            available = self.window.winfo_screenheight() - self._content.winfo_reqheight() - 56
            self.formula_view = FormulaView(self._content, self.theme, height=max(40, min(360, available)))
            self.formula_view.frame.pack(fill=tk.BOTH, expand=True, padx=3, pady=(2, 5))
            self.formula_view.set_content(result.calculation, scroll_position)
        elif result.assumptions:
            tk.Frame(self._content, height=1, bg=self.theme.border).pack(fill=tk.X, padx=10)
            # At 340 px this stays compact while preserving service-provided priorities.
            notes = "估计口径：" + "；".join(result.assumptions)
            note_lines = max(2, min(6, (self.window.winfo_screenheight() - 320) // 17))
            self._label(
                self._content, self._lines(notes, text_width, note_lines),
                color=self.theme.muted, size=8,
            ).pack(anchor="w", padx=10, pady=(5, 7))
        self.window.update_idletasks()
        height = min(self._content.winfo_reqheight() + 2, self.window.winfo_screenheight() - 48)
        self.window.geometry(f"{width}x{max(40, height)}")
        self.window.update_idletasks()
        if self.formula_view is not None:
            # A text fraction uses Tk's estimated total wrapped-line height,
            # which can change while the replacement widget is laid out.
            # Preserve the actual top character after final geometry instead.
            self.formula_view.text.yview(first_visible)

    def _target_row(self, parent: tk.Misc, estimate: DamageEstimate, width: int) -> None:
        row = tk.Frame(parent, bg=self.theme.bg)
        row.pack(fill=tk.X, pady=3)
        number = "≈ " + self._number(estimate.expected) if self._valid(estimate) else "无法估计"
        self._label(row, number, bold=True,
                    color="#ffcf5c" if estimate.locked else "#8ce1d5").pack(side=tk.RIGHT)
        prefix = "锁定 " if estimate.locked else ""
        title = f"{prefix}#{estimate.target_rank} {estimate.target_name}"
        available = max(40, width - self._font.measure(number) - 20)
        self._label(row, self._lines(title, available, 1), bold=estimate.locked).pack(side=tk.LEFT)

    def _place(self) -> None:
        self.window.update_idletasks()
        width, height = self.window.winfo_width(), self.window.winfo_height()
        screen_w, screen_h = self.window.winfo_screenwidth(), self.window.winfo_screenheight()
        if self._pointer_inside():
            x, y = self.window.winfo_x(), self.window.winfo_y()
        else:
            pointer_x, pointer_y = self._position
            x, y = pointer_x + 16, pointer_y + 18
            if x + width > screen_w - 8:
                x = pointer_x - width - 12
            if y + height > screen_h - 8:
                y = pointer_y - height - 12
        x = max(8, min(x, screen_w - width - 8))
        y = max(8, min(y, screen_h - height - 8))
        self.window.geometry(f"+{x}+{y}")
