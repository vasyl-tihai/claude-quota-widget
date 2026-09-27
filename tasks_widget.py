# -*- coding: utf-8 -*-
"""Віджет задач на день для робочого столу Windows.

Три списки:
  • сьогодні — те, що видно завжди; ○ позначає задачу виконаною, і вона зникає;
  • на потім — запас задач, згорнутий під спойлером; ↑ переносить на сьогодні;
  • виконані — згорнуті; ✓ повертає задачу на сьогодні.

Невиконане не згорає опівночі — просто лишається на сьогодні наступного дня.
Дані — tasks.json поруч зі скриптом.
"""

import os
import time
import uuid
from datetime import datetime

import tkinter as tk
import tkinter.font as tkfont

from common import (HERE, PAD, WIDTH, T, DesktopWindow, load_json, save_json,
                    set_dpi_awareness, tr)

TASKS_PATH = os.path.join(HERE, "tasks.json")
DONE_SHOWN = 15          # скільки виконаних показувати у спойлері
DONE_KEEP_DAYS = 30      # старші виконані прибираються з файлу самі


def load_tasks():
    data = load_json(TASKS_PATH)
    for key in ("today", "later", "done"):
        if not isinstance(data.get(key), list):
            data[key] = []
    cutoff = time.time() - DONE_KEEP_DAYS * 86400
    data["done"] = [t for t in data["done"] if t.get("done_at", 0) >= cutoff]
    return data


def new_task(text):
    return {"id": uuid.uuid4().hex[:12], "text": text, "created": time.time()}


class TasksWidget(DesktopWindow):
    APP_NAME = "DailyTasksWidget"
    SCRIPT = "tasks_widget.py"
    SETTINGS_FILE = "tasks_settings.json"
    TITLE_KEY = "tasks_title"

    def __init__(self):
        self.tasks = load_tasks()
        super().__init__()
        self.render()

    def fallback_settings(self):
        # перший запуск: тема й мова — як у віджета квоти, якщо він є
        quota = load_json(os.path.join(HERE, "settings.json"))
        return {k: quota[k] for k in ("theme", "lang", "alpha", "mode") if k in quota}

    def default_position(self):
        # під віджетом квоти, щоб при першому запуску вони не наклались
        return self.root.winfo_screenwidth() - WIDTH - 24, 420

    # -- побудова -------------------------------------------------------------

    def _build_body(self):
        self.font_task = tkfont.Font(family="Segoe UI", size=9)
        self.font_small = tkfont.Font(family="Segoe UI", size=8)
        self.font_done = tkfont.Font(family="Segoe UI", size=9, overstrike=True)

        self.today_box = tk.Frame(self.root, bg=T["bg"])
        self.today_box.pack(fill="x", padx=PAD)
        self.today_entry = self._entry(self.root, "add_today", "today")
        self.today_entry.frame.pack(fill="x", padx=PAD, pady=(4, 8))

        self.later_head = self._section_head("later")
        self.later_box = tk.Frame(self.root, bg=T["bg"])
        self.later_entry = self._entry(self.later_box, "add_later", "later")

        self.done_head = self._section_head("done")
        self.done_box = tk.Frame(self.root, bg=T["bg"])
        self.bottom_pad = tk.Frame(self.root, bg=T["bg"], height=6)
        self.bottom_pad.pack(fill="x")

    def _section_head(self, name):
        label = tk.Label(
            self.root, text="", bg=T["bg"], fg=T["muted"], font=self.font_small,
            anchor="w", cursor="hand2",
        )
        label._own_click = True
        label.bind("<Button-1>", lambda _e: self._toggle(name))
        label.bind("<Button-3>", self._popup)
        label.pack(fill="x", padx=PAD, pady=(2, 2))
        return label

    def _entry(self, parent, placeholder_key, target):
        """Поле вводу з підказкою всередині. Enter — додати задачу в target."""
        frame = tk.Frame(parent, bg=T["track"], padx=1, pady=1)
        entry = tk.Entry(
            frame, bg=T["bg"], fg=T["muted"], insertbackground=T["fg"],
            relief="flat", font=self.font_task, bd=4,
        )
        entry.pack(fill="x")
        entry.frame = frame
        entry.placeholder_key = placeholder_key
        entry.showing_hint = True
        entry.insert(0, tr(placeholder_key))

        def focus_in(_e):
            self.allow_keyboard(True)
            if entry.showing_hint:
                entry.delete(0, "end")
                entry.config(fg=T["fg"])
                entry.showing_hint = False
            frame.config(bg=T["accent"])

        def focus_out(_e):
            # відкладено: під час активації вікна Tk на мить віддає фокус
            # кореню і одразу повертає — такий хибний FocusOut не має
            # ні стирати набране, ні знову забороняти вікну клавіатуру
            self.root.after(150, settle)

        def settle():
            if self.root.focus_get() is entry:
                return
            frame.config(bg=T["track"])
            if not entry.get().strip():
                self._show_hint(entry)
            if not isinstance(self.root.focus_get(), tk.Entry):
                self.allow_keyboard(False)

        def submit(_e):
            text = entry.get().strip()
            if text:
                self.tasks[target].append(new_task(text))
                self.save()
                entry.delete(0, "end")
                self.render()
            return "break"

        def cancel(_e):
            entry.delete(0, "end")
            self.root.focus_set()  # FocusOut поверне підказку й прапорець

        def click(_e):
            # у режимі робочого столу вікно не активується, і Tk сам фокус
            # полю не дасть — FocusIn не прийде взагалі. Тому фокус силоміць
            self.allow_keyboard(True)
            # після активації Windows Tk повертає фокус туди, де він був у
            # вікні востаннє (корінь), — тож поле просимо вже після неї
            self.root.after(60, entry.focus_force)

        entry.bind("<Button-1>", click, add="+")
        entry.bind("<FocusIn>", focus_in)
        entry.bind("<FocusOut>", focus_out)
        entry.bind("<Return>", submit)
        entry.bind("<Escape>", cancel)
        return entry

    def _show_hint(self, entry):
        entry.delete(0, "end")
        entry.insert(0, tr(entry.placeholder_key))
        entry.config(fg=T["muted"])
        entry.showing_hint = True

    def _menu_items(self, menu):
        menu.add_command(label=tr("m_clear_done"), command=self.clear_done)
        menu.add_separator()

    # -- дії ------------------------------------------------------------------

    def save(self):
        save_json(TASKS_PATH, self.tasks)

    def _take(self, source, task_id):
        for i, task in enumerate(self.tasks[source]):
            if task["id"] == task_id:
                return self.tasks[source].pop(i)
        return None

    def move(self, source, target, task_id):
        task = self._take(source, task_id)
        if task is None:
            return
        if target == "done":
            task["done_at"] = time.time()
            self.tasks["done"].insert(0, task)  # найсвіжіші вгорі
        else:
            task.pop("done_at", None)
            self.tasks[target].append(task)
        self.save()
        self.render()

    def delete(self, source, task_id):
        if self._take(source, task_id) is not None:
            self.save()
            self.render()

    def clear_done(self):
        self.tasks["done"] = []
        self.save()
        self.render()

    def _toggle(self, name):
        key = "open_" + name
        self.settings[key] = not self.settings.get(key, False)
        self.save_settings()
        self.render()

    # -- малювання ------------------------------------------------------------

    def _task_row(self, parent, task, source):
        row = tk.Frame(parent, bg=T["bg"])
        row.pack(fill="x", pady=1)

        if source == "today":
            mark, mark_fg, action = "○", T["accent"], ("done",)
        elif source == "later":
            mark, mark_fg, action = "↑", T["accent"], ("today",)
        else:
            mark, mark_fg, action = "✓", T["green"], ("today",)

        button = tk.Label(
            row, text=mark, bg=T["bg"], fg=mark_fg, cursor="hand2",
            font=("Segoe UI Semibold", 10), width=2, anchor="n",
        )
        button._own_click = True
        button._own_menu = True
        button.pack(side="left", anchor="n")
        button.bind("<Button-1>", lambda _e: self.move(source, action[0], task["id"]))
        if source == "today":
            button.bind("<Enter>", lambda _e: button.config(text="●"))
            button.bind("<Leave>", lambda _e: button.config(text="○"))

        text = tk.Label(
            row, text=task["text"], bg=T["bg"],
            fg=T["muted"] if source != "today" else T["fg"],
            font=self.font_done if source == "done" else self.font_task,
            anchor="w", justify="left", wraplength=WIDTH - 2 * PAD - 30,
        )
        text._own_menu = True
        text.pack(side="left", fill="x", expand=True)

        if source == "done" and task.get("done_at"):
            when = datetime.fromtimestamp(task["done_at"])
            if when.date() != datetime.now().date():
                tk.Label(row, text=when.strftime("%d.%m"), bg=T["bg"], fg=T["muted"],
                         font=self.font_small).pack(side="right", anchor="n")

        for widget in (row, button, text):
            widget.bind("<Button-3>", lambda e, s=source, i=task["id"]: self._task_menu(e, s, i))
        row._own_menu = True
        return row

    def _task_menu(self, event, source, task_id):
        menu = tk.Menu(self.root, tearoff=0)
        if source == "today":
            menu.add_command(label=tr("t_done"), command=lambda: self.move(source, "done", task_id))
            menu.add_command(label=tr("t_to_later"), command=lambda: self.move(source, "later", task_id))
        elif source == "later":
            menu.add_command(label=tr("t_to_today"), command=lambda: self.move(source, "today", task_id))
            menu.add_command(label=tr("t_done"), command=lambda: self.move(source, "done", task_id))
        else:
            menu.add_command(label=tr("t_restore"), command=lambda: self.move(source, "today", task_id))
        menu.add_separator()
        menu.add_command(label=tr("t_delete"), command=lambda: self.delete(source, task_id))
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()
        return "break"

    def _fill(self, box, items, source, empty_text=None):
        for child in box.winfo_children():
            if child is not getattr(self, "later_entry", None) and \
                    child is not getattr(self.later_entry, "frame", None):
                child.destroy()
        if not items and empty_text:
            tk.Label(box, text=empty_text, bg=T["bg"], fg=T["muted"],
                     font=self.font_small, anchor="w").pack(fill="x", pady=(0, 2))
        for task in items:
            self.bind_drag(self._task_row(box, task, source))

    def render(self):
        done_today = sum(
            1 for t in self.tasks["done"]
            if datetime.fromtimestamp(t.get("done_at", 0)).date() == datetime.now().date())
        total = done_today + len(self.tasks["today"])
        self.status.config(text="%d/%d" % (done_today, total) if total else "", fg=T["muted"])

        self._fill(self.today_box, self.tasks["today"], "today", tr("no_tasks"))

        # «на потім»: список + власне поле, щоб задачу можна було одразу відкласти
        opened = self.settings.get("open_later", False)
        self.later_head.config(text=("▾ " if opened else "▸ ") + tr("later", n=len(self.tasks["later"])))
        self.later_entry.frame.pack_forget()
        self._fill(self.later_box, self.tasks["later"], "later")
        self.later_entry.frame.pack(fill="x", pady=(4, 6))
        self.later_box.pack_forget()
        if opened:
            self.later_box.pack(fill="x", padx=PAD, after=self.later_head)

        opened = self.settings.get("open_done", False)
        self.done_head.config(text=("▾ " if opened else "▸ ") + tr("done", n=len(self.tasks["done"])))
        self._fill(self.done_box, self.tasks["done"][:DONE_SHOWN], "done")
        self.done_box.pack_forget()
        if opened:
            self.done_box.pack(fill="x", padx=PAD, after=self.done_head)

        self.fit_height()

    def retheme(self):
        for widget in (self.today_box, self.later_box, self.done_box, self.bottom_pad):
            widget.config(bg=T["bg"])
        for head in (self.later_head, self.done_head):
            head.config(bg=T["bg"], fg=T["muted"])
        for entry in (self.today_entry, self.later_entry):
            entry.frame.config(bg=T["track"])
            entry.config(bg=T["bg"], fg=T["muted"] if entry.showing_hint else T["fg"],
                         insertbackground=T["fg"])
        self.render()

    def relabel(self):
        for entry in (self.today_entry, self.later_entry):
            if entry.showing_hint:
                self._show_hint(entry)
        self.render()


def main():
    set_dpi_awareness()
    TasksWidget().run()


if __name__ == "__main__":
    main()
