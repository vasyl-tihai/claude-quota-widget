# -*- coding: utf-8 -*-
"""Спільна основа віджетів: вікно на робочому столі, теми, переклади.

Використовують і quota_widget.py, і tasks_widget.py. Кожен віджет —
окремий процес зі своїм файлом налаштувань і своїм записом автозапуску.
"""

import ctypes
import json
import os
import sys
import winreg
from ctypes import wintypes

import tkinter as tk

HERE = os.path.dirname(os.path.abspath(__file__))

# --- WinAPI для режиму «на робочому столі» -----------------------------------

GWL_EXSTYLE = -20
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_NOACTIVATE = 0x08000000
HWND_BOTTOM = 1
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOACTIVATE = 0x0010
PIN_INTERVAL_MS = 2000

DWMWA_WINDOW_CORNER_PREFERENCE = 33
DWMWCP_ROUND = 2
CORNER_RADIUS = 12  # для запасного способу через регіон

GW_HWNDNEXT = 2
DWMWA_CLOAKED = 14
# те, що нормально лежить під віджетом: сам робочий стіл і сусідні віджети Tk
BOTTOM_CLASSES = ("Progman", "WorkerW", "SHELLDLL_DefView", "SysListView32")

_user32 = ctypes.windll.user32
_user32.GetWindow.restype = wintypes.HWND
_user32.GetWindow.argtypes = [wintypes.HWND, ctypes.c_uint]

WIDTH = 268
PAD = 14


def real_window(hwnd):
    """Чи це справжнє видиме вікно, а не порожнє або приховане системне."""
    if not _user32.IsWindowVisible(hwnd):
        return False
    rect = wintypes.RECT()
    _user32.GetWindowRect(hwnd, ctypes.byref(rect))
    if rect.right - rect.left <= 1 or rect.bottom - rect.top <= 1:
        return False
    # згорнуті вікна UWP лишаються «видимими» — їх видає лише прапорець cloaked
    cloaked = ctypes.c_int(0)
    try:
        ctypes.windll.dwmapi.DwmGetWindowAttribute(
            hwnd, DWMWA_CLOAKED, ctypes.byref(cloaked), ctypes.sizeof(cloaked))
    except (AttributeError, OSError):
        return True
    return cloaked.value == 0


def something_below(hwnd):
    """Чи є під вікном щось, крім робочого стола й сусідніх віджетів Tk."""
    name = ctypes.create_unicode_buffer(256)
    nxt = _user32.GetWindow(hwnd, GW_HWNDNEXT)
    while nxt:
        if real_window(nxt):
            _user32.GetClassNameW(nxt, name, 256)
            if name.value not in BOTTOM_CLASSES and not name.value.startswith("Tk"):
                return True
        nxt = _user32.GetWindow(nxt, GW_HWNDNEXT)
    return False


# --- теми --------------------------------------------------------------------
# green/amber/red — кольори рівня (норма / увага / критично).
# day/session/week/model — власний колір кожного ліміту для режиму
# «свій колір на ліміт»; accent — позначки й кнопки віджета задач.

THEMES = {
    "light": {
        "bg": "#f6f6f6", "fg": "#1f2328", "muted": "#6b7280", "track": "#dfe1e4",
        "green": "#1f883d", "amber": "#9a6700", "red": "#cf222e", "tick": "#8c95a1",
        "day": "#8250df", "session": "#0969da", "week": "#1a7f37", "model": "#bf3989",
        "accent": "#0969da",
    },
    "dark": {
        "bg": "#14161a", "fg": "#e8eaed", "muted": "#868d99", "track": "#272b33",
        "green": "#3fb950", "amber": "#d29922", "red": "#f85149", "tick": "#5b6473",
        "day": "#a371f7", "session": "#58a6ff", "week": "#3fb950", "model": "#f778ba",
        "accent": "#58a6ff",
    },
    "ocean": {
        "bg": "#0f1d2e", "fg": "#e3eefb", "muted": "#8aa3bf", "track": "#1f334a",
        "green": "#2ec4a6", "amber": "#f2b544", "red": "#ff6b6b", "tick": "#56708d",
        "day": "#7cc4ff", "session": "#4f9dff", "week": "#2ec4a6", "model": "#b69cff",
        "accent": "#4f9dff",
    },
    "violet": {
        "bg": "#1c1528", "fg": "#efe7fb", "muted": "#a293bb", "track": "#31264a",
        "green": "#6fdc8c", "amber": "#f5c451", "red": "#ff6f91", "tick": "#6d5d8a",
        "day": "#c58bff", "session": "#8f7bff", "week": "#5ccfe6", "model": "#ff8fd8",
        "accent": "#c58bff",
    },
    "forest": {
        "bg": "#142019", "fg": "#e5f2e9", "muted": "#8fa999", "track": "#24362b",
        "green": "#6bcf7f", "amber": "#e6b450", "red": "#f07167", "tick": "#58705f",
        "day": "#a3d977", "session": "#56c2a6", "week": "#6bcf7f", "model": "#e9c46a",
        "accent": "#6bcf7f",
    },
    "sand": {
        "bg": "#f7f1e6", "fg": "#2d2418", "muted": "#7d6e5a", "track": "#e6dcc9",
        "green": "#3f7f3a", "amber": "#b0700c", "red": "#c2362b", "tick": "#a8977d",
        "day": "#c0552f", "session": "#2f6f9f", "week": "#3f7f3a", "model": "#8a4f9e",
        "accent": "#c0552f",
    },
}
THEME_ORDER = ["light", "dark", "ocean", "violet", "forest", "sand"]

# Поточна палітра. Оновлюється НА МІСЦІ (T.update), а не перезаписується новим
# словником — щоб усі, хто вже тримає посилання на T, бачили нові кольори.
T = dict(THEMES["light"])


# --- переклади ---------------------------------------------------------------

LANG_ORDER = ["uk", "en", "pl", "de", "es"]
LANG_NAMES = {"uk": "Українська", "en": "English", "pl": "Polski",
              "de": "Deutsch", "es": "Español"}

STRINGS = {
    "uk": {
        "m_token": "Свій токен…", "token_prompt": "OAuth-токен підписки Claude (claude setup-token).\nПорожньо — брати вхід із claude.", "st_apikey": "API-ключ без квоти",
        "quota_title": "Квота Claude", "today": "Сьогодні", "session": "5 годин",
        "week": "Тиждень", "model_limit": "Модель",
        "day_note": "{used:.1f} з {budget:.1f}% тижня · ресет о {time}",
        "reset_at": "ресет о {time}", "reset_wd": "ресет {wd} {time}",
        "model_now": "Модель: {name}", "model_none": "Модель: —",
        "st_updating": "оновлення…", "st_fresh": "щойно оновлено",
        "st_login": "потрібен claude /login", "st_rejected": "токен не приймається",
        "st_429": "забагато запитів, чекаю", "st_error": "помилка {code}",
        "st_offline": "нема зв'язку", "st_nocred": "нема входу в claude",
        "m_refresh": "Оновити зараз", "m_theme": "Тема", "m_alpha": "Прозорість",
        "m_desktop": "На робочому столі (під вікнами)", "m_top": "Поверх усіх вікон",
        "m_autostart": "Запускати з Windows", "m_lang": "Мова", "m_close": "Закрити",
        "m_bars": "Колір смуг", "m_bars_level": "За рівнем витрати",
        "m_bars_limit": "Свій колір на кожен ліміт",
        "m_numbers": "Фарбувати відсотки", "m_thresholds": "Пороги кольору",
        "m_show_model": "Показувати модель",
        "th_light": "Світла", "th_dark": "Темна", "th_ocean": "Океан",
        "th_violet": "Фіалка", "th_forest": "Ліс", "th_sand": "Пісок",
        "tasks_title": "Задачі на сьогодні", "add_today": "+ нова задача",
        "add_later": "+ на потім", "later": "На потім ({n})", "done": "Виконані ({n})",
        "no_tasks": "Задач немає", "t_to_later": "Перенести на потім",
        "t_to_today": "На сьогодні", "t_done": "Виконано", "t_restore": "Повернути",
        "t_delete": "Видалити", "m_clear_done": "Очистити виконані",
        "weekdays": ["пн", "вт", "ср", "чт", "пт", "сб", "нд"],
    },
    "en": {
        "m_token": "Own token…", "token_prompt": "Claude subscription OAuth token (claude setup-token).\nLeave empty to use the claude login.", "st_apikey": "API key has no quota",
        "quota_title": "Claude Quota", "today": "Today", "session": "5 hours",
        "week": "Week", "model_limit": "Model",
        "day_note": "{used:.1f} of {budget:.1f}% week · resets {time}",
        "reset_at": "resets {time}", "reset_wd": "resets {wd} {time}",
        "model_now": "Model: {name}", "model_none": "Model: —",
        "st_updating": "updating…", "st_fresh": "just updated",
        "st_login": "run claude /login", "st_rejected": "token rejected",
        "st_429": "rate limited, waiting", "st_error": "error {code}",
        "st_offline": "offline", "st_nocred": "not logged in",
        "m_refresh": "Refresh now", "m_theme": "Theme", "m_alpha": "Opacity",
        "m_desktop": "On desktop (below windows)", "m_top": "Always on top",
        "m_autostart": "Start with Windows", "m_lang": "Language", "m_close": "Close",
        "m_bars": "Bar colors", "m_bars_level": "By usage level",
        "m_bars_limit": "Own color per limit",
        "m_numbers": "Color the percentages", "m_thresholds": "Color thresholds",
        "m_show_model": "Show model",
        "th_light": "Light", "th_dark": "Dark", "th_ocean": "Ocean",
        "th_violet": "Violet", "th_forest": "Forest", "th_sand": "Sand",
        "tasks_title": "Today's tasks", "add_today": "+ new task",
        "add_later": "+ for later", "later": "Later ({n})", "done": "Done ({n})",
        "no_tasks": "No tasks", "t_to_later": "Move to later",
        "t_to_today": "Move to today", "t_done": "Mark done", "t_restore": "Restore",
        "t_delete": "Delete", "m_clear_done": "Clear done",
        "weekdays": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
    },
    "pl": {
        "m_token": "Własny token…", "token_prompt": "Token OAuth subskrypcji Claude (claude setup-token).\nPuste — użyj logowania claude.", "st_apikey": "klucz API bez limitów",
        "quota_title": "Limity Claude", "today": "Dziś", "session": "5 godzin",
        "week": "Tydzień", "model_limit": "Model",
        "day_note": "{used:.1f} z {budget:.1f}% tyg. · reset o {time}",
        "reset_at": "reset o {time}", "reset_wd": "reset {wd} {time}",
        "model_now": "Model: {name}", "model_none": "Model: —",
        "st_updating": "odświeżanie…", "st_fresh": "właśnie odświeżono",
        "st_login": "wymagane claude /login", "st_rejected": "token odrzucony",
        "st_429": "za dużo zapytań", "st_error": "błąd {code}",
        "st_offline": "brak połączenia", "st_nocred": "brak logowania",
        "m_refresh": "Odśwież teraz", "m_theme": "Motyw", "m_alpha": "Przezroczystość",
        "m_desktop": "Na pulpicie (pod oknami)", "m_top": "Zawsze na wierzchu",
        "m_autostart": "Uruchamiaj z Windows", "m_lang": "Język", "m_close": "Zamknij",
        "m_bars": "Kolor pasków", "m_bars_level": "Według poziomu zużycia",
        "m_bars_limit": "Własny kolor dla limitu",
        "m_numbers": "Koloruj procenty", "m_thresholds": "Progi koloru",
        "m_show_model": "Pokazuj model",
        "th_light": "Jasny", "th_dark": "Ciemny", "th_ocean": "Ocean",
        "th_violet": "Fiolet", "th_forest": "Las", "th_sand": "Piasek",
        "tasks_title": "Zadania na dziś", "add_today": "+ nowe zadanie",
        "add_later": "+ na później", "later": "Na później ({n})",
        "done": "Zrobione ({n})", "no_tasks": "Brak zadań",
        "t_to_later": "Przenieś na później", "t_to_today": "Na dziś",
        "t_done": "Zrobione", "t_restore": "Przywróć", "t_delete": "Usuń",
        "m_clear_done": "Wyczyść zrobione",
        "weekdays": ["pn", "wt", "śr", "czw", "pt", "sob", "nd"],
    },
    "de": {
        "m_token": "Eigenes Token…", "token_prompt": "OAuth-Token des Claude-Abos (claude setup-token).\nLeer lassen für die claude-Anmeldung.", "st_apikey": "API-Key: kein Abo",
        "quota_title": "Claude-Kontingent", "today": "Heute", "session": "5 Stunden",
        "week": "Woche", "model_limit": "Modell",
        "day_note": "{used:.1f} von {budget:.1f}% Woche · Reset {time}",
        "reset_at": "Reset um {time}", "reset_wd": "Reset {wd} {time}",
        "model_now": "Modell: {name}", "model_none": "Modell: —",
        "st_updating": "aktualisiere…", "st_fresh": "gerade aktualisiert",
        "st_login": "claude /login nötig", "st_rejected": "Token abgelehnt",
        "st_429": "zu viele Anfragen", "st_error": "Fehler {code}",
        "st_offline": "keine Verbindung", "st_nocred": "nicht angemeldet",
        "m_refresh": "Jetzt aktualisieren", "m_theme": "Design", "m_alpha": "Deckkraft",
        "m_desktop": "Auf dem Desktop (unter Fenstern)", "m_top": "Immer im Vordergrund",
        "m_autostart": "Mit Windows starten", "m_lang": "Sprache", "m_close": "Schließen",
        "m_bars": "Balkenfarbe", "m_bars_level": "Nach Verbrauch",
        "m_bars_limit": "Eigene Farbe je Limit",
        "m_numbers": "Prozente einfärben", "m_thresholds": "Farbschwellen",
        "m_show_model": "Modell anzeigen",
        "th_light": "Hell", "th_dark": "Dunkel", "th_ocean": "Ozean",
        "th_violet": "Violett", "th_forest": "Wald", "th_sand": "Sand",
        "tasks_title": "Aufgaben für heute", "add_today": "+ neue Aufgabe",
        "add_later": "+ für später", "later": "Später ({n})", "done": "Erledigt ({n})",
        "no_tasks": "Keine Aufgaben", "t_to_later": "Auf später verschieben",
        "t_to_today": "Auf heute", "t_done": "Erledigt", "t_restore": "Zurückholen",
        "t_delete": "Löschen", "m_clear_done": "Erledigte leeren",
        "weekdays": ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"],
    },
    "es": {
        "m_token": "Token propio…", "token_prompt": "Token OAuth de la suscripción (claude setup-token).\nVacío: usar el inicio de sesión de claude.", "st_apikey": "clave API sin cuota",
        "quota_title": "Cuota de Claude", "today": "Hoy", "session": "5 horas",
        "week": "Semana", "model_limit": "Modelo",
        "day_note": "{used:.1f} de {budget:.1f}% sem. · reinicio {time}",
        "reset_at": "reinicio {time}", "reset_wd": "reinicio {wd} {time}",
        "model_now": "Modelo: {name}", "model_none": "Modelo: —",
        "st_updating": "actualizando…", "st_fresh": "recién actualizado",
        "st_login": "ejecuta claude /login", "st_rejected": "token rechazado",
        "st_429": "demasiadas solicitudes", "st_error": "error {code}",
        "st_offline": "sin conexión", "st_nocred": "sin sesión",
        "m_refresh": "Actualizar ahora", "m_theme": "Tema", "m_alpha": "Opacidad",
        "m_desktop": "En el escritorio (bajo ventanas)", "m_top": "Siempre encima",
        "m_autostart": "Iniciar con Windows", "m_lang": "Idioma", "m_close": "Cerrar",
        "m_bars": "Color de barras", "m_bars_level": "Según el uso",
        "m_bars_limit": "Color propio por límite",
        "m_numbers": "Colorear porcentajes", "m_thresholds": "Umbrales de color",
        "m_show_model": "Mostrar modelo",
        "th_light": "Claro", "th_dark": "Oscuro", "th_ocean": "Océano",
        "th_violet": "Violeta", "th_forest": "Bosque", "th_sand": "Arena",
        "tasks_title": "Tareas de hoy", "add_today": "+ nueva tarea",
        "add_later": "+ para después", "later": "Después ({n})", "done": "Hechas ({n})",
        "no_tasks": "Sin tareas", "t_to_later": "Pasar a después",
        "t_to_today": "Pasar a hoy", "t_done": "Hecha", "t_restore": "Restaurar",
        "t_delete": "Eliminar", "m_clear_done": "Vaciar hechas",
        "weekdays": ["lun", "mar", "mié", "jue", "vie", "sáb", "dom"],
    },
}

_lang = "en"


def detect_lang():
    """Мова інтерфейсу Windows, якщо ми її підтримуємо, інакше англійська."""
    try:
        primary = ctypes.windll.kernel32.GetUserDefaultUILanguage() & 0x3FF
    except (AttributeError, OSError):
        return "en"
    return {0x22: "uk", 0x09: "en", 0x15: "pl", 0x07: "de", 0x0A: "es"}.get(primary, "en")


def set_lang(code):
    global _lang
    _lang = code if code in STRINGS else "en"


def get_lang():
    return _lang


def tr(key, **kw):
    text = STRINGS[_lang].get(key, STRINGS["en"].get(key, key))
    return text.format(**kw) if kw else text


# --- налаштування ------------------------------------------------------------


def load_json(path):
    try:
        # utf-8-sig: файл можна правити руками, а Блокнот і PowerShell
        # додають BOM — на ньому json.load падає, і дані мовчки скидаються
        with open(path, "r", encoding="utf-8-sig") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_json(path, data):
    """Атомарно: обрізаний файл при читанні = ValueError = порожні дані."""
    try:
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except OSError:
        pass


# --- автозапуск --------------------------------------------------------------

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def autostart_command(script):
    pythonw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    if not os.path.exists(pythonw):
        pythonw = sys.executable
    return '"%s" "%s"' % (pythonw, os.path.join(HERE, script))


def autostart_enabled(app_name):
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            value, _ = winreg.QueryValueEx(key, app_name)
            return bool(value)
    except OSError:
        return False


def set_autostart(app_name, script, enabled):
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        if enabled:
            winreg.SetValueEx(key, app_name, 0, winreg.REG_SZ, autostart_command(script))
        else:
            try:
                winreg.DeleteValue(key, app_name)
            except OSError:
                pass


def set_dpi_awareness():
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass


# --- вікно -------------------------------------------------------------------


class DesktopWindow:
    """Безрамкове вікно-віджет: робочий стіл або поверх усіх, кути, меню.

    Нащадок задає APP_NAME, SCRIPT, SETTINGS_FILE, TITLE_KEY і реалізує
    _build_body(), _menu_items(menu), retheme(), relabel(), а за потреби
    fallback_settings() — звідки взяти тему й мову при першому запуску.
    """

    APP_NAME = ""
    SCRIPT = ""
    SETTINGS_FILE = ""
    TITLE_KEY = ""

    def __init__(self):
        self.root = tk.Tk()
        self.root.overrideredirect(True)

        self.settings_path = os.path.join(HERE, self.SETTINGS_FILE)
        self.settings = load_json(self.settings_path)
        for key, value in self.fallback_settings().items():
            self.settings.setdefault(key, value)
        if "lang" not in self.settings:
            self.settings["lang"] = detect_lang()
        set_lang(self.settings["lang"])
        self.root.title(tr(self.TITLE_KEY))

        # палітру ставимо ДО побудови — інакше віджети народяться в старих кольорах
        T.update(THEMES.get(self.settings.get("theme", "light"), THEMES["light"]))
        self.root.configure(bg=T["bg"])
        self.root.attributes("-alpha", self.settings.get("alpha", 0.92))

        self.stop = False
        self._pin_timer = None
        self._pin_paused = False

        self._build_header()
        self._build_body()
        self.bind_drag(self.root)
        self._restore_position()
        self._build_menu()

        self.root.after(50, self.round_corners)
        self.root.after(60, lambda: self.set_mode(self.settings.get("mode", "desktop")))
        self.root.protocol("WM_DELETE_WINDOW", self.close)

    # -- для нащадків ---------------------------------------------------------

    def fallback_settings(self):
        return {}

    def _build_body(self):
        raise NotImplementedError

    def _menu_items(self, menu):
        """Власні пункти віджета — на початку меню."""

    def retheme(self):
        """Перефарбувати власні елементи під поточну T."""

    def relabel(self):
        """Переписати власні підписи під поточну мову."""

    # -- побудова -------------------------------------------------------------

    def _build_header(self):
        self.head = tk.Frame(self.root, bg=T["bg"])
        self.head.pack(fill="x", padx=PAD, pady=(11, 9))

        self.head_title = tk.Label(
            self.head, text=tr(self.TITLE_KEY), bg=T["bg"], fg=T["fg"],
            font=("Segoe UI Semibold", 10),
        )
        self.head_title.pack(side="left")

        # ⚙ праворуч: те саме меню, що на правій кнопці, але його видно
        self.gear = tk.Label(
            self.head, text="⚙", bg=T["bg"], fg=T["muted"],
            font=("Segoe UI", 9), width=2, cursor="hand2",
        )
        self.gear.pack(side="right")
        self.gear.bind("<Button-1>", lambda _e: self._open_menu())
        self.gear.bind("<Enter>", lambda _e: self.gear.config(fg=T["fg"]))
        self.gear.bind("<Leave>", lambda _e: self.gear.config(fg=T["muted"]))

        self.status = tk.Label(
            self.head, text="", bg=T["bg"], fg=T["muted"], font=("Segoe UI", 8),
        )
        self.status.pack(side="right")

    def _all_widgets(self, parent):
        result = [parent]
        for child in parent.winfo_children():
            result.extend(self._all_widgets(child))
        return result

    def bind_drag(self, parent, skip=()):
        """Перетягування лівою і меню правою — на всі віджети під parent.

        Повторний bind заміщає попередній обробник, тому ⚙ і все, що має
        власну ліву кнопку (поля вводу, позначки задач), треба обходити —
        інакше перетягування затирає їхні кліки.
        """
        for widget in self._all_widgets(parent):
            if widget is self.gear or widget in skip or isinstance(widget, tk.Entry):
                continue
            if getattr(widget, "_own_click", False):
                continue
            widget.bind("<Button-1>", self._drag_start)
            widget.bind("<B1-Motion>", self._drag_move)
            widget.bind("<ButtonRelease-1>", self._drag_end)
            if not getattr(widget, "_own_menu", False):
                widget.bind("<Button-3>", self._popup)

    def _build_menu(self):
        self.menu = tk.Menu(self.root, tearoff=0)
        self._menu_items(self.menu)

        theme_menu = tk.Menu(self.menu, tearoff=0)
        self.theme_var = tk.StringVar(value=self.settings.get("theme", "light"))
        for name in THEME_ORDER:
            theme_menu.add_radiobutton(
                label=tr("th_" + name), variable=self.theme_var, value=name,
                command=lambda n=name: self.set_theme(n),
            )
        self.menu.add_cascade(label=tr("m_theme"), menu=theme_menu)

        alpha_menu = tk.Menu(self.menu, tearoff=0)
        for label, value in (("70%", 0.70), ("85%", 0.85), ("92%", 0.92), ("100%", 1.0)):
            alpha_menu.add_command(label=label, command=lambda v=value: self.set_alpha(v))
        self.menu.add_cascade(label=tr("m_alpha"), menu=alpha_menu)

        lang_menu = tk.Menu(self.menu, tearoff=0)
        self.lang_var = tk.StringVar(value=get_lang())
        for code in LANG_ORDER:
            lang_menu.add_radiobutton(
                label=LANG_NAMES[code], variable=self.lang_var, value=code,
                command=lambda c=code: self.change_lang(c),
            )
        self.menu.add_cascade(label=tr("m_lang"), menu=lang_menu)
        self.menu.add_separator()

        self.mode_var = tk.StringVar(value=self.settings.get("mode", "desktop"))
        self.menu.add_radiobutton(
            label=tr("m_desktop"), variable=self.mode_var,
            value="desktop", command=lambda: self.set_mode("desktop"),
        )
        self.menu.add_radiobutton(
            label=tr("m_top"), variable=self.mode_var,
            value="top", command=lambda: self.set_mode("top"),
        )
        self.autostart_var = tk.BooleanVar(value=autostart_enabled(self.APP_NAME))
        self.menu.add_checkbutton(
            label=tr("m_autostart"), variable=self.autostart_var,
            command=lambda: set_autostart(
                self.APP_NAME, self.SCRIPT, self.autostart_var.get()),
        )
        self.menu.add_separator()
        self.menu.add_command(label=tr("m_close"), command=self.close)

    def _popup(self, event):
        try:
            self.menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.menu.grab_release()

    def _open_menu(self):
        """Те саме меню, але від кнопки ⚙ — під нею, а не під курсором."""
        try:
            self.menu.tk_popup(
                self.gear.winfo_rootx(),
                self.gear.winfo_rooty() + self.gear.winfo_height(),
            )
        finally:
            self.menu.grab_release()

    # -- режим показу ---------------------------------------------------------

    def _hwnd(self):
        """Справжній HWND вікна (у Tk на Windows це може бути батько)."""
        raw = self.root.winfo_id()
        parent = _user32.GetParent(raw)
        return parent or raw

    def round_corners(self):
        """Заокруглює кути: спершу рідним способом Windows 11 (зі згладжуванням),
        інакше — обрізанням вікна по регіону (кути жорсткі, зате працює всюди)."""
        try:
            value = ctypes.c_int(DWMWCP_ROUND)
            result = ctypes.windll.dwmapi.DwmSetWindowAttribute(
                self._hwnd(), DWMWA_WINDOW_CORNER_PREFERENCE,
                ctypes.byref(value), ctypes.sizeof(value),
            )
            if result == 0:
                self._use_region = False
                return
        except (AttributeError, OSError):
            pass
        self._use_region = True
        self._apply_region()

    def _apply_region(self):
        """Запасний шлях: обрізати вікно заокругленим прямокутником."""
        if not getattr(self, "_use_region", False):
            return
        self.root.update_idletasks()
        w = self.root.winfo_width()
        h = self.root.winfo_height()
        if w <= 1 or h <= 1:
            return
        region = ctypes.windll.gdi32.CreateRoundRectRgn(
            0, 0, w + 1, h + 1, CORNER_RADIUS * 2, CORNER_RADIUS * 2
        )
        _user32.SetWindowRgn(self._hwnd(), region, True)

    def set_mode(self, mode):
        """desktop — лежить на робочому столі під вікнами; top — поверх усіх."""
        self.settings["mode"] = mode
        self.save_settings()
        if hasattr(self, "mode_var"):
            self.mode_var.set(mode)

        hwnd = self._hwnd()
        style = _user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        if mode == "desktop":
            self.root.attributes("-topmost", False)
            # не забирати фокус у програми, з якою працюють, і не лізти в Alt+Tab
            _user32.SetWindowLongW(
                hwnd, GWL_EXSTYLE, style | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE
            )
            self._cancel_pin()
            self._pin_to_bottom()
        else:
            self._cancel_pin()
            _user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style & ~WS_EX_NOACTIVATE)
            self.root.attributes("-topmost", True)

    def allow_keyboard(self, enabled):
        """Тимчасово дозволити вікну фокус — для друку в полі вводу.

        У режимі робочого столу стоїть WS_EX_NOACTIVATE: вікно не активується,
        тож і клавіатура до нього не доходить. На час друку прапорець знімаємо,
        а притискання донизу ставимо на паузу, щоб вікно не пірнало під інші.
        """
        if self.settings.get("mode") != "desktop":
            return
        hwnd = self._hwnd()
        style = _user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        if enabled:
            self._pin_paused = True
            _user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style & ~WS_EX_NOACTIVATE)
            _user32.SetForegroundWindow(hwnd)
        else:
            self._pin_paused = False
            _user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style | WS_EX_NOACTIVATE)

    def _pin_to_bottom(self):
        """Тримає вікно в самому низу порядку — інакше воно спливає нагору.

        SetWindowPos викликається ЛИШЕ коли є що виправляти: у напівпрозорого
        вікна кожен виклик змушує DWM перезмішати його з тлом, і все вікно
        помітно блимає раз на PIN_INTERVAL_MS.
        """
        if self.stop or self.settings.get("mode") != "desktop":
            return
        if not self._pin_paused and something_below(self._hwnd()):
            _user32.SetWindowPos(
                self._hwnd(), HWND_BOTTOM, 0, 0, 0, 0,
                SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE,
            )
        self._pin_timer = self.root.after(PIN_INTERVAL_MS, self._pin_to_bottom)

    def _cancel_pin(self):
        if self._pin_timer is not None:
            self.root.after_cancel(self._pin_timer)
            self._pin_timer = None

    # -- позиція і налаштування ---------------------------------------------

    def save_settings(self):
        save_json(self.settings_path, self.settings)

    def default_position(self):
        return self.root.winfo_screenwidth() - WIDTH - 24, 60

    def _restore_position(self):
        self.root.update_idletasks()
        height = self.root.winfo_reqheight()
        x = self.settings.get("x")
        y = self.settings.get("y")
        if x is None or y is None:
            x, y = self.default_position()
        # не дати вікну лишитись за межами екрана
        x = max(0, min(x, self.root.winfo_screenwidth() - 80))
        y = max(0, min(y, self.root.winfo_screenheight() - 60))
        self.root.geometry("%dx%d+%d+%d" % (WIDTH, height, x, y))

    def _drag_start(self, event):
        self._drag = (event.x_root, event.y_root,
                      self.root.winfo_x(), self.root.winfo_y())

    def _drag_move(self, event):
        if not hasattr(self, "_drag"):
            return
        sx, sy, wx, wy = self._drag
        self.root.geometry("+%d+%d" % (wx + event.x_root - sx, wy + event.y_root - sy))

    def _drag_end(self, _event):
        self.settings["x"] = self.root.winfo_x()
        self.settings["y"] = self.root.winfo_y()
        self.save_settings()

    def fit_height(self):
        self.root.update_idletasks()
        self.root.geometry("%dx%d" % (WIDTH, self.root.winfo_reqheight() + 6))
        self._apply_region()  # висота змінилась — регіон треба перерізати

    def set_alpha(self, value):
        self.settings["alpha"] = value
        self.root.attributes("-alpha", value)
        self.save_settings()

    def set_theme(self, name):
        T.update(THEMES[name])
        self.settings["theme"] = name
        self.save_settings()
        self.theme_var.set(name)
        self.root.config(bg=T["bg"])
        self.head.config(bg=T["bg"])
        self.head_title.config(bg=T["bg"], fg=T["fg"])
        self.gear.config(bg=T["bg"], fg=T["muted"])
        self.status.config(bg=T["bg"])
        self.retheme()

    def change_lang(self, code):
        set_lang(code)
        self.settings["lang"] = code
        self.save_settings()
        self.root.title(tr(self.TITLE_KEY))
        self.head_title.config(text=tr(self.TITLE_KEY))
        self.menu.destroy()
        self._build_menu()
        self.relabel()

    def close(self):
        # позицію тут НЕ зберігаємо: вона вже збережена на кінці перетягування,
        # а у вікна, яке ще не з'явилось на екрані, winfo_x() дає 0 — і закриття
        # такого вікна затирало б збережену позицію нулями
        self.stop = True
        self.root.destroy()

    def run(self):
        self.root.mainloop()
