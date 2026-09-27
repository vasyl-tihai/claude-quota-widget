# -*- coding: utf-8 -*-
"""Віджет календаря для робочого столу Windows.

Місяць сіткою 6×7, тиждень від понеділка, дні чужих місяців приглушені,
сьогоднішній день на плашці. Колесо або ▲/▼ — гортати місяці, клік по назві
місяця — повернутись до сьогодні.
"""

import os
from datetime import date, timedelta

import tkinter as tk

from common import (HERE, T, DesktopWindow, already_running, get_lang, load_json,
                    set_dpi_awareness, tr)

TICK_MS = 30000  # раз на пів хвилини перевіряємо, чи не змінилась дата

PAD = 12
CELL_W = 40
CELL_H = 34
BAND_H = 26
CAL_WIDTH = PAD * 2 + CELL_W * 7        # 304
GRID_W = CELL_W * 7
GRID_H = BAND_H + CELL_H * 6

BOX_W = 32       # плашка під числом (сьогодні / під курсором)
BOX_H = 30
BOX_R = 6        # радіус заокруглення плашки

MONTHS = {
    "uk": ["січень", "лютий", "березень", "квітень", "травень", "червень",
           "липень", "серпень", "вересень", "жовтень", "листопад", "грудень"],
    "en": ["January", "February", "March", "April", "May", "June", "July",
           "August", "September", "October", "November", "December"],
    "pl": ["Styczeń", "Luty", "Marzec", "Kwiecień", "Maj", "Czerwiec", "Lipiec",
           "Sierpień", "Wrzesień", "Październik", "Listopad", "Grudzień"],
    "de": ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli",
           "August", "September", "Oktober", "November", "Dezember"],
    "es": ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio",
           "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"],
    "fr": ["Janvier", "Février", "Mars", "Avril", "Mai", "Juin", "Juillet",
           "Août", "Septembre", "Octobre", "Novembre", "Décembre"],
    "it": ["Gennaio", "Febbraio", "Marzo", "Aprile", "Maggio", "Giugno", "Luglio",
           "Agosto", "Settembre", "Ottobre", "Novembre", "Dicembre"],
    "pt": ["Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho", "Julho",
           "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"],
    "nl": ["Januari", "Februari", "Maart", "April", "Mei", "Juni", "Juli",
           "Augustus", "September", "Oktober", "November", "December"],
    "cs": ["Leden", "Únor", "Březen", "Duben", "Květen", "Červen", "Červenec",
           "Srpen", "Září", "Říjen", "Listopad", "Prosinec"],
    "tr": ["Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran", "Temmuz",
           "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık"],
    "ja": ["%d月" % m for m in range(1, 13)],
    "zh": ["%d月" % m for m in range(1, 13)],
}
TITLE_FORMAT = {"uk": "{month} {year} р.", "ja": "{year}年{month}", "zh": "{year}年{month}"}

# Для світлої й темної — рівно ті кольори, що були в календаря до переїзду
# на спільні теми. Решту тем виводимо з палітри (cal_palette).
CAL_COLORS = {
    "light": {"other": "#b0b0b0", "weekend": "#b8552f", "band": "#2f9bf0",
              "band_fg": "#ffffff", "today": "#0f6cbd", "today_fg": "#ffffff",
              "hover": "#e4e4e4"},
    "dark": {"other": "#575e6a", "weekend": "#d19a72",
             # смуга днів тижня синя, як у світлій темі, але притемнена —
             # той самий насичений синій на темному тлі сліпить
             "band": "#1b3a5c", "band_fg": "#a9cdf1",
             "today": "#2f81f7", "today_fg": "#ffffff", "hover": "#232833"},
}


def hex_rgb(value):
    return tuple(int(value[i:i + 2], 16) for i in (1, 3, 5))


def blend(color, other, amount):
    """Змішує #rrggbb з іншим кольором: amount=0 — сам color, 1 — other."""
    a, b = hex_rgb(color), hex_rgb(other)
    return "#%02x%02x%02x" % tuple(round(x + (y - x) * amount) for x, y in zip(a, b))


def cal_palette(theme):
    if theme in CAL_COLORS:
        return CAL_COLORS[theme]
    dark = sum(hex_rgb(T["bg"])) < 3 * 128
    return {
        "other": blend(T["muted"], T["bg"], 0.45),
        "weekend": T["opus"],
        "band": blend(T["accent"], T["bg"], 0.6) if dark else T["accent"],
        "band_fg": blend(T["accent"], "#ffffff", 0.55) if dark else "#ffffff",
        "today": T["accent"],
        "today_fg": T["bg"] if dark else "#ffffff",
        "hover": T["track"],
    }


# --- дані --------------------------------------------------------------------


def shift_month(anchor, delta):
    """Той самий місяць плюс-мінус delta місяців (перше число)."""
    index = anchor.year * 12 + (anchor.month - 1) + delta
    return date(index // 12, index % 12 + 1, 1)


def month_cells(first):
    """42 дні поспіль, починаючи з понеділка того тижня, де 1-ше число.

    Завжди рівно 6 рядків — щоб вікно не стрибало у висоту між місяцями.
    """
    start = first - timedelta(days=first.weekday())
    return [start + timedelta(days=i) for i in range(42)]


def month_title(first):
    lang = get_lang()
    month = MONTHS.get(lang, MONTHS["en"])[first.month - 1]
    return TITLE_FORMAT.get(lang, "{month} {year}").format(month=month, year=first.year)


# --- плашка під числом -------------------------------------------------------


def inside_round_rect(px, py, w, h, r):
    """Чи всередині заокругленого прямокутника.

    Заокруглений прямокутник = внутрішній прямокутник, «роздутий» на радіус.
    Тому досить притиснути точку до внутрішнього прямокутника й порівняти
    відстань із радіусом — окремі випадки для кутів не потрібні.
    """
    cx = min(max(px, r), w - r)
    cy = min(max(py, r), h - r)
    dx, dy = px - cx, py - cy
    return dx * dx + dy * dy <= r * r


def rounded_image(w, h, r, fill, bg, samples=4):
    """Заокруглена плашка як картинка зі згладженими краями.

    Полотно tkinter малює без згладжування, тому create_oval/прямокутник
    дають видиму драбинку на краях. Тут покриття кожного пікселя рахується
    підвибіркою samples×samples і колір змішується з тлом — край виходить
    м'яким. Тло рівне, тож змішувати можна напряму, без справжньої
    прозорості (її PhotoImage і не вміє).
    """
    r = min(r, w / 2.0, h / 2.0)
    fr, fg_, fb = hex_rgb(fill)
    br, bgc, bb = hex_rgb(bg)
    step = 1.0 / samples
    total = float(samples * samples)

    rows = []
    for y in range(h):
        row = []
        for x in range(w):
            covered = 0
            for sy in range(samples):
                py = y + (sy + 0.5) * step
                for sx in range(samples):
                    if inside_round_rect(x + (sx + 0.5) * step, py, w, h, r):
                        covered += 1
            if covered == 0:
                row.append(bg)
            elif covered == total:
                row.append(fill)
            else:
                a = covered / total
                row.append("#%02x%02x%02x" % (
                    int(br + (fr - br) * a + 0.5),
                    int(bgc + (fg_ - bgc) * a + 0.5),
                    int(bb + (fb - bb) * a + 0.5),
                ))
        rows.append("{" + " ".join(row) + "}")

    image = tk.PhotoImage(width=w, height=h)
    image.put(" ".join(rows))
    return image


# --- вікно -------------------------------------------------------------------


class CalendarWidget(DesktopWindow):
    APP_NAME = "DesktopCalendarWidget"
    SCRIPT = "calendar_widget.py"
    SETTINGS_FILE = "calendar_settings.json"
    TITLE_KEY = "calendar"
    WIDTH = CAL_WIDTH
    HEAD_PADX = PAD

    def __init__(self):
        self.today = date.today()
        self.shown = self.today.replace(day=1)  # який місяць показуємо
        self._images = {}   # плашки; без посилання їх зжере складальник смiття
        self._hover = None  # день під курсором
        super().__init__()
        self.render()
        self.root.after(TICK_MS, self._tick)

    def fallback_settings(self):
        # перший запуск: тема й мова — як у віджета квоти, якщо він є
        quota = load_json(os.path.join(HERE, "settings.json"))
        return {k: quota[k] for k in ("theme", "lang", "alpha", "mode") if k in quota}

    def default_position(self):
        return self.root.winfo_screenwidth() - CAL_WIDTH - 24, 360

    # -- побудова -------------------------------------------------------------

    def _build_body(self):
        # заголовок спільний: замість назви віджета — місяць, клік — до сьогодні
        self.head_title.config(font=("Segoe UI Semibold", 12), cursor="hand2")
        self.head_title._own_click = True
        self.head_title.bind("<Button-1>", lambda _e: self.go_today())
        self.head_title.bind("<Button-3>", self._popup)

        # праворуч наліво: шестірня (вже є), ▼ наступний місяць, ▲ попередній
        self.next_btn = self._head_button("▼", lambda: self.step(1))
        self.prev_btn = self._head_button("▲", lambda: self.step(-1))

        self.canvas = tk.Canvas(
            self.root, width=GRID_W, height=GRID_H,
            bg=T["bg"], highlightthickness=0, bd=0,
        )
        self.canvas.pack(padx=PAD, pady=(0, PAD))
        self.canvas.bind("<Motion>", self._motion)
        self.canvas.bind("<Leave>", self._leave)

        for widget in (self.root, self.head, self.canvas, self.head_title,
                       self.prev_btn, self.next_btn, self.gear):
            widget.bind("<MouseWheel>", self._wheel)

    def _head_button(self, glyph, action):
        label = tk.Label(
            self.head, text=glyph, bg=T["bg"], fg=T["muted"],
            font=("Segoe UI", 9), width=2, cursor="hand2",
        )
        label._own_click = True
        label.pack(side="right")
        label.bind("<Button-1>", lambda _e: action())
        label.bind("<Button-3>", self._popup)
        label.bind("<Enter>", lambda _e, w=label: w.config(fg=T["fg"]))
        label.bind("<Leave>", lambda _e, w=label: w.config(fg=T["muted"]))
        return label

    def _menu_items(self, menu):
        menu.add_command(label=tr("cal_go_today"), command=self.go_today)
        menu.add_separator()

    def retheme(self):
        self._images.clear()  # плашки змішані з тлом — при зміні теми недійсні
        self.canvas.config(bg=T["bg"])
        self.head_title.config(fg=T["fg"])
        for btn in (self.prev_btn, self.next_btn):
            btn.config(bg=T["bg"], fg=T["muted"])
        self.render()

    def relabel(self):
        self.render()  # назва місяця й дні тижня — мовою віджета

    # -- навігація ------------------------------------------------------------

    def step(self, delta):
        self.shown = shift_month(self.shown, delta)
        self.render()

    def go_today(self):
        self.today = date.today()
        self.shown = self.today.replace(day=1)
        self.render()

    def _wheel(self, event):
        self.step(-1 if event.delta > 0 else 1)

    def _cell_at(self, x, y):
        """Який день під точкою полотна (None — смуга днів тижня або поза сіткою)."""
        if y < BAND_H:
            return None
        col = int(x // CELL_W)
        row = int((y - BAND_H) // CELL_H)
        if 0 <= col < 7 and 0 <= row < 6:
            return month_cells(self.shown)[row * 7 + col]
        return None

    def _motion(self, event):
        day = self._cell_at(event.x, event.y)
        if day != self._hover:
            self._hover = day
            self.render()

    def _leave(self, _event):
        if self._hover is not None:
            self._hover = None
            self.render()

    def _tick(self):
        """Перемальовує календар, коли настала нова доба.

        Перевірка датою, а не таймером до півночі: комп'ютер може заснути,
        і відкладений на 6 годин виклик прокинеться зі зсувом.
        """
        if self.stop:
            return
        current = date.today()
        if current != self.today:
            on_current_month = self.shown == self.today.replace(day=1)
            self.today = current
            if on_current_month:  # не смикати місяць, якщо гортали інший
                self.shown = current.replace(day=1)
            self.render()
        self.root.after(TICK_MS, self._tick)

    # -- малювання ------------------------------------------------------------

    def _box(self, fill):
        """Плашка потрібного кольору; рахується раз і лишається в кеші."""
        key = (fill, T["bg"])
        if key not in self._images:
            self._images[key] = rounded_image(BOX_W, BOX_H, BOX_R, fill, T["bg"])
        return self._images[key]

    def render(self):
        p = cal_palette(self.settings.get("theme", "light"))
        self.head_title.config(text=month_title(self.shown))

        c = self.canvas
        c.delete("all")

        # смуга з днями тижня
        c.create_rectangle(0, 0, GRID_W, BAND_H, fill=p["band"], outline="")
        for col, name in enumerate(tr("weekdays")):
            c.create_text(
                col * CELL_W + CELL_W / 2, BAND_H / 2 + 1, text=name[:1].upper() + name[1:],
                fill=p["band_fg"], font=("Segoe UI Semibold", 10),
            )

        for i, day in enumerate(month_cells(self.shown)):
            col, row = i % 7, i // 7
            cx = col * CELL_W + CELL_W / 2
            cy = BAND_H + row * CELL_H + CELL_H / 2

            if day.month != self.shown.month:
                color = p["other"]
            elif day.weekday() >= 5:
                color = p["weekend"]
            else:
                color = T["fg"]

            if day == self.today:
                c.create_image(cx, cy, image=self._box(p["today"]))
                color = p["today_fg"]
            elif day == self._hover:
                c.create_image(cx, cy, image=self._box(p["hover"]))

            c.create_text(
                cx, cy, text=str(day.day), fill=color,
                font=("Segoe UI Semibold" if day == self.today else "Segoe UI", 11),
            )

        self.fit_height()


def main():
    if already_running(CalendarWidget.APP_NAME):
        return
    set_dpi_awareness()
    CalendarWidget().run()


if __name__ == "__main__":
    main()
