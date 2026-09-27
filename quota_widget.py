# -*- coding: utf-8 -*-
"""Віджет квоти Claude Code для робочого столу Windows.

Показує 5-годинний ліміт, тижневий, ліміт по моделі — і окремо
УМОВНИЙ ДЕННИЙ ліміт: 100% тижня / 7 днів = 14.29% на добу.

Денний показник рахується як приріст тижневого відсотка від початку
поточної «квотної доби» (доба відлічується від часу тижневого ресету,
тобто ~04:59 за локальним часом).

Внизу — модель, якою Claude Code відповідав останнім (з журналу сесії).
"""

import json
import os
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

import tkinter as tk

from common import (HERE, PAD, WIDTH, T, DesktopWindow, set_dpi_awareness, tr)

# --- константи ---------------------------------------------------------------

STATE_PATH = os.path.join(HERE, "state.json")
# CLAUDE_CONFIG_DIR — та сама змінна, якою сам Claude Code переносить свою теку
CLAUDE_DIR = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(os.path.expanduser("~"), ".claude")
TOKEN_FILE = os.path.join(HERE, "token.txt")  # свій токен, вставлений через меню
CRED_PATH = os.path.join(CLAUDE_DIR, ".credentials.json")
PROJECTS_DIR = os.path.join(CLAUDE_DIR, "projects")

USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
TOKEN_URL = "https://platform.claude.com/v1/oauth/token"
OAUTH_CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"
USER_AGENT = "claude-cli/2.0.14 (external, cli)"

POLL_SECONDS = 300        # автооновлення раз на 5 хв
MIN_REQUEST_GAP = 180     # endpoint дає 429, якщо частіше
MODEL_POLL_MS = 20000     # модель — лише читання локального файлу, можна частіше
DAY_BUDGET = 100.0 / 7.0  # 14.29% тижня на добу

# пороги кольору рівня: (увага, критично)
THRESHOLDS = [(60, 85), (70, 90), (80, 95)]


# --- дані --------------------------------------------------------------------


class RefreshFailed(Exception):
    """Сервер відмовив у продовженні токена — потрібен ручний вхід."""


def read_credentials():
    with open(CRED_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def token_alive(doc):
    """Чи ще живий токен у файлі (з хвилиною запасу)."""
    expires = doc["claudeAiOauth"].get("expiresAt")
    return bool(expires) and expires / 1000.0 - 60 > time.time()


def refresh_credentials(force=False):
    """Продовжує токен через refresh_token і перезаписує .credentials.json.

    Треба тому, що застосунок Claude (desktop) тримає авторизацію в себе
    і файл на диску не переписує — той лишається з останнього запуску
    термінального claude і протухає за 8 годин.
    """
    doc = read_credentials()
    if not force and token_alive(doc):
        return doc["claudeAiOauth"]["accessToken"]  # хтось уже продовжив

    oauth = doc["claudeAiOauth"]
    if not oauth.get("refreshToken"):
        # CLI сам обнуляє токени у файлі, коли refresh-токен протух (~14 днів):
        # продовжувати нічим, а запит із порожнім токеном — просто 400
        raise RefreshFailed("refresh-токен порожній")
    body = json.dumps({
        "grant_type": "refresh_token",
        "refresh_token": oauth["refreshToken"],
        "client_id": OAUTH_CLIENT_ID,
    }).encode("utf-8")
    req = urllib.request.Request(
        TOKEN_URL,
        data=body,
        headers={
            "Content-Type": "application/json",
            "anthropic-beta": "oauth-2025-04-20",
            "User-Agent": USER_AGENT,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            tok = json.loads(resp.read().decode("utf-8"))
        access = tok["access_token"]
    except (urllib.error.HTTPError, ValueError, KeyError) as exc:
        # refresh_token мертвий або відкликаний — самі вже не полагодимо
        raise RefreshFailed(str(exc))

    now = time.time()
    oauth["accessToken"] = access
    if tok.get("refresh_token"):
        oauth["refreshToken"] = tok["refresh_token"]
    if tok.get("expires_in"):
        oauth["expiresAt"] = int((now + int(tok["expires_in"])) * 1000)
    if tok.get("refresh_token_expires_in"):
        oauth["refreshTokenExpiresAt"] = int(
            (now + int(tok["refresh_token_expires_in"])) * 1000)

    # атомарно: той самий файл читає і термінальний claude
    tmp = CRED_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(doc, f)
    os.replace(tmp, CRED_PATH)
    return oauth["accessToken"]


def ensure_token():
    """Живий OAuth-токен Claude Code: з файлу, а якщо протух — продовжений."""
    doc = read_credentials()
    if token_alive(doc):
        return doc["claudeAiOauth"]["accessToken"]
    return refresh_credentials()


class ApiKeyGiven(Exception):
    """Вставили API-ключ Console: у нього немає лімітів підписки, показувати нічого."""


def manual_token():
    """Свій токен замість .credentials.json, або None.

    Порядок: змінна CLAUDE_QUOTA_TOKEN, змінна CLAUDE_CODE_OAUTH_TOKEN (її ж
    читає Claude Code; туди кладуть токен із `claude setup-token`), token.txt.
    Такий токен віджет не продовжує — refresh-токена до нього немає.
    """
    for name in ("CLAUDE_QUOTA_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN"):
        value = (os.environ.get(name) or "").strip()
        if value:
            return value
    try:
        with open(TOKEN_FILE, "r", encoding="utf-8-sig") as f:
            return f.read().strip() or None
    except OSError:
        return None


def save_manual_token(value):
    value = (value or "").strip()
    if not value:
        try:
            os.remove(TOKEN_FILE)
        except OSError:
            pass
        return
    with open(TOKEN_FILE, "w", encoding="utf-8") as f:
        f.write(value)


def fetch_usage():
    token = manual_token()
    if token and token.startswith("sk-ant-api"):
        raise ApiKeyGiven()
    req = urllib.request.Request(
        USAGE_URL,
        headers={
            "Authorization": "Bearer " + (token or ensure_token()),
            "anthropic-beta": "oauth-2025-04-20",
            "User-Agent": USER_AGENT,
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def parse_dt(value):
    if not value:
        return None
    return datetime.fromisoformat(value)


def quantize(dt):
    """Округлює час до хвилини.

    Сервер віддає час ресету з мікросекундами, і вони РІЗНІ на кожному запиті
    (01:59:59.432665, потім 01:59:59.068654...). Якщо брати такий час як ключ
    доби, він ніколи не збігається зі збереженим — і база відліку скидається
    щоп'ять хвилин, а денний бар назавжди застигає на нулі.
    """
    return (dt + timedelta(seconds=30)).replace(second=0, microsecond=0)


def load_state():
    try:
        # utf-8-sig: файл інколи правлять руками, а Блокнот додає BOM
        with open(STATE_PATH, "r", encoding="utf-8-sig") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_state(state):
    """Пише атомарно: інакше читач може застати обрізаний файл.

    Обрізаний файл = ValueError = порожній стан = база відліку доби
    скидається поточним тижневим відсотком, і денна витрата губиться.
    """
    try:
        tmp = STATE_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
        os.replace(tmp, STATE_PATH)
    except OSError:
        pass


def extract(payload):
    """Витягує з відповіді те, що показує сам поп-ап."""
    out = {"session": None, "weekly": None, "scoped": [], "week_reset": None}

    for item in payload.get("limits") or []:
        kind = item.get("kind")
        entry = {
            "percent": float(item.get("percent") or 0),
            "resets_at": parse_dt(item.get("resets_at")),
            "title": None,
        }
        if kind == "session":
            entry["title"] = "5 годин"
            out["session"] = entry
        elif kind == "weekly_all":
            entry["title"] = "Тиждень"
            out["weekly"] = entry
            out["week_reset"] = entry["resets_at"]
        elif kind == "weekly_scoped":
            scope = item.get("scope") or {}
            model = (scope.get("model") or {}).get("display_name")
            entry["title"] = model  # None → підпис «Модель» мовою віджета
            out["scoped"].append(entry)

    # запасний шлях, якщо колись зникне масив limits
    if out["weekly"] is None and payload.get("seven_day"):
        sd = payload["seven_day"]
        out["weekly"] = {
            "title": "Тиждень",
            "percent": float(sd.get("utilization") or 0),
            "resets_at": parse_dt(sd.get("resets_at")),
        }
        out["week_reset"] = out["weekly"]["resets_at"]
    if out["session"] is None and payload.get("five_hour"):
        fh = payload["five_hour"]
        out["session"] = {
            "title": "5 годин",
            "percent": float(fh.get("utilization") or 0),
            "resets_at": parse_dt(fh.get("resets_at")),
        }

    return out


def compute_day(weekly_percent, week_reset):
    """Скільки з денної норми (14.29% тижня) вже витрачено сьогодні.

    Межі доби прив'язані до часу тижневого ресету, а не до опівночі.
    """
    if week_reset is None:
        return None

    now = datetime.now(timezone.utc)
    week_reset = quantize(week_reset)  # інакше ключі доби не збігаються — див. quantize()
    week_start = week_reset - timedelta(days=7)
    elapsed_days = (now - week_start).total_seconds() / 86400.0
    day_index = max(0, min(6, int(elapsed_days)))
    day_start = week_start + timedelta(days=day_index)

    state = load_state()
    week_key = week_reset.isoformat()
    day_key = day_start.isoformat()
    stored_week = parse_dt(state.get("week_reset"))
    sample_at = parse_dt(state.get("last_weekly_at"))

    if not state:
        # перший запуск: у нульовий день тижня все витрачене — це сьогоднішнє
        baseline = 0.0 if day_index == 0 else weekly_percent
    elif state.get("week_reset") != week_key and (stored_week is None or now >= stored_week):
        # тиждень справді скінчився — збережений ресет уже в минулому.
        # Якщо ж він ще в майбутньому, а ключ інший, то сервер просто віддав
        # інший час ресету: тиждень той самий, базу відліку рушити не можна
        baseline = 0.0 if day_index == 0 else weekly_percent
    elif state.get("day_start") != day_key:
        if sample_at is not None and sample_at > day_start:
            # остання проба СВІЖІША за межу доби, тобто збережений ключ доби
            # був хибний. Узяти таку пробу за базу = списати вже витрачене
            # сьогодні, і денна смуга обнулиться на середині дня
            baseline = float(state.get("baseline", 0.0))
        else:
            # нова доба: за базу беремо останнє значення перед межею
            baseline = float(state.get("last_weekly", weekly_percent))
    else:
        baseline = float(state.get("baseline", 0.0))

    if baseline > weekly_percent:
        # у межах тижня тижневий % лише росте — вища база означає, що вона
        # зіпсована (як 12.08 і 24.08), а не що витрата справді зменшилась.
        # Самолікування: рахуємо "сьогодні" з нуля від поточного значення,
        # аби смуга не застигала на нулі до кінця доби чи до ручної правки.
        baseline = weekly_percent

    save_state({
        "week_reset": week_key,
        "day_start": day_key,
        "baseline": baseline,
        "last_weekly": weekly_percent,
        "last_weekly_at": now.isoformat(),  # без часу проби запобіжник вище неможливий
    })

    used_today = max(0.0, weekly_percent - baseline)
    return {
        "used": used_today,
        "budget": DAY_BUDGET,
        "percent": used_today / DAY_BUDGET * 100.0,
        "day_index": day_index,
        "next_day": day_start + timedelta(days=1),
        "pace": elapsed_days / 7.0 * 100.0,  # скільки тижня «мало б» бути витрачено
    }


def current_model():
    """Модель, якою Claude Code відповідав останнім, або None.

    Кожна сесія Claude Code (термінал і застосунок) пише журнал
    ~/.claude/projects/<проєкт>/<сесія>.jsonl, і в кожній відповіді там є
    поле message.model. Беремо найсвіжіший журнал верхнього рівня: журнали
    субагентів лежать глибше (<сесія>/subagents/) і показували б модель
    помічника, а не ту, з якою працюєш.
    """
    best, best_mtime = None, 0.0
    try:
        for project in os.scandir(PROJECTS_DIR):
            if not project.is_dir():
                continue
            for entry in os.scandir(project.path):
                if entry.name.endswith(".jsonl") and entry.is_file():
                    mtime = entry.stat().st_mtime
                    if mtime > best_mtime:
                        best, best_mtime = entry.path, mtime
        if best is None:
            return None
        with open(best, "rb") as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - 262144))
            tail = f.read().decode("utf-8", "ignore").splitlines()
    except OSError:
        return None

    for line in reversed(tail):
        if '"assistant"' not in line:
            continue
        try:
            model = (json.loads(line).get("message") or {}).get("model") or ""
        except ValueError:
            continue  # перший рядок хвоста зазвичай обрізаний
        if model.startswith("claude-"):
            return model
    return None


def model_label(model_id):
    """claude-opus-5-5 → Opus 5.5, claude-haiku-4-5-20251001 → Haiku 4.5."""
    parts = model_id.split("[")[0].split("-")[1:]
    parts = [p for p in parts if not (p.isdigit() and len(p) == 8)]  # дата збірки
    words = [p.capitalize() for p in parts if not p.isdigit()]
    version = ".".join(p for p in parts if p.isdigit())
    return " ".join(words + ([version] if version else []))


def level_color(percent, settings):
    warn, crit = settings.get("thresholds", [70, 90])
    if percent >= crit:
        return T["red"]
    if percent >= warn:
        return T["amber"]
    return T["green"]


def fmt_reset(dt, with_weekday=False):
    if dt is None:
        return ""
    # quantize і тут: без нього той самий ресет показується то 04:59, то 05:00,
    # бо сервер щоразу віддає інші мікросекунди
    local = quantize(dt).astimezone()
    hhmm = "%02d:%02d" % (local.hour, local.minute)
    if with_weekday:
        return tr("reset_wd", wd=tr("weekdays")[local.weekday()], time=hhmm)
    return tr("reset_at", time=hhmm)


# --- інтерфейс ---------------------------------------------------------------


class Row:
    """Один рядок: назва, відсоток, смуга, підпис під нею.

    color_key — власний колір ліміту в палітрі (day/session/week/model)
    для режиму «свій колір на кожен ліміт».
    """

    def __init__(self, parent, title, settings, color_key, big=False):
        self.big = big
        self.settings = settings
        self.color_key = color_key
        self.frame = tk.Frame(parent, bg=T["bg"])
        self.frame.pack(fill="x", padx=PAD, pady=(0, 10))

        self.head = tk.Frame(self.frame, bg=T["bg"])
        self.head.pack(fill="x")

        self.title = tk.Label(
            self.head, text=title, bg=T["bg"], fg=T["fg"] if big else T["muted"],
            font=("Segoe UI Semibold" if big else "Segoe UI", 10 if big else 9),
            anchor="w",
        )
        self.title.pack(side="left")

        self.value = tk.Label(
            self.head, text="—", bg=T["bg"], fg=T["fg"],
            font=("Segoe UI Semibold", 13 if big else 11),
            anchor="e",
        )
        self.value.pack(side="right")

        height = 9 if big else 6
        self.canvas = tk.Canvas(
            self.frame, height=height, bg=T["bg"], highlightthickness=0, bd=0,
        )
        self.canvas.pack(fill="x", pady=(4, 0))
        self.bar_height = height
        self._last = None
        self.canvas.bind("<Configure>", self._redraw)

        self.note = tk.Label(
            self.frame, text="", bg=T["bg"], fg=T["muted"],
            font=("Segoe UI", 8), anchor="w",
        )
        self.note.pack(fill="x", pady=(2, 0))

    def retheme(self):
        """Перефарбувати під нову палітру. Структура й шрифти не міняються."""
        self.frame.config(bg=T["bg"])
        self.head.config(bg=T["bg"])
        self.title.config(bg=T["bg"], fg=T["fg"] if self.big else T["muted"])
        self.value.config(bg=T["bg"])
        self.canvas.config(bg=T["bg"])
        self.note.config(bg=T["bg"], fg=T["muted"])
        self._redraw()

    def _redraw(self, _event=None):
        if self._last:
            self.draw(*self._last)
        else:
            self.value.config(fg=T["fg"])

    def bar_color(self, percent):
        level = level_color(percent, self.settings)
        if self.settings.get("bars") == "limit" and level == T["green"]:
            # свій колір ліміту — поки витрата в нормі; далі попередження
            # важливіше за впізнаваність рядка
            return T[self.color_key]
        return level

    def draw(self, percent, tick=None):
        # колір смуги й цифри рахується тут, а не приходить готовим — інакше
        # після зміни теми чи порогів перемальовування лишало б старий колір
        self._last = (percent, tick)
        self.value.config(
            fg=level_color(percent, self.settings)
            if self.settings.get("numbers", True) else T["fg"])
        c = self.canvas
        c.delete("all")
        width = c.winfo_width()
        if width <= 1:  # полотно ще не отримало розмір — беремо розрахункову ширину
            width = WIDTH - 2 * PAD
        h = self.bar_height
        c.create_rectangle(0, 0, width, h, fill=T["track"], outline="")
        filled = max(0.0, min(100.0, percent)) / 100.0 * width
        if filled > 0:
            c.create_rectangle(0, 0, filled, h, fill=self.bar_color(percent), outline="")
        if tick is not None:
            x = max(0.0, min(100.0, tick)) / 100.0 * width
            c.create_line(x, -1, x, h + 1, fill=T["tick"], width=1)


class QuotaWidget(DesktopWindow):
    APP_NAME = "ClaudeQuotaWidget"
    SCRIPT = "quota_widget.py"
    SETTINGS_FILE = "settings.json"
    TITLE_KEY = "quota_title"

    def __init__(self):
        self.last_request = 0.0
        self.data = None
        self.error = None      # (ключ перекладу, аргументи) або None
        self.updated_at = None
        self._timer = None
        self._model_timer = None
        self.model_id = None
        super().__init__()
        self.status.config(text="…")
        self.root.after(200, self.refresh)
        self.root.after(300, self.refresh_model)

    # -- побудова -------------------------------------------------------------

    def _build_body(self):
        s = self.settings
        self.day_row = Row(self.root, tr("today"), s, "day", big=True)
        self.separator = tk.Frame(self.root, bg=T["track"], height=1)
        self.separator.pack(fill="x", padx=PAD, pady=(2, 10))

        self.session_row = Row(self.root, tr("session"), s, "session")
        self.week_row = Row(self.root, tr("week"), s, "week")
        # окремий контейнер: рядки моделей з'являються вже після побудови,
        # і без нього стали б нижче за підпис моделі
        self.scoped_box = tk.Frame(self.root, bg=T["bg"])
        self.scoped_box.pack(fill="x")
        self.scoped_rows = []

        self.model_label = tk.Label(
            self.root, text="", bg=T["bg"], fg=T["muted"],
            font=("Segoe UI", 8), anchor="w",
        )
        self._place_model_label()

    def _place_model_label(self):
        if self.settings.get("show_model", True):
            self.model_label.pack(fill="x", padx=PAD, pady=(0, 8))
        else:
            self.model_label.pack_forget()

    def _rows(self):
        return [self.day_row, self.session_row, self.week_row] + self.scoped_rows

    def _menu_items(self, menu):
        menu.add_command(label=tr("m_refresh"), command=self.refresh)
        menu.add_command(label=tr("m_token"), command=self.ask_token)
        menu.add_separator()

        bars = tk.Menu(menu, tearoff=0)
        self.bars_var = tk.StringVar(value=self.settings.get("bars", "level"))
        for value, key in (("level", "m_bars_level"), ("limit", "m_bars_limit")):
            bars.add_radiobutton(
                label=tr(key), variable=self.bars_var, value=value,
                command=lambda v=value: self._set_style("bars", v),
            )
        menu.add_cascade(label=tr("m_bars"), menu=bars)

        thresholds = tk.Menu(menu, tearoff=0)
        self.thr_var = tk.StringVar(
            value="%d/%d" % tuple(self.settings.get("thresholds", [70, 90])))
        for warn, crit in THRESHOLDS:
            label = "%d%% / %d%%" % (warn, crit)
            thresholds.add_radiobutton(
                label=label, variable=self.thr_var, value="%d/%d" % (warn, crit),
                command=lambda w=warn, c=crit: self._set_style("thresholds", [w, c]),
            )
        menu.add_cascade(label=tr("m_thresholds"), menu=thresholds)

        self.numbers_var = tk.BooleanVar(value=self.settings.get("numbers", True))
        menu.add_checkbutton(
            label=tr("m_numbers"), variable=self.numbers_var,
            command=lambda: self._set_style("numbers", self.numbers_var.get()),
        )
        self.show_model_var = tk.BooleanVar(value=self.settings.get("show_model", True))
        menu.add_checkbutton(
            label=tr("m_show_model"), variable=self.show_model_var,
            command=self._toggle_model,
        )
        menu.add_separator()

    def ask_token(self):
        """Вставити свій OAuth-токен підписки (порожнє поле — повернутись до claude)."""
        from tkinter import simpledialog
        self.allow_keyboard(True)
        try:
            value = simpledialog.askstring(
                tr("m_token"), tr("token_prompt"), parent=self.root, show="•")
        finally:
            self.allow_keyboard(False)
        if value is None:
            return  # Скасувати — нічого не міняємо
        save_manual_token(value)
        self.last_request = 0.0  # новий токен — перевірити одразу, а не за 5 хв
        self.refresh()

    def _set_style(self, key, value):
        self.settings[key] = value
        self.save_settings()
        for row in self._rows():
            row._redraw()

    def _toggle_model(self):
        self.settings["show_model"] = self.show_model_var.get()
        self.save_settings()
        self._place_model_label()
        self.fit_height()

    def retheme(self):
        self.separator.config(bg=T["track"])
        self.scoped_box.config(bg=T["bg"])
        self.model_label.config(bg=T["bg"], fg=T["muted"])
        self._show_status()
        for row in self._rows():
            row.retheme()

    def relabel(self):
        self.day_row.title.config(text=tr("today"))
        self.session_row.title.config(text=tr("session"))
        self.week_row.title.config(text=tr("week"))
        self._show_status()
        self._show_model()
        self.render()

    # -- модель ---------------------------------------------------------------

    def refresh_model(self):
        if self.stop:
            return
        model = current_model()
        if model != self.model_id or not self.model_label.cget("text"):
            self.model_id = model
            self._show_model()
        self._model_timer = self.root.after(MODEL_POLL_MS, self.refresh_model)

    def _show_model(self):
        if self.model_id:
            self.model_label.config(text=tr("model_now", name=model_label(self.model_id)))
        else:
            self.model_label.config(text=tr("model_none"))

    # -- дані -----------------------------------------------------------------

    def _schedule_next(self):
        """Один-єдиний таймер: ручне оновлення не має плодити нові ланцюжки."""
        if self.stop:
            return
        if self._timer is not None:
            self.root.after_cancel(self._timer)
        self._timer = self.root.after(POLL_SECONDS * 1000, self.refresh)

    def refresh(self):
        gap = time.time() - self.last_request
        if gap < MIN_REQUEST_GAP and self.data is not None:
            self.status.config(text=tr("st_fresh"))
            self._schedule_next()
            return

        self.last_request = time.time()
        self.status.config(text=tr("st_updating"))
        threading.Thread(target=self._worker, daemon=True).start()

    def _worker(self):
        try:
            try:
                payload = fetch_usage()
            except urllib.error.HTTPError as exc:
                if exc.code != 401 or manual_token():
                    raise  # свій токен продовжувати нічим
                # сервер відкинув токен раніше, ніж той протух за годинником
                refresh_credentials(force=True)
                payload = fetch_usage()
            self.root.after(0, self._apply, payload, None)
        except ApiKeyGiven:
            self.root.after(0, self._apply, None, ("st_apikey", {}))
        except RefreshFailed:
            self.root.after(0, self._apply, None, ("st_login", {}))
        except FileNotFoundError:
            # claude на цьому ПК жодного разу не входив — файлу токена немає
            self.root.after(0, self._apply, None, ("st_nocred", {}))
        except urllib.error.HTTPError as exc:
            if exc.code == 401:
                error = ("st_rejected", {})
            elif exc.code == 429:
                error = ("st_429", {})
            else:
                error = ("st_error", {"code": exc.code})
            self.root.after(0, self._apply, None, error)
        except (urllib.error.URLError, OSError, ValueError, KeyError):
            self.root.after(0, self._apply, None, ("st_offline", {}))

    def _apply(self, payload, error):
        if payload is not None:
            self.data = extract(payload)
            self.error = None
            self.updated_at = datetime.now()
        else:
            self.error = error
        self._show_status()
        self.render()
        self._schedule_next()

    def _show_status(self):
        if self.error:
            key, args = self.error
            self.status.config(text=tr(key, **args), fg=T["amber"])
        elif self.updated_at:
            self.status.config(
                text="%02d:%02d" % (self.updated_at.hour, self.updated_at.minute),
                fg=T["muted"])

    def render(self):
        data = self.data
        if not data:
            return

        weekly = data.get("weekly")
        weekly_percent = weekly["percent"] if weekly else 0.0
        day = compute_day(weekly_percent, data.get("week_reset"))

        # --- денний ліміт ---
        if day:
            self.day_row.value.config(text="%d%%" % round(day["percent"]))
            self.day_row.draw(day["percent"])
            local_next = day["next_day"].astimezone()
            # «ресет», як у решті рядків: «оновиться» читалось як «віджет
            # оновиться аж о 05:00», хоча йдеться про початок нової доби квоти
            self.day_row.note.config(text=tr(
                "day_note", used=day["used"], budget=day["budget"],
                time="%02d:%02d" % (local_next.hour, local_next.minute)))
        else:
            self.day_row.value.config(text="—")

        # --- 5 годин ---
        session = data.get("session")
        if session:
            self.session_row.value.config(text="%d%%" % round(session["percent"]))
            self.session_row.draw(session["percent"])
            self.session_row.note.config(text=fmt_reset(session["resets_at"]))

        # --- тиждень (з міткою «де мав би бути» темпом) ---
        if weekly:
            self.week_row.value.config(text="%d%%" % round(weekly_percent))
            self.week_row.draw(weekly_percent, tick=day["pace"] if day else None)
            self.week_row.note.config(text=fmt_reset(weekly["resets_at"], with_weekday=True))

        # --- ліміти по моделях ---
        scoped = data.get("scoped") or []
        while len(self.scoped_rows) < len(scoped):
            row = Row(self.scoped_box, "", self.settings, "model")
            self.scoped_rows.append(row)
            self.bind_drag(row.frame)

        for row, entry in zip(self.scoped_rows, scoped):
            row.frame.pack(fill="x", padx=PAD, pady=(0, 10))
            row.title.config(text=entry["title"] or tr("model_limit"))
            row.value.config(text="%d%%" % round(entry["percent"]))
            row.draw(entry["percent"])
            row.note.config(text=fmt_reset(entry["resets_at"], with_weekday=True))

        for row in self.scoped_rows[len(scoped):]:
            row.frame.pack_forget()

        self.fit_height()


def main():
    set_dpi_awareness()
    QuotaWidget().run()


if __name__ == "__main__":
    main()
