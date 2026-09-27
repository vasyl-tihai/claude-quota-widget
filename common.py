# -*- coding: utf-8 -*-
"""Спільна основа віджетів: вікно на робочому столі, теми, переклади.

Використовують і quota_widget.py, і tasks_widget.py. Кожен віджет —
окремий процес зі своїм файлом налаштувань і своїм записом автозапуску.
"""

import ctypes
import json
import os
import subprocess
import sys
import winreg
from ctypes import wintypes

import tkinter as tk
import tkinter.font as tkfont

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
# «свій колір на ліміт»; accent — позначки й кнопки віджета задач;
# opus/sonnet/haiku/fable/other — постійний колір кожної сім'ї моделей.

THEMES = {
    "light": {
        "bg": "#f6f6f6", "fg": "#1f2328", "muted": "#6b7280", "track": "#dfe1e4",
        "green": "#1f883d", "amber": "#9a6700", "red": "#cf222e", "tick": "#8c95a1",
        "day": "#8250df", "session": "#0969da", "week": "#1a7f37", "model": "#bf3989",
        "accent": "#0969da",
        "opus": "#bc4c00", "sonnet": "#0969da", "haiku": "#1a7f37", "fable": "#8250df", "other": "#6b7280",
    },
    "dark": {
        "bg": "#14161a", "fg": "#e8eaed", "muted": "#868d99", "track": "#272b33",
        "green": "#3fb950", "amber": "#d29922", "red": "#f85149", "tick": "#5b6473",
        "day": "#a371f7", "session": "#58a6ff", "week": "#3fb950", "model": "#f778ba",
        "accent": "#58a6ff",
        "opus": "#ff9e64", "sonnet": "#58a6ff", "haiku": "#3fb950", "fable": "#d2a8ff", "other": "#8b949e",
    },
    "ocean": {
        "bg": "#0f1d2e", "fg": "#e3eefb", "muted": "#8aa3bf", "track": "#1f334a",
        "green": "#2ec4a6", "amber": "#f2b544", "red": "#ff6b6b", "tick": "#56708d",
        "day": "#7cc4ff", "session": "#4f9dff", "week": "#2ec4a6", "model": "#b69cff",
        "accent": "#4f9dff",
        "opus": "#ffb86b", "sonnet": "#4f9dff", "haiku": "#2ec4a6", "fable": "#c9a7ff", "other": "#8aa3bf",
    },
    "violet": {
        "bg": "#1c1528", "fg": "#efe7fb", "muted": "#a293bb", "track": "#31264a",
        "green": "#6fdc8c", "amber": "#f5c451", "red": "#ff6f91", "tick": "#6d5d8a",
        "day": "#c58bff", "session": "#8f7bff", "week": "#5ccfe6", "model": "#ff8fd8",
        "accent": "#c58bff",
        "opus": "#ffab70", "sonnet": "#8f7bff", "haiku": "#5ccfe6", "fable": "#ff8fd8", "other": "#a293bb",
    },
    "forest": {
        "bg": "#142019", "fg": "#e5f2e9", "muted": "#8fa999", "track": "#24362b",
        "green": "#6bcf7f", "amber": "#e6b450", "red": "#f07167", "tick": "#58705f",
        "day": "#a3d977", "session": "#56c2a6", "week": "#6bcf7f", "model": "#e9c46a",
        "accent": "#6bcf7f",
        "opus": "#f4a261", "sonnet": "#56c2a6", "haiku": "#a3d977", "fable": "#e9c46a", "other": "#8fa999",
    },
    "sand": {
        "bg": "#f7f1e6", "fg": "#2d2418", "muted": "#7d6e5a", "track": "#e6dcc9",
        "green": "#3f7f3a", "amber": "#b0700c", "red": "#c2362b", "tick": "#a8977d",
        "day": "#c0552f", "session": "#2f6f9f", "week": "#3f7f3a", "model": "#8a4f9e",
        "accent": "#c0552f",
        "opus": "#c0552f", "sonnet": "#2f6f9f", "haiku": "#3f7f3a", "fable": "#8a4f9e", "other": "#7d6e5a",
    },
}
THEME_ORDER = ["light", "dark", "ocean", "violet", "forest", "sand"]

# Поточна палітра. Оновлюється НА МІСЦІ (T.update), а не перезаписується новим
# словником — щоб усі, хто вже тримає посилання на T, бачили нові кольори.
T = dict(THEMES["light"])


# --- переклади ---------------------------------------------------------------

LANG_ORDER = ["uk", "en", "pl", "de", "es", "fr", "it", "pt", "nl", "cs", "tr", "ja", "zh"]
LANG_NAMES = {"uk": "Українська", "en": "English", "pl": "Polski", "de": "Deutsch",
              "es": "Español", "fr": "Français", "it": "Italiano", "pt": "Português",
              "nl": "Nederlands", "cs": "Čeština", "tr": "Türkçe", "ja": "日本語",
              "zh": "简体中文"}

STRINGS = {
    "uk": {
        "calendar": "Календар", "cal_go_today": "До поточного місяця",
        "m_pace_tick": "Мітка рівного темпу на тижні",
        "m_widgets": "Віджети", "m_apply_all": "Ця тема й мова — для всіх", "m_model_row": "Модель унизу",
        "m_rows": "Показники",
        "models_week": "Моделі за тиждень", "now": "зараз", "models_loading": "Моделі: рахую…",
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
        "m_models": "Моделі внизу", "m_models_current": "Лише поточна", "m_models_week": "Усі за тиждень (кольори й частки)", "m_models_off": "Не показувати",
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
        "calendar": "Calendar", "cal_go_today": "Go to current month",
        "m_pace_tick": "Even-pace mark on Week",
        "m_widgets": "Widgets", "m_apply_all": "Use this theme and language for all", "m_model_row": "Model at the bottom",
        "m_rows": "Rows shown",
        "models_week": "Models this week", "now": "now", "models_loading": "Models: counting…",
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
        "m_models": "Models at the bottom", "m_models_current": "Current only", "m_models_week": "All this week (colors and shares)", "m_models_off": "Hide",
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
        "calendar": "Kalendarz", "cal_go_today": "Do bieżącego miesiąca",
        "m_pace_tick": "Znacznik równego tempa (tydzień)",
        "m_widgets": "Widżety", "m_apply_all": "Ten motyw i język dla wszystkich", "m_model_row": "Model na dole",
        "m_rows": "Wskaźniki",
        "models_week": "Modele w tym tygodniu", "now": "teraz", "models_loading": "Modele: liczę…",
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
        "m_models": "Modele na dole", "m_models_current": "Tylko bieżący", "m_models_week": "Wszystkie w tygodniu (kolory i udziały)", "m_models_off": "Ukryj",
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
        "calendar": "Kalender", "cal_go_today": "Zum aktuellen Monat",
        "m_pace_tick": "Gleichmaß-Marke bei Woche",
        "m_widgets": "Widgets", "m_apply_all": "Dieses Design und diese Sprache für alle", "m_model_row": "Modell unten",
        "m_rows": "Anzeigen",
        "models_week": "Modelle diese Woche", "now": "jetzt", "models_loading": "Modelle: zähle…",
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
        "m_models": "Modelle unten", "m_models_current": "Nur aktuelles", "m_models_week": "Alle dieser Woche (Farben und Anteile)", "m_models_off": "Ausblenden",
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
        "calendar": "Calendario", "cal_go_today": "Ir al mes actual",
        "m_pace_tick": "Marca de ritmo uniforme (semana)",
        "m_widgets": "Widgets", "m_apply_all": "Este tema e idioma para todos", "m_model_row": "Modelo abajo",
        "m_rows": "Indicadores",
        "models_week": "Modelos esta semana", "now": "ahora", "models_loading": "Modelos: contando…",
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
        "m_models": "Modelos abajo", "m_models_current": "Solo el actual", "m_models_week": "Todos esta semana (colores y cuotas)", "m_models_off": "Ocultar",
        "th_light": "Claro", "th_dark": "Oscuro", "th_ocean": "Océano",
        "th_violet": "Violeta", "th_forest": "Bosque", "th_sand": "Arena",
        "tasks_title": "Tareas de hoy", "add_today": "+ nueva tarea",
        "add_later": "+ para después", "later": "Después ({n})", "done": "Hechas ({n})",
        "no_tasks": "Sin tareas", "t_to_later": "Pasar a después",
        "t_to_today": "Pasar a hoy", "t_done": "Hecha", "t_restore": "Restaurar",
        "t_delete": "Eliminar", "m_clear_done": "Vaciar hechas",
        "weekdays": ["lun", "mar", "mié", "jue", "vie", "sáb", "dom"],
    },
    "fr": {
        "calendar": "Calendrier", "cal_go_today": "Aller au mois en cours",
        "m_pace_tick": "Repère de rythme régulier (semaine)",
        "m_widgets": "Widgets", "m_apply_all": "Ce thème et cette langue pour tous", "m_model_row": "Modèle en bas",
        "m_rows": "Lignes affichées",
        "models_week": "Modèles cette semaine",
        "now": "maintenant",
        "models_loading": "Modèles : calcul…",
        "m_token": "Jeton personnel…",
        "token_prompt": "Jeton OAuth de l'abonnement Claude (claude setup-token).\nLaisser vide pour utiliser claude login.",
        "st_apikey": "Clé API sans quota",
        "quota_title": "Quota Claude",
        "today": "Aujourd'hui",
        "session": "5 heures",
        "week": "Semaine",
        "model_limit": "Modèle",
        "day_note": "{used:.1f} de {budget:.1f}% sem. · réinit. {time}",
        "reset_at": "réinit. {time}",
        "reset_wd": "réinit. {wd} {time}",
        "model_now": "Modèle : {name}",
        "model_none": "Modèle : —",
        "st_updating": "mise à jour…",
        "st_fresh": "mis à jour",
        "st_login": "lancer claude /login",
        "st_rejected": "jeton rejeté",
        "st_429": "limité, en attente",
        "st_error": "erreur {code}",
        "st_offline": "hors ligne",
        "st_nocred": "non connecté",
        "m_refresh": "Actualiser",
        "m_theme": "Thème",
        "m_alpha": "Opacité",
        "m_desktop": "Sur le bureau (sous les fenêtres)",
        "m_top": "Toujours au premier plan",
        "m_autostart": "Démarrer avec Windows",
        "m_lang": "Langue",
        "m_close": "Fermer",
        "m_bars": "Couleurs des barres",
        "m_bars_level": "Selon le niveau d'utilisation",
        "m_bars_limit": "Couleur propre par limite",
        "m_numbers": "Colorer les pourcentages",
        "m_thresholds": "Seuils de couleur",
        "m_models": "Modèles en bas",
        "m_models_current": "Actuel seulement",
        "m_models_week": "Toute la semaine (couleurs et parts)",
        "m_models_off": "Masquer",
        "th_light": "Clair",
        "th_dark": "Sombre",
        "th_ocean": "Océan",
        "th_violet": "Violet",
        "th_forest": "Forêt",
        "th_sand": "Sable",
        "tasks_title": "Tâches du jour",
        "add_today": "+ nouvelle tâche",
        "add_later": "+ pour plus tard",
        "later": "Plus tard ({n})",
        "done": "Terminé ({n})",
        "no_tasks": "Aucune tâche",
        "t_to_later": "Reporter",
        "t_to_today": "Déplacer à aujourd'hui",
        "t_done": "Marquer terminé",
        "t_restore": "Restaurer",
        "t_delete": "Supprimer",
        "m_clear_done": "Effacer terminées",
        "weekdays": ["lun", "mar", "mer", "jeu", "ven", "sam", "dim"],
    },
    "it": {
        "calendar": "Calendario", "cal_go_today": "Vai al mese corrente",
        "m_pace_tick": "Segno di ritmo costante (settimana)",
        "m_widgets": "Widget", "m_apply_all": "Questo tema e lingua per tutti", "m_model_row": "Modello in basso",
        "m_rows": "Righe mostrate",
        "models_week": "Modelli questa settimana",
        "now": "ora",
        "models_loading": "Modelli: conteggio…",
        "m_token": "Token personale…",
        "token_prompt": "Token OAuth dell'abbonamento Claude (claude setup-token).\nLascia vuoto per usare claude login.",
        "st_apikey": "Chiave API senza quota",
        "quota_title": "Quota Claude",
        "today": "Oggi",
        "session": "5 ore",
        "week": "Settimana",
        "model_limit": "Modello",
        "day_note": "{used:.1f} di {budget:.1f}% sett. · reset {time}",
        "reset_at": "reset {time}",
        "reset_wd": "reset {wd} {time}",
        "model_now": "Modello: {name}",
        "model_none": "Modello: —",
        "st_updating": "aggiornamento…",
        "st_fresh": "appena aggiornato",
        "st_login": "esegui claude /login",
        "st_rejected": "token rifiutato",
        "st_429": "limitato, attesa",
        "st_error": "errore {code}",
        "st_offline": "offline",
        "st_nocred": "non connesso",
        "m_refresh": "Aggiorna ora",
        "m_theme": "Tema",
        "m_alpha": "Opacità",
        "m_desktop": "Sul desktop (sotto le finestre)",
        "m_top": "Sempre in primo piano",
        "m_autostart": "Avvia con Windows",
        "m_lang": "Lingua",
        "m_close": "Chiudi",
        "m_bars": "Colori delle barre",
        "m_bars_level": "In base al livello di utilizzo",
        "m_bars_limit": "Colore proprio per limite",
        "m_numbers": "Colora le percentuali",
        "m_thresholds": "Soglie di colore",
        "m_models": "Modelli in basso",
        "m_models_current": "Solo attuale",
        "m_models_week": "Tutta la settimana (colori e quote)",
        "m_models_off": "Nascondi",
        "th_light": "Chiaro",
        "th_dark": "Scuro",
        "th_ocean": "Oceano",
        "th_violet": "Viola",
        "th_forest": "Foresta",
        "th_sand": "Sabbia",
        "tasks_title": "Attività di oggi",
        "add_today": "+ nuova attività",
        "add_later": "+ per dopo",
        "later": "Più tardi ({n})",
        "done": "Fatto ({n})",
        "no_tasks": "Nessuna attività",
        "t_to_later": "Sposta a dopo",
        "t_to_today": "Sposta a oggi",
        "t_done": "Segna come fatto",
        "t_restore": "Ripristina",
        "t_delete": "Elimina",
        "m_clear_done": "Cancella completate",
        "weekdays": ["lun", "mar", "mer", "gio", "ven", "sab", "dom"],
    },
    "pt": {
        "calendar": "Calendário", "cal_go_today": "Ir para o mês atual",
        "m_pace_tick": "Marca de ritmo uniforme (semana)",
        "m_widgets": "Widgets", "m_apply_all": "Este tema e idioma para todos", "m_model_row": "Modelo embaixo",
        "m_rows": "Linhas exibidas",
        "models_week": "Modelos esta semana",
        "now": "agora",
        "models_loading": "Modelos: contando…",
        "m_token": "Token próprio…",
        "token_prompt": "Token OAuth da assinatura Claude (claude setup-token).\nDeixe vazio para usar o claude login.",
        "st_apikey": "Chave de API sem cota",
        "quota_title": "Cota Claude",
        "today": "Hoje",
        "session": "5 horas",
        "week": "Semana",
        "model_limit": "Modelo",
        "day_note": "{used:.1f} de {budget:.1f}% sem. · reinicia {time}",
        "reset_at": "reinicia {time}",
        "reset_wd": "reinicia {wd} {time}",
        "model_now": "Modelo: {name}",
        "model_none": "Modelo: —",
        "st_updating": "atualizando…",
        "st_fresh": "atualizado agora",
        "st_login": "execute claude /login",
        "st_rejected": "token rejeitado",
        "st_429": "limitado, aguardando",
        "st_error": "erro {code}",
        "st_offline": "offline",
        "st_nocred": "não conectado",
        "m_refresh": "Atualizar agora",
        "m_theme": "Tema",
        "m_alpha": "Opacidade",
        "m_desktop": "Na área de trabalho (atrás das janelas)",
        "m_top": "Sempre no topo",
        "m_autostart": "Iniciar com o Windows",
        "m_lang": "Idioma",
        "m_close": "Fechar",
        "m_bars": "Cores das barras",
        "m_bars_level": "Por nível de uso",
        "m_bars_limit": "Cor própria por limite",
        "m_numbers": "Colorir as porcentagens",
        "m_thresholds": "Limites de cor",
        "m_models": "Modelos na parte inferior",
        "m_models_current": "Somente atual",
        "m_models_week": "Toda a semana (cores e partes)",
        "m_models_off": "Ocultar",
        "th_light": "Claro",
        "th_dark": "Escuro",
        "th_ocean": "Oceano",
        "th_violet": "Violeta",
        "th_forest": "Floresta",
        "th_sand": "Areia",
        "tasks_title": "Tarefas de hoje",
        "add_today": "+ nova tarefa",
        "add_later": "+ para depois",
        "later": "Depois ({n})",
        "done": "Concluído ({n})",
        "no_tasks": "Nenhuma tarefa",
        "t_to_later": "Mover para depois",
        "t_to_today": "Mover para hoje",
        "t_done": "Marcar concluído",
        "t_restore": "Restaurar",
        "t_delete": "Excluir",
        "m_clear_done": "Limpar concluídas",
        "weekdays": ["seg", "ter", "qua", "qui", "sex", "sáb", "dom"],
    },
    "nl": {
        "calendar": "Kalender", "cal_go_today": "Naar huidige maand",
        "m_pace_tick": "Markering gelijk tempo (week)",
        "m_widgets": "Widgets", "m_apply_all": "Dit thema en deze taal voor alle", "m_model_row": "Model onderaan",
        "m_rows": "Weergegeven rijen",
        "models_week": "Modellen deze week",
        "now": "nu",
        "models_loading": "Modellen: tellen…",
        "m_token": "Eigen token…",
        "token_prompt": "Claude-abonnement OAuth-token (claude setup-token).\nLaat leeg om claude login te gebruiken.",
        "st_apikey": "API-sleutel geen quota",
        "quota_title": "Claude-quota",
        "today": "Vandaag",
        "session": "5 uur",
        "week": "Week",
        "model_limit": "Model",
        "day_note": "{used:.1f} van {budget:.1f}% week · reset {time}",
        "reset_at": "reset {time}",
        "reset_wd": "reset {wd} {time}",
        "model_now": "Model: {name}",
        "model_none": "Model: —",
        "st_updating": "bijwerken…",
        "st_fresh": "zojuist bijgewerkt",
        "st_login": "voer claude /login uit",
        "st_rejected": "token geweigerd",
        "st_429": "gelimiteerd, wacht",
        "st_error": "fout {code}",
        "st_offline": "offline",
        "st_nocred": "niet ingelogd",
        "m_refresh": "Nu vernieuwen",
        "m_theme": "Thema",
        "m_alpha": "Dekking",
        "m_desktop": "Op bureaublad (achter vensters)",
        "m_top": "Altijd op voorgrond",
        "m_autostart": "Starten met Windows",
        "m_lang": "Taal",
        "m_close": "Sluiten",
        "m_bars": "Balkkleuren",
        "m_bars_level": "Op gebruiksniveau",
        "m_bars_limit": "Eigen kleur per limiet",
        "m_numbers": "Percentages kleuren",
        "m_thresholds": "Kleurdrempels",
        "m_models": "Modellen onderaan",
        "m_models_current": "Alleen huidige",
        "m_models_week": "Hele week (kleuren en aandelen)",
        "m_models_off": "Verbergen",
        "th_light": "Licht",
        "th_dark": "Donker",
        "th_ocean": "Oceaan",
        "th_violet": "Violet",
        "th_forest": "Bos",
        "th_sand": "Zand",
        "tasks_title": "Taken van vandaag",
        "add_today": "+ nieuwe taak",
        "add_later": "+ voor later",
        "later": "Later ({n})",
        "done": "Klaar ({n})",
        "no_tasks": "Geen taken",
        "t_to_later": "Verplaatsen naar later",
        "t_to_today": "Verplaatsen naar vandaag",
        "t_done": "Als klaar markeren",
        "t_restore": "Herstellen",
        "t_delete": "Verwijderen",
        "m_clear_done": "Klaar wissen",
        "weekdays": ["ma", "di", "wo", "do", "vr", "za", "zo"],
    },
    "cs": {
        "calendar": "Kalendář", "cal_go_today": "Na aktuální měsíc",
        "m_pace_tick": "Značka rovnoměrného tempa (týden)",
        "m_widgets": "Widgety", "m_apply_all": "Tento motiv a jazyk pro všechny", "m_model_row": "Model dole",
        "m_rows": "Zobrazené řádky",
        "models_week": "Modely tento týden",
        "now": "teď",
        "models_loading": "Modely: počítání…",
        "m_token": "Vlastní token…",
        "token_prompt": "OAuth token předplatného Claude (claude setup-token).\nPonechte prázdné pro použití claude login.",
        "st_apikey": "API klíč bez kvóty",
        "quota_title": "Kvóta Claude",
        "today": "Dnes",
        "session": "5 hodin",
        "week": "Týden",
        "model_limit": "Model",
        "day_note": "{used:.1f} z {budget:.1f}% týd. · reset {time}",
        "reset_at": "reset {time}",
        "reset_wd": "reset {wd} {time}",
        "model_now": "Model: {name}",
        "model_none": "Model: —",
        "st_updating": "aktualizace…",
        "st_fresh": "právě aktualizováno",
        "st_login": "spusťte claude /login",
        "st_rejected": "token odmítnut",
        "st_429": "omezeno, čekání",
        "st_error": "chyba {code}",
        "st_offline": "offline",
        "st_nocred": "nepřihlášen",
        "m_refresh": "Obnovit nyní",
        "m_theme": "Motiv",
        "m_alpha": "Průhlednost",
        "m_desktop": "Na ploše (pod okny)",
        "m_top": "Vždy navrchu",
        "m_autostart": "Spouštět s Windows",
        "m_lang": "Jazyk",
        "m_close": "Zavřít",
        "m_bars": "Barvy pruhů",
        "m_bars_level": "Podle úrovně využití",
        "m_bars_limit": "Vlastní barva pro každý limit",
        "m_numbers": "Obarvit procenta",
        "m_thresholds": "Barevné prahy",
        "m_models": "Modely dole",
        "m_models_current": "Jen aktuální",
        "m_models_week": "Celý týden (barvy a podíly)",
        "m_models_off": "Skrýt",
        "th_light": "Světlý",
        "th_dark": "Tmavý",
        "th_ocean": "Oceán",
        "th_violet": "Fialová",
        "th_forest": "Les",
        "th_sand": "Písek",
        "tasks_title": "Dnešní úkoly",
        "add_today": "+ nový úkol",
        "add_later": "+ na později",
        "later": "Později ({n})",
        "done": "Hotovo ({n})",
        "no_tasks": "Žádné úkoly",
        "t_to_later": "Přesunout na později",
        "t_to_today": "Přesunout na dnes",
        "t_done": "Označit hotové",
        "t_restore": "Obnovit",
        "t_delete": "Smazat",
        "m_clear_done": "Smazat hotové",
        "weekdays": ["po", "út", "st", "čt", "pá", "so", "ne"],
    },
    "tr": {
        "calendar": "Takvim", "cal_go_today": "Bu aya git",
        "m_pace_tick": "Hafta için eşit tempo işareti",
        "m_widgets": "Widget'lar", "m_apply_all": "Bu tema ve dili tümüne uygula", "m_model_row": "Alttaki model",
        "m_rows": "Gösterilen satırlar",
        "models_week": "Bu haftaki modeller",
        "now": "şimdi",
        "models_loading": "Modeller: sayılıyor…",
        "m_token": "Kendi token…",
        "token_prompt": "Claude abonelik OAuth token'ı (claude setup-token).\nBoş bırakılırsa claude login kullanılır.",
        "st_apikey": "API anahtarında kota yok",
        "quota_title": "Claude Kota",
        "today": "Bugün",
        "session": "5 saat",
        "week": "Hafta",
        "model_limit": "Model",
        "day_note": "{used:.1f} / {budget:.1f}% hafta · yenilenir {time}",
        "reset_at": "yenilenir {time}",
        "reset_wd": "yenilenir {wd} {time}",
        "model_now": "Model: {name}",
        "model_none": "Model: —",
        "st_updating": "güncelleniyor…",
        "st_fresh": "az önce güncellendi",
        "st_login": "claude /login yazın",
        "st_rejected": "token reddedildi",
        "st_429": "sınırlandı, bekleniyor",
        "st_error": "hata {code}",
        "st_offline": "çevrimdışı",
        "st_nocred": "oturum açık değil",
        "m_refresh": "Şimdi yenile",
        "m_theme": "Tema",
        "m_alpha": "Saydamlık",
        "m_desktop": "Masaüstünde (pencerelerin altında)",
        "m_top": "Her zaman üstte",
        "m_autostart": "Windows ile başlat",
        "m_lang": "Dil",
        "m_close": "Kapat",
        "m_bars": "Çubuk renkleri",
        "m_bars_level": "Kullanım düzeyine göre",
        "m_bars_limit": "Her limit için ayrı renk",
        "m_numbers": "Yüzdeleri renklendir",
        "m_thresholds": "Renk eşikleri",
        "m_models": "Altta modeller",
        "m_models_current": "Yalnızca güncel",
        "m_models_week": "Tüm hafta (renkler ve paylar)",
        "m_models_off": "Gizle",
        "th_light": "Açık",
        "th_dark": "Koyu",
        "th_ocean": "Okyanus",
        "th_violet": "Mor",
        "th_forest": "Orman",
        "th_sand": "Kum",
        "tasks_title": "Bugünün görevleri",
        "add_today": "+ yeni görev",
        "add_later": "+ sonraya",
        "later": "Sonra ({n})",
        "done": "Tamamlandı ({n})",
        "no_tasks": "Görev yok",
        "t_to_later": "Sonraya taşı",
        "t_to_today": "Bugüne taşı",
        "t_done": "Tamamlandı işaretle",
        "t_restore": "Geri yükle",
        "t_delete": "Sil",
        "m_clear_done": "Tamamlananları temizle",
        "weekdays": ["Pzt", "Sal", "Çar", "Per", "Cum", "Cmt", "Paz"],
    },
    "ja": {
        "calendar": "カレンダー", "cal_go_today": "今月に戻る",
        "m_pace_tick": "週の均等ペースの目印",
        "m_widgets": "ウィジェット", "m_apply_all": "このテーマと言語をすべてに適用", "m_model_row": "下部のモデル",
        "m_rows": "表示行数",
        "models_week": "今週のモデル",
        "now": "現在",
        "models_loading": "モデル: 集計中…",
        "m_token": "独自トークン…",
        "token_prompt": "Claudeサブスクリプションの OAuth トークン (claude setup-token)。\n空欄の場合は claude login を使用します。",
        "st_apikey": "APIキーにクォータなし",
        "quota_title": "Claudeクォータ",
        "today": "今日",
        "session": "5時間",
        "week": "週",
        "model_limit": "モデル",
        "day_note": "今週 {used:.1f}/{budget:.1f}% · {time}にリセット",
        "reset_at": "{time}にリセット",
        "reset_wd": "{wd} {time}にリセット",
        "model_now": "モデル: {name}",
        "model_none": "モデル: —",
        "st_updating": "更新中…",
        "st_fresh": "更新済み",
        "st_login": "claude /login を実行",
        "st_rejected": "トークン拒否",
        "st_429": "制限中、待機",
        "st_error": "エラー {code}",
        "st_offline": "オフライン",
        "st_nocred": "未ログイン",
        "m_refresh": "今すぐ更新",
        "m_theme": "テーマ",
        "m_alpha": "不透明度",
        "m_desktop": "デスクトップに表示(ウィンドウの下)",
        "m_top": "常に最前面に表示",
        "m_autostart": "Windows起動時に開始",
        "m_lang": "言語",
        "m_close": "閉じる",
        "m_bars": "バーの色",
        "m_bars_level": "使用量に応じて",
        "m_bars_limit": "上限ごとに色を分ける",
        "m_numbers": "パーセントに色を付ける",
        "m_thresholds": "色のしきい値",
        "m_models": "下部にモデルを表示",
        "m_models_current": "現在のみ",
        "m_models_week": "今週すべて(色と割合)",
        "m_models_off": "非表示",
        "th_light": "ライト",
        "th_dark": "ダーク",
        "th_ocean": "オーシャン",
        "th_violet": "バイオレット",
        "th_forest": "フォレスト",
        "th_sand": "サンド",
        "tasks_title": "今日のタスク",
        "add_today": "+ 新しいタスク",
        "add_later": "+ 後で",
        "later": "後で ({n})",
        "done": "完了 ({n})",
        "no_tasks": "タスクなし",
        "t_to_later": "後回しにする",
        "t_to_today": "今日に移動",
        "t_done": "完了にする",
        "t_restore": "復元",
        "t_delete": "削除",
        "m_clear_done": "完了済みを削除",
        "weekdays": ["月", "火", "水", "木", "金", "土", "日"],
    },
    "zh": {
        "calendar": "日历", "cal_go_today": "回到本月",
        "m_pace_tick": "本周均匀进度标记",
        "m_widgets": "小组件", "m_apply_all": "将此主题和语言应用于全部", "m_model_row": "底部模型",
        "m_rows": "显示行数",
        "models_week": "本周模型",
        "now": "现在",
        "models_loading": "模型：统计中…",
        "m_token": "自定义令牌…",
        "token_prompt": "Claude 订阅 OAuth 令牌 (claude setup-token)。\n留空则使用 claude login。",
        "st_apikey": "API密钥无配额",
        "quota_title": "Claude 配额",
        "today": "今天",
        "session": "5小时",
        "week": "本周",
        "model_limit": "模型",
        "day_note": "{used:.1f} / {budget:.1f}% 周 · {time} 重置",
        "reset_at": "{time} 重置",
        "reset_wd": "{wd} {time} 重置",
        "model_now": "模型：{name}",
        "model_none": "模型：—",
        "st_updating": "更新中…",
        "st_fresh": "刚刚更新",
        "st_login": "运行 claude /login",
        "st_rejected": "令牌被拒绝",
        "st_429": "已限速，等待中",
        "st_error": "错误 {code}",
        "st_offline": "离线",
        "st_nocred": "未登录",
        "m_refresh": "立即刷新",
        "m_theme": "主题",
        "m_alpha": "不透明度",
        "m_desktop": "显示在桌面（窗口下方）",
        "m_top": "始终置顶",
        "m_autostart": "随 Windows 启动",
        "m_lang": "语言",
        "m_close": "关闭",
        "m_bars": "进度条颜色",
        "m_bars_level": "按使用水平",
        "m_bars_limit": "每个限额单独配色",
        "m_numbers": "为百分比上色",
        "m_thresholds": "颜色阈值",
        "m_models": "底部显示模型",
        "m_models_current": "仅当前",
        "m_models_week": "本周全部（颜色和占比）",
        "m_models_off": "隐藏",
        "th_light": "浅色",
        "th_dark": "深色",
        "th_ocean": "海洋",
        "th_violet": "紫罗兰",
        "th_forest": "森林",
        "th_sand": "沙色",
        "tasks_title": "今日任务",
        "add_today": "+ 新任务",
        "add_later": "+ 稍后处理",
        "later": "稍后 ({n})",
        "done": "已完成 ({n})",
        "no_tasks": "暂无任务",
        "t_to_later": "移到稍后",
        "t_to_today": "移到今天",
        "t_done": "标记完成",
        "t_restore": "恢复",
        "t_delete": "删除",
        "m_clear_done": "清除已完成",
        "weekdays": ["周一", "周二", "周三", "周四", "周五", "周六", "周日"],
    },
}

_lang = "en"


def detect_lang():
    """Мова інтерфейсу Windows, якщо ми її підтримуємо, інакше англійська."""
    try:
        primary = ctypes.windll.kernel32.GetUserDefaultUILanguage() & 0x3FF
    except (AttributeError, OSError):
        return "en"
    return {0x22: "uk", 0x09: "en", 0x15: "pl", 0x07: "de", 0x0A: "es", 0x0C: "fr",
            0x10: "it", 0x16: "pt", 0x13: "nl", 0x05: "cs", 0x1F: "tr", 0x11: "ja",
            0x04: "zh"}.get(primary, "en")


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


# --- усі віджети: увімкнути/вимкнути один з іншого -------------------------

# Кожен віджет — окремий процес. Живий процес пише свій PID у <app>.pid поруч
# зі скриптом; за ним інші віджети бачать, чи він запущений, і можуть його
# запустити або закрити зі свого меню «Віджети».
WIDGETS = [
    {"app": "ClaudeQuotaWidget", "script": "quota_widget.py",
     "title": "quota_title", "settings": "settings.json"},
    {"app": "DailyTasksWidget", "script": "tasks_widget.py",
     "title": "tasks_title", "settings": "tasks_settings.json"},
    {"app": "DesktopCalendarWidget", "script": "calendar_widget.py",
     "title": "calendar", "settings": "calendar_settings.json"},
]
SHARED_KEYS = ("theme", "lang", "alpha")  # «ця тема й мова — для всіх»

_kernel32 = ctypes.windll.kernel32
_kernel32.OpenProcess.restype = wintypes.HANDLE
PROCESS_TERMINATE = 0x0001
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
STILL_ACTIVE = 259


def _pid_path(app):
    return os.path.join(HERE, app + ".pid")


def running_pid(app):
    """PID живого процесу віджета або None (файл старий, процес помер)."""
    try:
        with open(_pid_path(app), "r", encoding="ascii") as f:
            pid = int(f.read().strip())
    except (OSError, ValueError):
        return None
    handle = _kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return None
    try:
        code = wintypes.DWORD()
        if not _kernel32.GetExitCodeProcess(handle, ctypes.byref(code)) \
                or code.value != STILL_ACTIVE:
            return None
        # PID міг дістатись іншій програмі — перевіряємо, що це справді python
        name = ctypes.create_unicode_buffer(1024)
        size = wintypes.DWORD(1024)
        if _kernel32.QueryFullProcessImageNameW(handle, 0, name, ctypes.byref(size)) \
                and "python" not in name.value.lower():
            return None
        return pid
    finally:
        _kernel32.CloseHandle(handle)


def start_widget(script):
    pythonw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    if not os.path.exists(pythonw):
        pythonw = sys.executable
    subprocess.Popen([pythonw, os.path.join(HERE, script)], cwd=HERE, close_fds=True)


def stop_widget(app):
    pid = running_pid(app)
    if pid is None:
        return
    handle = _kernel32.OpenProcess(PROCESS_TERMINATE, False, pid)
    if handle:
        _kernel32.TerminateProcess(handle, 0)
        _kernel32.CloseHandle(handle)
    try:
        os.remove(_pid_path(app))
    except OSError:
        pass


def already_running(app):
    """Другий екземпляр того самого віджета не потрібен (start.bat двічі тощо)."""
    pid = running_pid(app)
    return pid is not None and pid != os.getpid()


def virtual_screen():
    """(x, y, ширина, висота) усіх моніторів разом — лівий може мати x < 0."""
    m = _user32.GetSystemMetrics
    return m(76), m(77), m(78), m(79)


def clamp_position(x, y):
    """Лишити на екрані хоча б шматок заголовка, щоб вікно можна було вхопити."""
    vx, vy, vw, vh = virtual_screen()
    x = max(vx - WIDTH + 80, min(x, vx + vw - 80))
    y = max(vy, min(y, vy + vh - 40))
    return x, y


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
    WIDTH = WIDTH        # календар ширший — перевизначає
    HEAD_PADX = PAD

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
        self._drag = None
        if any(w["app"] == self.APP_NAME for w in WIDGETS):
            try:
                with open(_pid_path(self.APP_NAME), "w", encoding="ascii") as f:
                    f.write(str(os.getpid()))
            except OSError:
                pass

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
        self.head.pack(fill="x", padx=self.HEAD_PADX, pady=(11, 9))

        self.head_title = tk.Label(
            self.head, text=tr(self.TITLE_KEY), bg=T["bg"], fg=T["fg"],
            font=("Segoe UI Semibold", 10),
        )
        self.head_title.pack(side="left")

        # шестірня праворуч: те саме меню, що на правій кнопці, але його видно.
        # Символ «⚙» у Segoe UI малюється схожим на квітку, тому беремо значок
        # «Параметри» зі шрифту значків Windows (Win11 — Fluent, Win10 — MDL2)
        text, font = "⚙", ("Segoe UI", 9)
        families = set(tkfont.families(self.root))
        for family in ("Segoe Fluent Icons", "Segoe MDL2 Assets"):
            if family in families:
                text, font = "\uE713", (family, 10)
                break
        self.gear = tk.Label(
            self.head, text=text, bg=T["bg"], fg=T["muted"],
            font=font, width=2, cursor="hand2",
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

        widgets = tk.Menu(self.menu, tearoff=0, postcommand=self._sync_widgets_menu)
        self.widget_vars = {}
        for w in WIDGETS:
            var = tk.BooleanVar(value=True)
            self.widget_vars[w["app"]] = var
            widgets.add_checkbutton(
                label=tr(w["title"]), variable=var,
                command=lambda w=w, v=var: self._toggle_widget(w, v),
            )
        widgets.add_separator()
        widgets.add_command(label=tr("m_apply_all"), command=self.apply_to_all)
        self.menu.add_cascade(label=tr("m_widgets"), menu=widgets)
        self.menu.add_separator()
        self.menu.add_command(label=tr("m_close"), command=self.close)

    def _sync_widgets_menu(self):
        """Галочки — за справжнім станом процесів у мить відкриття меню."""
        for w in WIDGETS:
            alive = w["app"] == self.APP_NAME or running_pid(w["app"]) is not None
            self.widget_vars[w["app"]].set(alive)

    def _toggle_widget(self, w, var):
        if w["app"] == self.APP_NAME:
            if not var.get():
                self.close()
            return
        if var.get():
            if running_pid(w["app"]) is None:
                start_widget(w["script"])
        else:
            stop_widget(w["app"])

    def apply_to_all(self):
        """Тему, мову й прозорість цього віджета — решті; запущені перезапустити."""
        for w in WIDGETS:
            if w["app"] == self.APP_NAME:
                continue
            path = os.path.join(HERE, w["settings"])
            data = load_json(path)
            for key in SHARED_KEYS:
                if key in self.settings:
                    data[key] = self.settings[key]
            save_json(path, data)
            if running_pid(w["app"]) is not None:
                stop_widget(w["app"])
                start_widget(w["script"])

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
        return self.root.winfo_screenwidth() - self.WIDTH - 24, 60

    def _restore_position(self):
        self.root.update_idletasks()
        height = self.root.winfo_reqheight()
        x = self.settings.get("x")
        y = self.settings.get("y")
        if x is None or y is None:
            x, y = self.default_position()
        # не дати вікну лишитись за межами екрана (враховуючи всі монітори)
        x, y = clamp_position(x, y)
        self.root.geometry("%dx%d+%d+%d" % (self.WIDTH, height, x, y))
        # застосувати одразу: інакше до першого показу вікна Tk встигає
        # перерахувати геометрію сам, і позиція губиться (вікно в куті 0,0)
        self.root.update_idletasks()

    def _drag_start(self, event):
        self._drag = (event.x_root, event.y_root,
                      self.root.winfo_x(), self.root.winfo_y())

    def _drag_move(self, event):
        # лише після натискання саме на віджеті: колись точка відліку лишалась
        # від давнього перетягування, і вікно відлітало за край екрана (y=-334)
        if not self._drag:
            return
        sx, sy, wx, wy = self._drag
        x, y = clamp_position(wx + event.x_root - sx, wy + event.y_root - sy)
        self.root.geometry("+%d+%d" % (x, y))

    def _drag_end(self, _event):
        if not self._drag:
            return  # відпускання без свого натискання (напр. після меню)
        self._drag = None
        self.settings["x"], self.settings["y"] = clamp_position(
            self.root.winfo_x(), self.root.winfo_y())
        self.save_settings()

    def fit_height(self):
        self.root.update_idletasks()
        self.root.geometry("%dx%d" % (self.WIDTH, self.root.winfo_reqheight() + 6))
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
        if running_pid(self.APP_NAME) == os.getpid():
            try:
                os.remove(_pid_path(self.APP_NAME))
            except OSError:
                pass
        self.root.destroy()

    def run(self):
        self.root.mainloop()
