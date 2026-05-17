from __future__ import annotations
import csv
import json
import os
import threading
import time
import urllib.error
import urllib.request
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from tkinter import (
    END, LEFT, RIGHT, BOTH, TOP, BOTTOM, X, Y,
    StringVar, IntVar, BooleanVar,
    ttk, messagebox, filedialog,
)
import tkinter as tk
import tkinter.font as tkfont

# ── Optional: matplotlib for charts ──────────────────────────────────────────
try:
    import matplotlib
    matplotlib.use("TkAgg")
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
    MATPLOTLIB_OK = True
except ImportError:
    MATPLOTLIB_OK = False

# =============================================================================
#  CONSTANTS
# =============================================================================
APP_TITLE   = "CurrencyX  ·  Real-Time Converter"
DATA_DIR    = Path.home() / ".currencyx"
HISTORY_CSV = DATA_DIR / "history.csv"
CACHE_JSON  = DATA_DIR / "rate_cache.json"
FAV_JSON    = DATA_DIR / "favorites.json"

API_URL = "https://api.exchangerate-api.com/v4/latest/{base}"

REFRESH_INTERVAL = 300          # seconds between auto-refresh
MAX_HISTORY      = 500

CURRENCY_NAMES: dict[str, str] = {
    "AED": "UAE Dirham",        "ARS": "Argentine Peso",
    "AUD": "Australian Dollar", "BDT": "Bangladeshi Taka",
    "BRL": "Brazilian Real",    "CAD": "Canadian Dollar",
    "CHF": "Swiss Franc",       "CNY": "Chinese Yuan",
    "CZK": "Czech Koruna",      "DKK": "Danish Krone",
    "EGP": "Egyptian Pound",    "EUR": "Euro",
    "GBP": "British Pound",     "HKD": "Hong Kong Dollar",
    "HUF": "Hungarian Forint",  "IDR": "Indonesian Rupiah",
    "ILS": "Israeli Shekel",    "INR": "Indian Rupee",
    "JPY": "Japanese Yen",      "KRW": "South Korean Won",
    "KWD": "Kuwaiti Dinar",     "MXN": "Mexican Peso",
    "MYR": "Malaysian Ringgit", "NGN": "Nigerian Naira",
    "NOK": "Norwegian Krone",   "NZD": "New Zealand Dollar",
    "PHP": "Philippine Peso",   "PKR": "Pakistani Rupee",
    "PLN": "Polish Zloty",      "QAR": "Qatari Riyal",
    "RON": "Romanian Leu",      "RUB": "Russian Ruble",
    "SAR": "Saudi Riyal",       "SEK": "Swedish Krona",
    "SGD": "Singapore Dollar",  "THB": "Thai Baht",
    "TRY": "Turkish Lira",      "TWD": "Taiwan Dollar",
    "UAH": "Ukrainian Hryvnia", "USD": "US Dollar",
    "VND": "Vietnamese Dong",   "ZAR": "South African Rand",
}

POPULAR_CURRENCIES = [
    "USD", "EUR", "GBP", "PKR", "INR", "JPY", "CAD",
    "AUD", "CHF", "CNY", "AED", "SAR",
]

# Palette
CLR = {
    "bg":          "#0D0F14",
    "panel":       "#151821",
    "card":        "#1C2030",
    "card2":       "#222840",
    "accent":      "#00D4AA",
    "accent2":     "#4F8EF7",
    "accent3":     "#F7C04F",
    "danger":      "#FF5C6A",
    "text":        "#E8EAF2",
    "text_dim":    "#7A809A",
    "text_dimmer": "#4A5070",
    "border":      "#252A40",
    "hover":       "#2A3050",
    "success":     "#2ECC71",
}

# =============================================================================
#  DATA MODELS
# =============================================================================
class RateCache:
    """Persistent rate cache with TTL."""

    def __init__(self):
        DATA_DIR.mkdir(exist_ok=True)
        self._data: dict = {}
        self._load()

    def _load(self):
        if CACHE_JSON.exists():
            try:
                self._data = json.loads(CACHE_JSON.read_text())
            except Exception:
                self._data = {}

    def _save(self):
        CACHE_JSON.write_text(json.dumps(self._data, indent=2))

    def get(self, base: str) -> dict | None:
        entry = self._data.get(base)
        if entry and time.time() - entry["ts"] < REFRESH_INTERVAL:
            return entry["rates"]
        return None

    def set(self, base: str, rates: dict):
        self._data[base] = {"ts": time.time(), "rates": rates}
        self._save()

    def get_stale(self, base: str) -> dict | None:
        entry = self._data.get(base)
        return entry["rates"] if entry else None

    @property
    def last_updated(self) -> str:
        ts = max((v["ts"] for v in self._data.values()), default=0)
        if ts == 0:
            return "Never"
        return datetime.fromtimestamp(ts).strftime("%b %d, %Y  %H:%M")


class ConversionHistory:
    """CSV-backed conversion history."""

    FIELDS = ["timestamp", "from_currency", "to_currency", "amount", "result", "rate"]

    def __init__(self):
        DATA_DIR.mkdir(exist_ok=True)
        if not HISTORY_CSV.exists():
            with HISTORY_CSV.open("w", newline="") as f:
                csv.DictWriter(f, fieldnames=self.FIELDS).writeheader()

    def add(self, from_cur: str, to_cur: str, amount: float, result: float, rate: float):
        with HISTORY_CSV.open("a", newline="") as f:
            csv.DictWriter(f, fieldnames=self.FIELDS).writerow({
                "timestamp":     datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "from_currency": from_cur,
                "to_currency":   to_cur,
                "amount":        round(amount, 6),
                "result":        round(result, 6),
                "rate":          round(rate, 6),
            })

    def load(self) -> list[dict]:
        try:
            with HISTORY_CSV.open(newline="") as f:
                return list(csv.DictReader(f))[-MAX_HISTORY:]
        except Exception:
            return []

    def export_json(self, path: str):
        json.dump(self.load(), open(path, "w"), indent=2)


class Favorites:
    def __init__(self):
        DATA_DIR.mkdir(exist_ok=True)
        self._pairs: list[tuple] = []
        self._load()

    def _load(self):
        if FAV_JSON.exists():
            try:
                raw = json.loads(FAV_JSON.read_text())
                self._pairs = [tuple(p) for p in raw]
            except Exception:
                pass

    def _save(self):
        FAV_JSON.write_text(json.dumps(self._pairs))

    def toggle(self, frm: str, to: str) -> bool:
        pair = (frm, to)
        if pair in self._pairs:
            self._pairs.remove(pair)
            self._save()
            return False
        self._pairs.append(pair)
        self._save()
        return True

    def is_fav(self, frm: str, to: str) -> bool:
        return (frm, to) in self._pairs

    @property
    def pairs(self):
        return list(self._pairs)


# =============================================================================
#  API LAYER
# =============================================================================
class ExchangeAPI:
    """Thin wrapper around ExchangeRate-API (free tier, no key needed)."""

    def __init__(self, cache: RateCache):
        self.cache = cache
        self.online = True

    def fetch_rates(self, base: str) -> dict:
        base = base.upper()
        cached = self.cache.get(base)
        if cached:
            return cached

        try:
            url = API_URL.format(base=base)
            with urllib.request.urlopen(url, timeout=8) as resp:
                data = json.loads(resp.read())
            rates = data.get("rates", {})
            if not rates:
                raise ValueError("Empty rates from API")
            self.cache.set(base, rates)
            self.online = True
            return rates
        except (urllib.error.URLError, OSError):
            self.online = False
            stale = self.cache.get_stale(base)
            if stale:
                return stale
            raise ConnectionError("No internet and no cached rates available.")
        except Exception as exc:
            stale = self.cache.get_stale(base)
            if stale:
                return stale
            raise RuntimeError(f"API error: {exc}") from exc

    def convert(self, base: str, target: str, amount: float) -> tuple:
        """Returns (converted_amount, rate)."""
        rates = self.fetch_rates(base)
        tgt = target.upper()
        if tgt not in rates:
            raise KeyError(f"Currency '{tgt}' not found.")
        rate = rates[tgt]
        return amount * rate, rate

    def get_all_rates(self, base: str) -> dict:
        return self.fetch_rates(base)


# =============================================================================
#  GUI HELPERS
# =============================================================================
def _hex2rgb(h: str) -> tuple:
    h = h.lstrip("#")
    return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))

def _blend(c1: str, c2: str, t: float) -> str:
    r1, g1, b1 = _hex2rgb(c1)
    r2, g2, b2 = _hex2rgb(c2)
    r = int(r1 + (r2-r1)*t)
    g = int(g1 + (g2-g1)*t)
    b = int(b1 + (b2-b1)*t)
    return f"#{r:02x}{g:02x}{b:02x}"


class StyledButton(tk.Canvas):
    """Pill-shaped animated button."""

    def __init__(self, master, text="", command=None,
                 bg=None, fg=CLR["text"], width=160, height=40,
                 font_size=10, icon="", **kw):
        # Store dimensions under collision-safe names BEFORE super().__init__
        # because tk.Canvas exposes width/height as configure options and
        # Tkinter returns them as strings, causing TypeError in _draw().
        self._btn_w     = int(width)
        self._btn_h     = int(height)
        self._bg_normal = bg or CLR["accent"]
        self._bg_hover  = _blend(self._bg_normal, "#FFFFFF", 0.15)
        self._bg_press  = _blend(self._bg_normal, "#000000", 0.15)
        self._fg        = fg
        self._text      = text
        self._icon      = icon
        self._cmd       = command
        try:
            parent_bg = master["bg"]
        except Exception:
            parent_bg = CLR["bg"]
        super().__init__(master,
                         width=self._btn_w, height=self._btn_h,
                         bd=0, highlightthickness=0,
                         bg=parent_bg, cursor="hand2", **kw)
        self._fnt = tkfont.Font(family="Segoe UI", size=font_size, weight="bold")
        self._draw(self._bg_normal)
        self.bind("<Enter>",           lambda e: self._draw(self._bg_hover))
        self.bind("<Leave>",           lambda e: self._draw(self._bg_normal))
        self.bind("<Button-1>",        lambda e: self._press())
        self.bind("<ButtonRelease-1>", lambda e: self._release())
        self.tag_bind("all", "<Button-1>",        lambda e: self._press())
        self.tag_bind("all", "<ButtonRelease-1>", lambda e: self._release())

    def _draw(self, bg):
        self.delete("all")
        w, h = self._btn_w, self._btn_h
        r = h // 2
        self.create_oval(0, 0, h, h, fill=bg, outline="")
        self.create_oval(w-h, 0, w, h, fill=bg, outline="")
        self.create_rectangle(r, 0, w-r, h, fill=bg, outline="")
        label = (self._icon + "  " + self._text).strip()
        self.create_text(w//2, h//2, text=label, fill=self._fg,
                         font=self._fnt, anchor="center")

    def _press(self):
        self._draw(self._bg_press)

    def _release(self):
        self._draw(self._bg_normal)
        if self._cmd:
            self._cmd()

    def configure_text(self, text):
        self._text = text
        self._draw(self._bg_normal)

class Card(tk.Frame):
    def __init__(self, master, bg=None, pad=16, **kw):
        super().__init__(master, bg=bg or CLR["card"],
                         padx=pad, pady=pad, **kw)

class Separator(tk.Frame):
    def __init__(self, master, color=CLR["border"], **kw):
        super().__init__(master, bg=color, height=1, **kw)

class ToastNotification:
    """Temporary floating notification."""

    def __init__(self, root: tk.Tk):
        self._root = root
        self._win  = None

    def show(self, msg: str, kind: str = "success", duration: int = 2500):
        if self._win:
            try:
                self._win.destroy()
            except Exception:
                pass
        color = {"success": CLR["success"], "error": CLR["danger"],
                 "info": CLR["accent2"]}.get(kind, CLR["accent"])
        w = tk.Toplevel(self._root)
        w.overrideredirect(True)
        w.attributes("-topmost", True)
        w.configure(bg=color)
        tk.Label(w, text=msg, bg=color, fg="#fff",
                 font=("Segoe UI", 10, "bold"),
                 padx=18, pady=10).pack()
        self._root.update_idletasks()
        rx = self._root.winfo_x() + self._root.winfo_width()
        ry = self._root.winfo_y() + self._root.winfo_height()
        w.geometry(f"+{rx - 320}+{ry - 80}")
        self._win = w
        self._root.after(duration, lambda: self._safe_destroy(w))

    def _safe_destroy(self, w):
        try:
            w.destroy()
        except Exception:
            pass

# =============================================================================
#  MAIN APPLICATION
# =============================================================================
class CurrencyConverterApp(tk.Tk):

    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.configure(bg=CLR["bg"])
        self.minsize(1050, 680)
        self.geometry("1180x760")

        # Backend
        self._cache   = RateCache()
        self._api     = ExchangeAPI(self._cache)
        self._history = ConversionHistory()
        self._favs    = Favorites()
        self._toast   = ToastNotification(self)

        # State
        self._from_var   = StringVar(value="USD")
        self._to_var     = StringVar(value="PKR")
        self._amount_var = StringVar(value="1")
        self._result_var = StringVar(value="—")
        self._rate_var   = StringVar(value="Rate: —")
        self._status_var = StringVar(value="Ready")
        self._online_var = StringVar(value="● ONLINE")
        self._auto_refresh_after = None
        self._chart_canvas = None

        self._build_fonts()
        self._build_ui()
        self._schedule_refresh()
        self._fetch_rates_bg(silent=True)

    # -------------------------------------------------------------------------
    def _build_fonts(self):
        self.F = {
            "title":   tkfont.Font(family="Segoe UI", size=22, weight="bold"),
            "heading": tkfont.Font(family="Segoe UI", size=13, weight="bold"),
            "body":    tkfont.Font(family="Segoe UI", size=10),
            "mono":    tkfont.Font(family="Consolas",  size=10),
            "big":     tkfont.Font(family="Segoe UI", size=28, weight="bold"),
            "small":   tkfont.Font(family="Segoe UI", size=8),
            "label":   tkfont.Font(family="Segoe UI", size=9),
        }

    # =========================================================================
    # UI CONSTRUCTION
    # =========================================================================
    def _build_ui(self):
        self._build_topbar()
        self._build_tabbar()
        self._content = tk.Frame(self, bg=CLR["bg"])
        self._content.pack(fill=BOTH, expand=True)

        self._tabs: dict[str, tk.Frame] = {}
        for name, builder in [
            ("converter", self._build_tab_converter),
            ("rates",     self._build_tab_rates),
            ("multi",     self._build_tab_multi),
            ("history",   self._build_tab_history),
            ("favorites", self._build_tab_favorites),
        ]:
            frame = tk.Frame(self._content, bg=CLR["bg"])
            frame.place(relx=0, rely=0, relwidth=1, relheight=1)
            builder(frame)
            self._tabs[name] = frame

        self._build_statusbar()
        self._switch_tab("converter")

    # ── Top bar ───────────────────────────────────────────────────────────────
    def _build_topbar(self):
        bar = tk.Frame(self, bg=CLR["panel"], height=60)
        bar.pack(fill=X)
        bar.pack_propagate(False)

        left = tk.Frame(bar, bg=CLR["panel"])
        left.pack(side=LEFT, padx=20, pady=8)
        tk.Label(left, text="₿", font=("Segoe UI", 26, "bold"),
                 fg=CLR["accent"], bg=CLR["panel"]).pack(side=LEFT)
        title_f = tk.Frame(left, bg=CLR["panel"])
        title_f.pack(side=LEFT, padx=8)
        tk.Label(title_f, text="CurrencyX", font=self.F["heading"],
                 fg=CLR["text"], bg=CLR["panel"]).pack(anchor="w")
        tk.Label(title_f, text="Real-Time Exchange Rates", font=self.F["small"],
                 fg=CLR["text_dim"], bg=CLR["panel"]).pack(anchor="w")

        right = tk.Frame(bar, bg=CLR["panel"])
        right.pack(side=RIGHT, padx=20, pady=8)
        self._online_lbl = tk.Label(right, textvariable=self._online_var,
                                    font=("Segoe UI", 9, "bold"),
                                    fg=CLR["success"], bg=CLR["panel"])
        self._online_lbl.pack(anchor="e")
        self._updated_lbl = tk.Label(right,
                                     text=f"Updated: {self._cache.last_updated}",
                                     font=self.F["small"], fg=CLR["text_dim"],
                                     bg=CLR["panel"])
        self._updated_lbl.pack(anchor="e")

        Separator(self, color=CLR["border"]).pack(fill=X)

    # ── Tab bar ───────────────────────────────────────────────────────────────
    def _build_tabbar(self):
        self._tabbar = tk.Frame(self, bg=CLR["panel"], height=46)
        self._tabbar.pack(fill=X)
        self._tabbar.pack_propagate(False)

        self._tab_btns: dict[str, tk.Label] = {}
        specs = [
            ("converter", "⇄  Convert"),
            ("rates",     "📊  Live Rates"),
            ("multi",     "🔀  Multi-Convert"),
            ("history",   "🕘  History"),
            ("favorites", "★  Favorites"),
        ]
        for key, label in specs:
            btn = tk.Label(self._tabbar, text=label,
                           font=("Segoe UI", 9, "bold"),
                           fg=CLR["text_dim"], bg=CLR["panel"],
                           padx=18, pady=12, cursor="hand2")
            btn.pack(side=LEFT)
            btn.bind("<Button-1>", lambda _, k=key: self._switch_tab(k))
            btn.bind("<Enter>",    lambda e, b=btn: b.configure(fg=CLR["text"]))
            btn.bind("<Leave>",    lambda e, b=btn, k=key: self._on_tab_leave(b, k))
            self._tab_btns[key] = btn

        Separator(self, color=CLR["accent"]).pack(fill=X)
        self._active_tab = ""

    def _on_tab_leave(self, btn, key):
        if key != self._active_tab:
            btn.configure(fg=CLR["text_dim"])

    def _switch_tab(self, key: str):
        if self._active_tab:
            prev = self._tab_btns[self._active_tab]
            prev.configure(fg=CLR["text_dim"], bg=CLR["panel"])
        self._active_tab = key
        btn = self._tab_btns[key]
        btn.configure(fg=CLR["accent"], bg=CLR["hover"])
        for name, frame in self._tabs.items():
            if name == key:
                frame.lift()
            else:
                frame.lower()
        if key == "history":
            self._refresh_history_table()
        if key == "rates":
            self._refresh_rates_table()
        if key == "favorites":
            self._refresh_fav_table()

    # ── Status bar ────────────────────────────────────────────────────────────
    def _build_statusbar(self):
        bar = tk.Frame(self, bg=CLR["panel"], height=28)
        bar.pack(fill=X, side=BOTTOM)
        bar.pack_propagate(False)
        Separator(bar, color=CLR["border"]).pack(fill=X)
        tk.Label(bar, textvariable=self._status_var,
                 font=self.F["small"], fg=CLR["text_dim"],
                 bg=CLR["panel"]).pack(side=LEFT, padx=12)
        tk.Label(bar, text="ExchangeRate-API  |  Auto-refresh every 5 min",
                 font=self.F["small"], fg=CLR["text_dimmer"],
                 bg=CLR["panel"]).pack(side=RIGHT, padx=12)

    # =========================================================================
    # TAB: CONVERTER
    # =========================================================================
    def _build_tab_converter(self, parent):
        outer = tk.Frame(parent, bg=CLR["bg"])
        outer.pack(fill=BOTH, expand=True, padx=32, pady=24)

        # Main converter card
        card = Card(outer, bg=CLR["card"], pad=28)
        card.pack(fill=X)

        tk.Label(card, text="Currency Converter", font=self.F["heading"],
                 fg=CLR["text"], bg=CLR["card"]).pack(anchor="w")
        tk.Label(card, text="Enter an amount and select currencies to convert",
                 font=self.F["small"], fg=CLR["text_dim"],
                 bg=CLR["card"]).pack(anchor="w", pady=(2, 16))

        row = tk.Frame(card, bg=CLR["card"])
        row.pack(fill=X)

        self._build_labeled_entry(row, "Amount", self._amount_var, width=18).pack(
            side=LEFT, padx=(0, 12))
        self._build_labeled_combo(row, "From", self._from_var).pack(
            side=LEFT, padx=(0, 10))

        swap_f = tk.Frame(row, bg=CLR["card"])
        swap_f.pack(side=LEFT, padx=4, pady=(14, 0))
        StyledButton(swap_f, text="⇄", command=self._swap_currencies,
                     bg=CLR["card2"], width=48, height=38, font_size=14).pack()

        self._build_labeled_combo(row, "To", self._to_var).pack(
            side=LEFT, padx=(10, 16))

        btn_f = tk.Frame(row, bg=CLR["card"])
        btn_f.pack(side=LEFT, pady=(14, 0), padx=(8, 0))
        StyledButton(btn_f, text="Convert", command=self._do_convert,
                     bg=CLR["accent"], fg="#0D0F14",
                     width=120, height=38).pack()

        fav_f = tk.Frame(row, bg=CLR["card"])
        fav_f.pack(side=LEFT, pady=(14, 0), padx=6)
        self._fav_btn = StyledButton(fav_f, text="☆", command=self._toggle_fav,
                                     bg=CLR["card2"], width=48, height=38, font_size=14)
        self._fav_btn.pack()

        # Result card
        res_card = Card(outer, bg=CLR["card2"], pad=22)
        res_card.pack(fill=X, pady=(14, 0))

        res_row = tk.Frame(res_card, bg=CLR["card2"])
        res_row.pack(fill=X)

        left_res = tk.Frame(res_row, bg=CLR["card2"])
        left_res.pack(side=LEFT, fill=BOTH, expand=True)

        tk.Label(left_res, text="Converted Amount", font=self.F["label"],
                 fg=CLR["text_dim"], bg=CLR["card2"]).pack(anchor="w")
        tk.Label(left_res, textvariable=self._result_var,
                 font=self.F["big"], fg=CLR["accent"],
                 bg=CLR["card2"]).pack(anchor="w", pady=(4, 0))
        tk.Label(left_res, textvariable=self._rate_var,
                 font=self.F["body"], fg=CLR["text_dim"],
                 bg=CLR["card2"]).pack(anchor="w", pady=(2, 0))

        right_res = tk.Frame(res_row, bg=CLR["card2"])
        right_res.pack(side=RIGHT, padx=8)
        StyledButton(right_res, text="Copy", command=self._copy_result,
                     bg=CLR["accent2"], width=90, height=34, font_size=9).pack(pady=(0, 6))
        StyledButton(right_res, text="History →",
                     command=lambda: self._switch_tab("history"),
                     bg=CLR["card"], width=90, height=34, font_size=9).pack()

        # Quick pairs section
        quick_lbl_f = tk.Frame(outer, bg=CLR["bg"])
        quick_lbl_f.pack(fill=X, pady=(20, 6))
        tk.Label(quick_lbl_f, text="Quick Pairs", font=self.F["heading"],
                 fg=CLR["text"], bg=CLR["bg"]).pack(side=LEFT)
        StyledButton(quick_lbl_f, text="↻ Refresh", command=self._refresh_quick,
                     bg=CLR["card"], width=100, height=30, font_size=8).pack(side=RIGHT)

        self._quick_frame = tk.Frame(outer, bg=CLR["bg"])
        self._quick_frame.pack(fill=X)
        self._build_quick_pairs()

    def _build_labeled_entry(self, parent, label, var, width=18):
        frame = tk.Frame(parent, bg=parent["bg"])
        tk.Label(frame, text=label, font=self.F["label"],
                 fg=CLR["text_dim"], bg=parent["bg"]).pack(anchor="w", pady=(0, 4))
        e = tk.Entry(frame, textvariable=var, width=width,
                     font=self.F["body"], bg=CLR["card2"], fg=CLR["text"],
                     insertbackground=CLR["accent"], relief="flat",
                     highlightthickness=1, highlightcolor=CLR["accent"],
                     highlightbackground=CLR["border"])
        e.pack(ipady=7)
        e.bind("<Return>", lambda _: self._do_convert())
        return frame

    def _build_labeled_combo(self, parent, label, var):
        frame = tk.Frame(parent, bg=parent["bg"])
        tk.Label(frame, text=label, font=self.F["label"],
                 fg=CLR["text_dim"], bg=parent["bg"]).pack(anchor="w", pady=(0, 4))
        all_codes = sorted(CURRENCY_NAMES.keys())
        combo = ttk.Combobox(frame, textvariable=var, values=all_codes,
                             width=10, font=self.F["body"], state="normal")
        combo.pack(ipady=4)
        self._style_combo(combo)
        return frame

    def _style_combo(self, combo):
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TCombobox",
                        fieldbackground=CLR["card2"],
                        background=CLR["card2"],
                        foreground=CLR["text"],
                        selectbackground=CLR["accent"],
                        selectforeground="#000",
                        bordercolor=CLR["border"],
                        arrowcolor=CLR["accent"])

    def _build_quick_pairs(self):
        for w in self._quick_frame.winfo_children():
            w.destroy()

        pairs = [
            ("USD", "PKR"), ("USD", "EUR"), ("USD", "GBP"),
            ("USD", "INR"), ("EUR", "GBP"), ("GBP", "PKR"),
        ]
        for i, (frm, to) in enumerate(pairs):
            col_frame = tk.Frame(self._quick_frame, bg=CLR["bg"])
            col_frame.grid(row=0, column=i, padx=4, sticky="ew")
            self._quick_frame.columnconfigure(i, weight=1)

            card = Card(col_frame, bg=CLR["card"], pad=12)
            card.pack(fill=BOTH)

            top_r = tk.Frame(card, bg=CLR["card"])
            top_r.pack(fill=X)
            tk.Label(top_r, text=f"{frm} → {to}", font=("Segoe UI", 9, "bold"),
                     fg=CLR["text"], bg=CLR["card"]).pack(side=LEFT)

            rate_lbl = tk.Label(card, text="Loading…", font=self.F["heading"],
                                fg=CLR["accent"], bg=CLR["card"])
            rate_lbl.pack(anchor="w", pady=(4, 0))

            tk.Label(card, text=CURRENCY_NAMES.get(to, ""),
                     font=self.F["small"], fg=CLR["text_dim"],
                     bg=CLR["card"]).pack(anchor="w")

            use_btn = tk.Label(card, text="Use →", font=self.F["small"],
                               fg=CLR["accent2"], bg=CLR["card"], cursor="hand2")
            use_btn.pack(anchor="e")
            use_btn.bind("<Button-1>", lambda _, f=frm, t=to: self._use_quick(f, t))

            threading.Thread(target=self._load_quick_rate,
                             args=(frm, to, rate_lbl), daemon=True).start()

    def _use_quick(self, frm, to):
        self._from_var.set(frm)
        self._to_var.set(to)
        self._amount_var.set("1")
        self._do_convert()

    def _load_quick_rate(self, frm, to, lbl):
        try:
            rates = self._api.fetch_rates(frm)
            rate = rates.get(to, 0)
            self.after(0, lambda: lbl.configure(text=f"{rate:,.4f}"))
        except Exception:
            self.after(0, lambda: lbl.configure(text="N/A"))

    def _refresh_quick(self):
        self._build_quick_pairs()

    # ── Converter actions ─────────────────────────────────────────────────────
    def _do_convert(self):
        frm = self._from_var.get().upper().strip()
        to  = self._to_var.get().upper().strip()
        amt_str = self._amount_var.get().strip()

        if not frm or not to:
            self._toast.show("Please select currencies.", "error")
            return
        try:
            amt = float(amt_str.replace(",", ""))
            if amt < 0:
                raise ValueError
        except ValueError:
            self._toast.show("Invalid amount. Enter a positive number.", "error")
            return

        self._status_var.set("Fetching rates…")
        self._result_var.set("Loading…")

        def _work():
            try:
                result, rate = self._api.convert(frm, to, amt)
                self.after(0, lambda: self._show_result(frm, to, amt, result, rate))
            except (KeyError, ValueError) as e:
                self.after(0, lambda: self._toast.show(str(e), "error"))
                self.after(0, lambda: self._status_var.set("Error"))
            except (ConnectionError, RuntimeError) as e:
                self.after(0, lambda: self._toast.show(str(e), "error"))
                self.after(0, lambda: self._status_var.set("Offline / Error"))

        threading.Thread(target=_work, daemon=True).start()

    def _show_result(self, frm, to, amt, result, rate):
        decimals = 2 if result > 1 else 6
        fmt = f"{result:,.{decimals}f}"
        self._result_var.set(f"{fmt}  {to}")
        self._rate_var.set(
            f"1 {frm} = {rate:,.6f} {to}  ·  "
            f"1 {to} = {(1/rate):,.6f} {frm}"
        )
        self._history.add(frm, to, amt, result, rate)
        self._status_var.set(
            f"Converted {amt:,.2f} {frm}  →  {fmt} {to}   "
            f"[{self._cache.last_updated}]"
        )
        self._update_online_indicator()
        self._update_fav_btn()
        self._toast.show(f"{amt:.2f} {frm} = {fmt} {to}", "success")

    def _swap_currencies(self):
        frm = self._from_var.get()
        self._from_var.set(self._to_var.get())
        self._to_var.set(frm)
        if self._result_var.get() not in ("—", "Loading…"):
            self._do_convert()

    def _copy_result(self):
        raw = self._result_var.get()
        val = raw.split()[0].replace(",", "") if raw != "—" else ""
        if val:
            self.clipboard_clear()
            self.clipboard_append(val)
            self._toast.show("Result copied to clipboard!", "info")

    def _toggle_fav(self):
        frm = self._from_var.get().upper().strip()
        to  = self._to_var.get().upper().strip()
        if not frm or not to:
            return
        added = self._favs.toggle(frm, to)
        self._update_fav_btn()
        msg = (f"Added {frm}→{to} to favorites!" if added
               else f"Removed {frm}→{to} from favorites.")
        self._toast.show(msg, "success" if added else "info")

    def _update_fav_btn(self):
        frm = self._from_var.get().upper().strip()
        to  = self._to_var.get().upper().strip()
        is_fav = self._favs.is_fav(frm, to)
        self._fav_btn.configure_text("★" if is_fav else "☆")

    # =========================================================================
    # TAB: LIVE RATES
    # =========================================================================
    def _build_tab_rates(self, parent):
        outer = tk.Frame(parent, bg=CLR["bg"])
        outer.pack(fill=BOTH, expand=True, padx=32, pady=24)

        ctrl = Card(outer, bg=CLR["card"], pad=16)
        ctrl.pack(fill=X)

        ctrl_row = tk.Frame(ctrl, bg=CLR["card"])
        ctrl_row.pack(fill=X)

        tk.Label(ctrl_row, text="Base Currency:", font=self.F["body"],
                 fg=CLR["text_dim"], bg=CLR["card"]).pack(side=LEFT, padx=(0, 8))
        self._rates_base_var = StringVar(value="USD")
        base_combo = ttk.Combobox(ctrl_row, textvariable=self._rates_base_var,
                                  values=sorted(CURRENCY_NAMES.keys()),
                                  width=8, font=self.F["body"])
        base_combo.pack(side=LEFT, ipady=4, padx=(0, 12))
        self._style_combo(base_combo)

        tk.Label(ctrl_row, text="Filter:", font=self.F["body"],
                 fg=CLR["text_dim"], bg=CLR["card"]).pack(side=LEFT, padx=(0, 6))
        self._rates_filter_var = StringVar()
        tk.Entry(ctrl_row, textvariable=self._rates_filter_var,
                 width=14, font=self.F["body"],
                 bg=CLR["card2"], fg=CLR["text"],
                 insertbackground=CLR["accent"], relief="flat",
                 highlightthickness=1, highlightcolor=CLR["accent"],
                 highlightbackground=CLR["border"]).pack(side=LEFT, ipady=5, padx=(0, 12))
        self._rates_filter_var.trace_add("write", lambda *_: self._refresh_rates_table())

        StyledButton(ctrl_row, text="↻ Load Rates",
                     command=self._refresh_rates_table,
                     bg=CLR["accent"], fg="#0D0F14", width=120, height=34).pack(side=LEFT)

        tbl_frame = tk.Frame(outer, bg=CLR["bg"])
        tbl_frame.pack(fill=BOTH, expand=True, pady=(12, 0))

        self._rates_tree = self._build_treeview(
            tbl_frame,
            cols=("code", "name", "rate", "inverse"),
            headings=["Code", "Currency Name", "Rate (per USD)", "Inverse"],
            widths=[80, 240, 180, 180],
        )

    def _refresh_rates_table(self):
        base = self._rates_base_var.get().upper()
        filt = self._rates_filter_var.get().upper()
        self._status_var.set("Loading rates…")

        def _work():
            try:
                rates = self._api.get_all_rates(base)
                self.after(0, lambda: self._populate_rates(rates, base, filt))
            except Exception as e:
                self.after(0, lambda: self._toast.show(str(e), "error"))

        threading.Thread(target=_work, daemon=True).start()

    def _populate_rates(self, rates: dict, base: str, filt: str):
        for item in self._rates_tree.get_children():
            self._rates_tree.delete(item)
        self._rates_tree.heading("rate", text=f"Rate (per {base})")
        for code, rate in sorted(rates.items()):
            name = CURRENCY_NAMES.get(code, code)
            if filt and filt not in code and filt not in name.upper():
                continue
            inv = f"{1/rate:.6f}" if rate else "—"
            tag = "pop" if code in POPULAR_CURRENCIES else "normal"
            self._rates_tree.insert("", END,
                                    values=(code, name, f"{rate:.6f}", inv),
                                    tags=(tag,))
        self._rates_tree.tag_configure("pop",    foreground=CLR["accent"])
        self._rates_tree.tag_configure("normal", foreground=CLR["text"])
        n = len(self._rates_tree.get_children())
        self._status_var.set(f"Loaded {n} rates for {base}")
        self._updated_lbl.configure(text=f"Updated: {self._cache.last_updated}")
        self._update_online_indicator()

    # =========================================================================
    # TAB: MULTI-CONVERT
    # =========================================================================
    def _build_tab_multi(self, parent):
        outer = tk.Frame(parent, bg=CLR["bg"])
        outer.pack(fill=BOTH, expand=True, padx=32, pady=24)

        ctrl = Card(outer, bg=CLR["card"], pad=16)
        ctrl.pack(fill=X)

        tk.Label(ctrl, text="Multi-Currency Converter", font=self.F["heading"],
                 fg=CLR["text"], bg=CLR["card"]).pack(anchor="w", pady=(0, 10))

        row = tk.Frame(ctrl, bg=CLR["card"])
        row.pack(fill=X)

        tk.Label(row, text="Base Currency:", font=self.F["body"],
                 fg=CLR["text_dim"], bg=CLR["card"]).pack(side=LEFT, padx=(0, 6))
        self._multi_base_var = StringVar(value="USD")
        base_c = ttk.Combobox(row, textvariable=self._multi_base_var,
                               values=sorted(CURRENCY_NAMES.keys()),
                               width=8, font=self.F["body"])
        base_c.pack(side=LEFT, ipady=4, padx=(0, 14))
        self._style_combo(base_c)

        tk.Label(row, text="Amount:", font=self.F["body"],
                 fg=CLR["text_dim"], bg=CLR["card"]).pack(side=LEFT, padx=(0, 6))
        self._multi_amt_var = StringVar(value="1")
        tk.Entry(row, textvariable=self._multi_amt_var, width=14,
                 font=self.F["body"], bg=CLR["card2"], fg=CLR["text"],
                 insertbackground=CLR["accent"], relief="flat",
                 highlightthickness=1, highlightcolor=CLR["accent"],
                 highlightbackground=CLR["border"]).pack(side=LEFT, ipady=5, padx=(0, 12))

        StyledButton(row, text="Convert All", command=self._do_multi_convert,
                     bg=CLR["accent"], fg="#0D0F14", width=120, height=34).pack(side=LEFT)

        # Currency checkboxes
        chk_frame = Card(outer, bg=CLR["card"], pad=14)
        chk_frame.pack(fill=X, pady=(10, 0))
        tk.Label(chk_frame, text="Select target currencies:",
                 font=self.F["body"], fg=CLR["text_dim"],
                 bg=CLR["card"]).pack(anchor="w", pady=(0, 8))

        grid_f = tk.Frame(chk_frame, bg=CLR["card"])
        grid_f.pack(fill=X)
        self._multi_vars: dict[str, BooleanVar] = {}
        cols_n = 9
        for i, code in enumerate(sorted(CURRENCY_NAMES.keys())):
            var = BooleanVar(value=code in POPULAR_CURRENCIES)
            self._multi_vars[code] = var
            tk.Checkbutton(grid_f, text=code, variable=var,
                           bg=CLR["card"], fg=CLR["text"],
                           selectcolor=CLR["card2"],
                           activebackground=CLR["card"],
                           activeforeground=CLR["accent"],
                           font=self.F["small"]).grid(
                row=i // cols_n, column=i % cols_n, sticky="w", padx=2)

        res_frame = tk.Frame(outer, bg=CLR["bg"])
        res_frame.pack(fill=BOTH, expand=True, pady=(12, 0))

        self._multi_tree = self._build_treeview(
            res_frame,
            cols=("currency", "name", "rate", "result"),
            headings=["Currency", "Name", "Rate", "Converted Amount"],
            widths=[100, 200, 180, 200],
        )

    def _do_multi_convert(self):
        base    = self._multi_base_var.get().upper()
        amt_str = self._multi_amt_var.get().strip()
        try:
            amt = float(amt_str.replace(",", ""))
        except ValueError:
            self._toast.show("Invalid amount.", "error")
            return

        targets = [c for c, v in self._multi_vars.items() if v.get()]
        if not targets:
            self._toast.show("Select at least one target currency.", "error")
            return

        self._status_var.set("Converting…")

        def _work():
            try:
                rates   = self._api.fetch_rates(base)
                results = []
                for code in sorted(targets):
                    if code in rates:
                        rate = rates[code]
                        results.append((code, CURRENCY_NAMES.get(code, ""), rate, amt * rate))
                self.after(0, lambda: self._populate_multi(results, base))
            except Exception as e:
                self.after(0, lambda: self._toast.show(str(e), "error"))

        threading.Thread(target=_work, daemon=True).start()

    def _populate_multi(self, results, base):
        for item in self._multi_tree.get_children():
            self._multi_tree.delete(item)
        for code, name, rate, res in results:
            dec = 2 if res > 1 else 6
            self._multi_tree.insert("", END, values=(
                code, name, f"{rate:.6f}", f"{res:,.{dec}f}",
            ))
        self._status_var.set(f"Converted to {len(results)} currencies from {base}")
        self._toast.show(f"Done! {len(results)} currencies converted.", "success")

    # =========================================================================
    # TAB: HISTORY
    # =========================================================================
    def _build_tab_history(self, parent):
        outer = tk.Frame(parent, bg=CLR["bg"])
        outer.pack(fill=BOTH, expand=True, padx=32, pady=24)

        ctrl = Card(outer, bg=CLR["card"], pad=14)
        ctrl.pack(fill=X)
        ctrl_row = tk.Frame(ctrl, bg=CLR["card"])
        ctrl_row.pack(fill=X)

        tk.Label(ctrl_row, text="Conversion History", font=self.F["heading"],
                 fg=CLR["text"], bg=CLR["card"]).pack(side=LEFT)

        btns = tk.Frame(ctrl_row, bg=CLR["card"])
        btns.pack(side=RIGHT)
        StyledButton(btns, text="Export CSV", command=self._export_csv,
                     bg=CLR["accent2"], width=100, height=32, font_size=8).pack(
            side=LEFT, padx=4)
        StyledButton(btns, text="Export JSON", command=self._export_json,
                     bg=CLR["card2"], width=100, height=32, font_size=8).pack(
            side=LEFT, padx=4)
        StyledButton(btns, text="↻ Refresh", command=self._refresh_history_table,
                     bg=CLR["card2"], width=90, height=32, font_size=8).pack(side=LEFT)

        # Trend chart area
        if MATPLOTLIB_OK:
            chart_card = Card(outer, bg=CLR["card"], pad=10)
            chart_card.pack(fill=X, pady=(10, 0))
            tk.Label(chart_card, text="Rate Trend  (click a row to plot)",
                     font=self.F["label"], fg=CLR["text_dim"],
                     bg=CLR["card"]).pack(anchor="w", pady=(0, 4))
            self._chart_frame = tk.Frame(chart_card, bg=CLR["card"], height=160)
            self._chart_frame.pack(fill=X)
            self._chart_frame.pack_propagate(False)

        tbl_frame = tk.Frame(outer, bg=CLR["bg"])
        tbl_frame.pack(fill=BOTH, expand=True, pady=(12, 0))

        self._hist_tree = self._build_treeview(
            tbl_frame,
            cols=("ts", "from", "to", "amount", "result", "rate"),
            headings=["Timestamp", "From", "To", "Amount", "Result", "Rate"],
            widths=[160, 70, 70, 120, 140, 130],
        )
        if MATPLOTLIB_OK:
            self._hist_tree.bind("<ButtonRelease-1>", self._on_history_click)

        tk.Label(outer,
                 text="History is saved automatically. "
                      "Click a row to view the rate trend chart.",
                 font=self.F["small"], fg=CLR["text_dim"],
                 bg=CLR["bg"]).pack(anchor="w", pady=(6, 0))

    def _refresh_history_table(self):
        for item in self._hist_tree.get_children():
            self._hist_tree.delete(item)
        rows = self._history.load()
        for r in reversed(rows):
            self._hist_tree.insert("", END, values=(
                r.get("timestamp", ""),
                r.get("from_currency", ""),
                r.get("to_currency", ""),
                r.get("amount", ""),
                r.get("result", ""),
                r.get("rate", ""),
            ))
        self._status_var.set(f"History: {len(rows)} entries")

    def _on_history_click(self, _):
        sel = self._hist_tree.selection()
        if not sel:
            return
        vals = self._hist_tree.item(sel[0])["values"]
        if len(vals) < 3:
            return
        frm, to = str(vals[1]), str(vals[2])
        rows = [r for r in self._history.load()
                if r.get("from_currency") == frm and r.get("to_currency") == to]
        if not rows:
            return
        # Allow single-point: duplicate so the line renders
        rate_values = [float(r["rate"]) for r in rows[-20:]]
        if len(rate_values) == 1:
            rate_values = rate_values * 2
        self._draw_trend_chart(rate_values, f"{frm} \u2192 {to}  Rate History ({len(rows)} records)")

    def _draw_trend_chart(self, values, title):
        # Destroy previous canvas widget cleanly
        if self._chart_canvas is not None:
            try:
                self._chart_canvas.get_tk_widget().destroy()
            except Exception:
                pass
            self._chart_canvas = None
        # Clear any leftover children
        for child in self._chart_frame.winfo_children():
            try:
                child.destroy()
            except Exception:
                pass

        fig = Figure(figsize=(10, 1.78), dpi=90, facecolor=CLR["card"])
        ax  = fig.add_subplot(111)
        ax.set_facecolor(CLR["card2"])

        xs = list(range(len(values)))
        ax.plot(xs, values, color=CLR["accent"], linewidth=2.5,
                marker="o", markersize=5, zorder=3)
        ax.fill_between(xs, values, min(values) * 0.999,
                        alpha=0.25, color=CLR["accent"])

        ax.annotate(f"{values[0]:.4f}",  xy=(xs[0],  values[0]),
                    fontsize=7, color=CLR["text_dim"],
                    xytext=(4, 4), textcoords="offset points")
        ax.annotate(f"{values[-1]:.4f}", xy=(xs[-1], values[-1]),
                    fontsize=7, color=CLR["accent"],
                    xytext=(-30, 4), textcoords="offset points")

        ax.set_title(title, color=CLR["text"], fontsize=9, pad=3,
                     loc="left", fontweight="bold")
        ax.tick_params(colors=CLR["text_dim"], labelsize=7)
        ax.yaxis.tick_right()
        ax.set_xticks([])
        for spine in ax.spines.values():
            spine.set_edgecolor(CLR["border"])
        fig.tight_layout(pad=0.4)

        self._chart_canvas = FigureCanvasTkAgg(fig, master=self._chart_frame)
        self._chart_canvas.draw()
        self._chart_canvas.get_tk_widget().pack(fill=BOTH, expand=True)

    def _export_csv(self):
        path = filedialog.asksaveasfilename(
            defaultextension=".csv", filetypes=[("CSV files", "*.csv")])
        if path:
            import shutil
            shutil.copy(HISTORY_CSV, path)
            self._toast.show("History exported to CSV!", "success")

    def _export_json(self):
        path = filedialog.asksaveasfilename(
            defaultextension=".json", filetypes=[("JSON files", "*.json")])
        if path:
            self._history.export_json(path)
            self._toast.show("History exported to JSON!", "success")

    # =========================================================================
    # TAB: FAVORITES
    # =========================================================================
    def _build_tab_favorites(self, parent):
        outer = tk.Frame(parent, bg=CLR["bg"])
        outer.pack(fill=BOTH, expand=True, padx=32, pady=24)

        ctrl = Card(outer, bg=CLR["card"], pad=14)
        ctrl.pack(fill=X)
        ctrl_row = tk.Frame(ctrl, bg=CLR["card"])
        ctrl_row.pack(fill=X)
        tk.Label(ctrl_row, text="★  Favorite Pairs", font=self.F["heading"],
                 fg=CLR["text"], bg=CLR["card"]).pack(side=LEFT)
        StyledButton(ctrl_row, text="↻ Refresh Rates",
                     command=self._refresh_fav_table,
                     bg=CLR["accent"], fg="#0D0F14", width=130, height=32).pack(side=RIGHT)
        tk.Label(ctrl, text="Save frequently used pairs here for quick access.",
                 font=self.F["small"], fg=CLR["text_dim"],
                 bg=CLR["card"]).pack(anchor="w", pady=(4, 0))

        tbl_frame = tk.Frame(outer, bg=CLR["bg"])
        tbl_frame.pack(fill=BOTH, expand=True, pady=(14, 0))

        self._fav_tree = self._build_treeview(
            tbl_frame,
            cols=("from", "to", "from_name", "to_name", "rate"),
            headings=["From", "To", "From Currency", "To Currency", "Live Rate"],
            widths=[80, 80, 200, 200, 180],
        )
        self._fav_tree.bind("<Double-1>", self._on_fav_double_click)
        tk.Label(outer,
                 text="Double-click a pair to load it in the converter.  "
                      "Add favorites via the ☆ button on the Convert tab.",
                 font=self.F["small"], fg=CLR["text_dim"],
                 bg=CLR["bg"]).pack(anchor="w", pady=(6, 0))

    def _refresh_fav_table(self):
        for item in self._fav_tree.get_children():
            self._fav_tree.delete(item)
        pairs = self._favs.pairs
        if not pairs:
            self._fav_tree.insert("", END, values=(
                "—", "—", "No favorites yet.",
                "Add via ☆ on the Convert tab", "—",
            ))
            return
        for frm, to in pairs:
            self._fav_tree.insert("", END, values=(
                frm, to,
                CURRENCY_NAMES.get(frm, frm),
                CURRENCY_NAMES.get(to, to),
                "Loading…",
            ))
        threading.Thread(target=self._load_fav_rates, daemon=True).start()

    def _load_fav_rates(self):
        for item in self._fav_tree.get_children():
            vals = self._fav_tree.item(item)["values"]
            frm, to = str(vals[0]), str(vals[1])
            if frm == "—":
                continue
            try:
                rates = self._api.fetch_rates(frm)
                rate  = rates.get(to, 0)
                new_v = list(vals)
                new_v[4] = f"{rate:,.6f}"
                self.after(0, lambda i=item, v=new_v: self._fav_tree.item(i, values=v))
            except Exception:
                pass

    def _on_fav_double_click(self, _):
        sel = self._fav_tree.selection()
        if not sel:
            return
        vals = self._fav_tree.item(sel[0])["values"]
        frm, to = str(vals[0]), str(vals[1])
        if frm == "—":
            return
        self._from_var.set(frm)
        self._to_var.set(to)
        self._switch_tab("converter")
        self._do_convert()

    # =========================================================================
    # SHARED WIDGET BUILDER
    # =========================================================================
    def _build_treeview(self, parent, cols: tuple, headings: list,
                        widths: list) -> ttk.Treeview:
        style = ttk.Style()
        style.configure("Dark.Treeview",
                        background=CLR["card"],
                        foreground=CLR["text"],
                        fieldbackground=CLR["card"],
                        rowheight=28,
                        font=("Segoe UI", 9))
        style.configure("Dark.Treeview.Heading",
                        background=CLR["card2"],
                        foreground=CLR["accent"],
                        font=("Segoe UI", 9, "bold"),
                        relief="flat")
        style.map("Dark.Treeview",
                  background=[("selected", CLR["hover"])],
                  foreground=[("selected", CLR["accent"])])

        container = tk.Frame(parent, bg=CLR["bg"])
        container.pack(fill=BOTH, expand=True)

        tree = ttk.Treeview(container, columns=cols, show="headings",
                            style="Dark.Treeview")
        sb_y = ttk.Scrollbar(container, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=sb_y.set)
        sb_y.pack(side=RIGHT, fill=Y)
        tree.pack(side=LEFT, fill=BOTH, expand=True)

        for col, heading, width in zip(cols, headings, widths):
            tree.heading(col, text=heading)
            tree.column(col, width=width, anchor="w", minwidth=50)

        return tree

    # =========================================================================
    # ONLINE INDICATOR
    # =========================================================================
    def _update_online_indicator(self):
        if self._api.online:
            self._online_var.set("● ONLINE")
            self._online_lbl.configure(fg=CLR["success"])
        else:
            self._online_var.set("● OFFLINE (cached)")
            self._online_lbl.configure(fg=CLR["danger"])

    # =========================================================================
    # AUTO-REFRESH
    # =========================================================================
    def _schedule_refresh(self):
        if self._auto_refresh_after:
            self.after_cancel(self._auto_refresh_after)
        self._auto_refresh_after = self.after(
            REFRESH_INTERVAL * 1000, self._auto_refresh
        )

    def _auto_refresh(self):
        self._fetch_rates_bg(silent=True)
        self._schedule_refresh()

    def _fetch_rates_bg(self, silent=False):
        def _work():
            try:
                self._api.fetch_rates(self._from_var.get().upper())
                self.after(0, self._update_online_indicator)
                self.after(0, lambda: self._updated_lbl.configure(
                    text=f"Updated: {self._cache.last_updated}"))
                if not silent:
                    self.after(0, lambda: self._toast.show("Rates refreshed!", "success"))
            except Exception:
                self.after(0, self._update_online_indicator)

        threading.Thread(target=_work, daemon=True).start()

# =============================================================================
#  ENTRY POINT
# =============================================================================
def main():
    app = CurrencyConverterApp()
    app.mainloop()

if __name__ == "__main__":
    main()
