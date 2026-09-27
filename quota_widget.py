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

from common import (HERE, PAD, WIDTH, T, DesktopWindow, already_running, load_json,
                    save_json, set_dpi_awareness, tr)

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


# --- моделі: хто скільки з'їв за тиждень --------------------------------------

USAGE_CACHE = os.path.join(HERE, "model_usage.json")
USAGE_POLL_MS = 60000
USAGE_DAYS = 8            # тримаємо трохи більше тижня квоти
FAMILIES = ("opus", "sonnet", "haiku", "fable")
# Вага токенів за типом, приблизно як у ціні: вихід ~5× дорожчий за вхід,
# запис у кеш ~1.25×, читання кешу ~0.1×. Без ваг частку «з'їдало» б читання
# кешу — його в довгих сесіях у сотні разів більше за решту.
TOKEN_WEIGHTS = {"input_tokens": 1.0, "output_tokens": 5.0,
                 "cache_creation_input_tokens": 1.25, "cache_read_input_tokens": 0.1}


def model_family(model_id):
    for part in model_id.split("[")[0].split("-")[1:]:
        if not part.isdigit():
            return part if part in FAMILIES else "other"
    return "other"


def blend(color, other, amount):
    """Змішує #rrggbb з іншим кольором: amount=0 — сам color, 1 — other."""
    a = [int(color[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(other[i:i + 2], 16) for i in (1, 3, 5)]
    return "#%02x%02x%02x" % tuple(round(x + (y - x) * amount) for x, y in zip(a, b))


def parse_ts(value):
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except (AttributeError, ValueError):
        return None


class ModelUsage:
    """Частки моделей за тиждень з журналів ~/.claude/projects (разом із субагентами).

    Журналів за тиждень — гігабайти, тож читаємо лише нове: для кожного файлу
    пам'ятаємо, на якому байті зупинились, а суми тримаємо погодинно.
    Усе це лежить у model_usage.json, щоб перезапуск не перечитував усе.
    """

    def __init__(self):
        cache = load_json(USAGE_CACHE)
        self.files = cache.get("files") or {}      # шлях -> {"offset": байт}
        self.buckets = cache.get("buckets") or {}  # модель -> {година: вага}

    def scan(self):
        cutoff = time.time() - USAGE_DAYS * 86400
        alive = set()
        for dirpath, _dirs, names in os.walk(PROJECTS_DIR):
            for name in names:
                if not name.endswith(".jsonl"):
                    continue
                path = os.path.join(dirpath, name)
                try:
                    st = os.stat(path)
                except OSError:
                    continue
                if st.st_mtime < cutoff:
                    continue
                alive.add(path)
                info = self.files.get(path) or {"offset": 0}
                if st.st_size < info["offset"]:
                    info = {"offset": 0}  # файл переписали з нуля
                if st.st_size > info["offset"]:
                    try:
                        info["offset"] = self._read(path, info["offset"])
                    except OSError:
                        pass
                self.files[path] = info

        self.files = {p: i for p, i in self.files.items() if p in alive}
        min_hour = int(cutoff // 3600)
        for model in list(self.buckets):
            hours = {h: w for h, w in self.buckets[model].items() if int(h) >= min_hour}
            if hours:
                self.buckets[model] = hours
            else:
                del self.buckets[model]
        save_json(USAGE_CACHE, {"files": self.files, "buckets": self.buckets})

    def _read(self, path, offset):
        seen = set()
        with open(path, "rb") as f:
            f.seek(offset)
            while True:
                line = f.readline()
                if not line.endswith(b"\n"):
                    break  # недописаний рядок — дочитаємо наступного разу
                offset += len(line)
                # дешевий відсів до json.loads: більшість байтів — результати
                # інструментів у рядках "user", і розбирати їх нема чого
                if b'"usage"' not in line or b'"assistant"' not in line:
                    continue
                try:
                    obj = json.loads(line)
                except ValueError:
                    continue
                msg = obj.get("message") or {}
                model = msg.get("model") or ""
                usage = msg.get("usage")
                ts = parse_ts(obj.get("timestamp"))
                if not model.startswith("claude-") or not isinstance(usage, dict) or ts is None:
                    continue
                # одна відповідь пишеться кількома рядками (по блоку контенту),
                # і в кожному той самий usage — рахувати треба один раз
                key = msg.get("id") or obj.get("requestId")
                if key in seen:
                    continue
                seen.add(key)
                weight = sum(float(usage.get(k) or 0) * w for k, w in TOKEN_WEIGHTS.items())
                hour = str(int(ts // 3600))
                bucket = self.buckets.setdefault(model, {})
                bucket[hour] = bucket.get(hour, 0.0) + weight
        return offset

    def shares(self, since_ts):
        """[(назва, сім'я, відсоток)] від більшої частки до меншої."""
        first_hour = int(since_ts // 3600)
        totals = {}
        for model, hours in self.buckets.items():
            weight = sum(w for h, w in hours.items() if int(h) >= first_hour)
            if weight > 0:
                label = model_label(model)
                prev = totals.get(label, (0.0, model))[0]
                totals[label] = (prev + weight, model)
        grand = sum(w for w, _m in totals.values())
        items = [(label, model_family(model), w / grand * 100.0)
                 for label, (w, model) in totals.items()]
        return sorted(items, key=lambda item: -item[2])


class ModelsBlock:
    """Внизу квоти: кожна модель — свій колір, смуга на її частку за тиждень."""

    def __init__(self, parent):
        self.frame = tk.Frame(parent, bg=T["bg"])
        self.title = tk.Label(self.frame, text=tr("models_loading"), bg=T["bg"],
                              fg=T["muted"], font=("Segoe UI", 8), anchor="w")
        self.title.pack(fill="x", pady=(0, 3))
        self.box = tk.Frame(self.frame, bg=T["bg"])
        self.box.pack(fill="x")
        self.items = None    # None — ще не пораховано
        self.current = None  # id моделі останньої відповіді

    def show(self, mode="current"):
        for child in self.box.winfo_children():
            child.destroy()
        current = model_label(self.current) if self.current else None
        if mode != "week":
            # простий вигляд — один рядок, як було від початку
            self.title.config(text=tr("model_now", name=current) if current
                              else tr("model_none"))
            return
        items = list(self.items or [])
        if current and current not in [label for label, _f, _s in items]:
            items.append((current, model_family(self.current), 0.0))

        if self.items is None:
            self.title.config(text=tr("models_loading"))
        elif not items:
            self.title.config(text=tr("model_none"))
        else:
            self.title.config(text=tr("models_week"))

        used = {}
        for label, family, share in items:
            # дві версії однієї сім'ї (Opus 5.5 і Opus 5) не мають злитись:
            # кожна наступна — блідіший відтінок кольору сім'ї
            nth = used.get(family, 0)
            used[family] = nth + 1
            color = blend(T.get(family, T["other"]), T["bg"], min(0.6, 0.3 * nth))
            row = tk.Frame(self.box, bg=T["bg"])
            row.pack(fill="x", pady=(0, 5))
            head = tk.Frame(row, bg=T["bg"])
            head.pack(fill="x")
            tk.Label(head, text="●", bg=T["bg"], fg=color,
                     font=("Segoe UI", 8)).pack(side="left")
            tk.Label(head, text=label, bg=T["bg"], fg=T["fg"],
                     font=("Segoe UI Semibold" if label == current else "Segoe UI", 9)
                     ).pack(side="left")
            if label == current:
                tk.Label(head, text="· " + tr("now"), bg=T["bg"], fg=T["muted"],
                         font=("Segoe UI", 8)).pack(side="left", padx=(3, 0))
            if self.items is not None:
                tk.Label(head, text="%d%%" % round(share), bg=T["bg"], fg=color,
                         font=("Segoe UI Semibold", 9)).pack(side="right")
            bar = tk.Canvas(row, height=4, bg=T["bg"], highlightthickness=0, bd=0)
            bar.pack(fill="x", pady=(2, 0))
            width = WIDTH - 2 * PAD
            bar.create_rectangle(0, 0, width, 4, fill=T["track"], outline="")
            if share > 0:
                bar.create_rectangle(0, 0, max(2, share / 100.0 * width), 4,
                                     fill=color, outline="")

    def retheme(self, mode):
        for widget in (self.frame, self.box):
            widget.config(bg=T["bg"])
        self.title.config(bg=T["bg"], fg=T["muted"])
        self.show(mode)


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
        self.usage = ModelUsage()
        self.scoped_titles = []  # моделі з окремим лімітом — для меню «Показники»
        self._scanning = False
        super().__init__()
        self.status.config(text="…")
        self.root.after(200, self.refresh)
        self.root.after(300, self.refresh_model)
        self.root.after(400, self.refresh_usage)

    # -- побудова -------------------------------------------------------------

    def _build_body(self):
        s = self.settings
        self.day_row = Row(self.root, tr("today"), s, "day", big=True)
        self.separator = tk.Frame(self.root, bg=T["track"], height=1)
        self.separator.pack(fill="x", padx=PAD, pady=(2, 10))

        self.session_row = Row(self.root, tr("session"), s, "session")
        self.week_row = Row(self.root, tr("week"), s, "week")
        # окремий контейнер: рядки моделей з'являються вже після побудови,
        # і без нього стали б нижче за блок моделей
        self.scoped_box = tk.Frame(self.root, bg=T["bg"])
        self.scoped_box.pack(fill="x")
        self.scoped_rows = []

        self.models = ModelsBlock(self.root)
        self._place_models()

    def models_mode(self):
        """current — один рядок «Модель: …» (за замовчуванням), week — усі
        моделі тижня з кольорами й частками, off — нічого."""
        mode = self.settings.get("models")
        if mode in ("current", "week", "off"):
            return mode
        return "off" if self.settings.get("show_model") is False else "current"

    def _place_models(self):
        if self.models_mode() != "off":
            self.models.frame.pack(fill="x", padx=PAD, pady=(0, 6))
        else:
            self.models.frame.pack_forget()

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
        models = tk.Menu(menu, tearoff=0)
        self.models_var = tk.StringVar(value=self.models_mode())
        for value, key in (("current", "m_models_current"), ("week", "m_models_week"),
                           ("off", "m_models_off")):
            models.add_radiobutton(
                label=tr(key), variable=self.models_var, value=value,
                command=lambda v=value: self.set_models_mode(v),
            )
        menu.add_cascade(label=tr("m_models"), menu=models)

        rows = tk.Menu(menu, tearoff=0)
        self.row_vars = {}
        labels = [("today", tr("today")), ("session", tr("session")), ("week", tr("week"))]
        labels += [("m:" + t, t) for t in self.scoped_titles]
        for key, label in labels:
            var = tk.BooleanVar(value=self.row_visible(key))
            self.row_vars[key] = var
            rows.add_checkbutton(label=label, variable=var,
                                 command=lambda k=key, v=var: self.toggle_row(k, v))
        rows.add_separator()
        self.pace_var = tk.BooleanVar(value=self.settings.get("pace_tick", False))
        rows.add_checkbutton(label=tr("m_pace_tick"), variable=self.pace_var,
                             command=self._toggle_pace)
        self.model_row_var = tk.BooleanVar(value=self.models_mode() != "off")
        rows.add_checkbutton(label=tr("m_model_row"), variable=self.model_row_var,
                             command=self._toggle_model_row)
        menu.add_cascade(label=tr("m_rows"), menu=rows)
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

    def _toggle_pace(self):
        self.settings["pace_tick"] = self.pace_var.get()
        self.save_settings()
        self.render()

    def _toggle_model_row(self):
        """Прибрати/повернути напис моделі; повертається той режим, що був."""
        if self.model_row_var.get():
            mode = self.settings.get("models_last", "current")
        else:
            if self.models_mode() != "off":
                self.settings["models_last"] = self.models_mode()
            mode = "off"
        self.models_var.set(mode)
        self.set_models_mode(mode)

    def set_models_mode(self, mode):
        if hasattr(self, "model_row_var"):
            self.model_row_var.set(mode != "off")
        self.settings["models"] = mode
        self.settings.pop("show_model", None)
        self.save_settings()
        self._place_models()
        self._show_models()
        if mode == "week":
            self.refresh_usage(reschedule=False)  # порахувати одразу, а не за хвилину

    def retheme(self):
        self.separator.config(bg=T["track"])
        self.scoped_box.config(bg=T["bg"])
        self._show_status()
        for row in self._rows():
            row.retheme()
        self.models.retheme(self.models_mode())
        self.bind_drag(self.models.box)

    def relabel(self):
        self.day_row.title.config(text=tr("today"))
        self.session_row.title.config(text=tr("session"))
        self.week_row.title.config(text=tr("week"))
        self._show_status()
        self._show_models()
        self.render()

    # -- модель ---------------------------------------------------------------

    def refresh_model(self):
        """Поточна модель — часто: це лише хвіст одного файлу."""
        if self.stop:
            return
        model = current_model()
        if model != self.models.current:
            self.models.current = model
            self._show_models()
        self._model_timer = self.root.after(MODEL_POLL_MS, self.refresh_model)

    def refresh_usage(self, reschedule=True):
        """Частки моделей — у фоні: перший прохід читає журнали за тиждень.

        Лише в режимі week: у решті режимів журнали за тиждень не читаються.
        """
        if self.stop:
            return
        if reschedule:
            self.root.after(USAGE_POLL_MS, self.refresh_usage)
        if self.models_mode() == "week" and not self._scanning:
            self._scanning = True
            week_reset = (self.data or {}).get("week_reset")
            if week_reset:
                since = (quantize(week_reset) - timedelta(days=7)).timestamp()
            else:
                since = time.time() - 7 * 86400
            threading.Thread(target=self._usage_worker, args=(since,), daemon=True).start()

    def _usage_worker(self, since):
        try:
            self.usage.scan()
            items = self.usage.shares(since)
        except Exception:
            items = None  # журнали недоступні — лишаємо, що було
        self.root.after(0, self._apply_usage, items)

    def _apply_usage(self, items):
        self._scanning = False
        if items is not None:
            self.models.items = items
            self._show_models()

    def _show_models(self):
        self.models.show(self.models_mode())
        self.bind_drag(self.models.box)
        self.fit_height()

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

    # -- які показники видно --------------------------------------------------

    def row_visible(self, key):
        return key not in self.settings.get("hidden", [])

    def _row_keys(self):
        return ["today", "session", "week"] + ["m:" + t for t in self.scoped_titles]

    def toggle_row(self, key, var):
        hidden = set(self.settings.get("hidden", []))
        if var.get():
            hidden.discard(key)
        else:
            hidden.add(key)
            if all(k in hidden for k in self._row_keys()):
                var.set(True)  # останній показник не прибираємо — віджет став би порожнім
                return
        self.settings["hidden"] = sorted(hidden)
        self.save_settings()
        self.render() if self.data else self._layout()

    def _layout(self):
        """Перепакувати рядки в сталому порядку, пропускаючи приховані."""
        parts = [self.day_row.frame, self.separator, self.session_row.frame,
                 self.week_row.frame, self.scoped_box, self.models.frame]
        for widget in parts:
            widget.pack_forget()
        below = any(self.row_visible(k) for k in self._row_keys()[1:])
        if self.row_visible("today"):
            self.day_row.frame.pack(fill="x", padx=PAD, pady=(0, 10))
            if below:
                self.separator.pack(fill="x", padx=PAD, pady=(2, 10))
        if self.row_visible("session"):
            self.session_row.frame.pack(fill="x", padx=PAD, pady=(0, 10))
        if self.row_visible("week"):
            self.week_row.frame.pack(fill="x", padx=PAD, pady=(0, 10))
        self.scoped_box.pack(fill="x")
        self._place_models()
        self.fit_height()

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
            # мітка рівномірного темпу — лише на бажання: без пояснення вона
            # читається як зайва рисочка на смузі
            pace = day["pace"] if day and self.settings.get("pace_tick", False) else None
            self.week_row.draw(weekly_percent, tick=pace)
            self.week_row.note.config(text=fmt_reset(weekly["resets_at"], with_weekday=True))

        # --- ліміти по моделях ---
        scoped = data.get("scoped") or []
        while len(self.scoped_rows) < len(scoped):
            row = Row(self.scoped_box, "", self.settings, "model")
            self.scoped_rows.append(row)
            self.bind_drag(row.frame)

        titles = [entry["title"] or tr("model_limit") for entry in scoped]
        if titles != self.scoped_titles:
            # з'явилась чи зникла модель з окремим лімітом — її галочка в меню
            self.scoped_titles = titles
            self.menu.destroy()
            self._build_menu()

        # спершу зняти всі: інакше після приховування й повернення рядки
        # переставлялись би в іншому порядку
        for row in self.scoped_rows:
            row.frame.pack_forget()
        for row, entry in zip(self.scoped_rows, scoped):
            if self.row_visible("m:" + (entry["title"] or tr("model_limit"))):
                row.frame.pack(fill="x", padx=PAD, pady=(0, 10))
            row.title.config(text=entry["title"] or tr("model_limit"))
            family = (entry["title"] or "").split(" ")[0].lower()
            # той самий колір моделі, що й у блоці моделей унизу
            row.color_key = family if family in FAMILIES else "model"
            row.value.config(text="%d%%" % round(entry["percent"]))
            row.draw(entry["percent"])
            row.note.config(text=fmt_reset(entry["resets_at"], with_weekday=True))

        self._layout()


def main():
    if already_running(QuotaWidget.APP_NAME):
        return
    set_dpi_awareness()
    QuotaWidget().run()


if __name__ == "__main__":
    main()
