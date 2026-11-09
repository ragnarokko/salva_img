"""Scarica le immagini JPG di una pagina web, una dopo l'altra, con pausa impostabile.

Uso: python scarica_immagini.py
Dipendenze: requests, Pillow (tkinter e' incluso in Python).
"""
import html
import io
import os
import re
import shutil
import tempfile
import threading
import tkinter as tk
from html.parser import HTMLParser
from tkinter import filedialog, messagebox, ttk
from urllib.parse import urljoin, urlparse

import requests
from PIL import Image, ImageTk

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
SKIP_EXT = (".png", ".gif", ".webp", ".svg", ".ico", ".avif", ".bmp",
            ".css", ".js", ".json", ".woff", ".woff2", ".mp4")
THUMB = 150


class Collector(HTMLParser):
    """Raccoglie in ordine di apparizione gli URL candidati nel DOM."""

    def __init__(self):
        super().__init__()
        self.urls = []

    def _add(self, u):
        if u and not u.startswith(("data:", "javascript:", "#")):
            self.urls.append(u.strip())

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "img":
            for k in ("src", "data-src", "data-original", "data-lazy-src"):
                self._add(a.get(k))
            for k in ("srcset", "data-srcset"):
                if a.get(k):
                    parts = [p.strip().split(" ")[0] for p in a[k].split(",") if p.strip()]
                    if parts:
                        self._add(parts[-1])  # di norma la piu' grande
        elif tag == "source":
            if a.get("srcset"):
                parts = [p.strip().split(" ")[0] for p in a["srcset"].split(",") if p.strip()]
                if parts:
                    self._add(parts[-1])
        elif tag == "a":
            href = a.get("href")
            if href and re.search(r"\.jpe?g($|\?)", href, re.I):
                self._add(href)


def find_candidates(page_html, base_url):
    c = Collector()
    c.feed(page_html)
    found = list(c.urls)
    # URL .jpg/.jpeg dentro script/JSON incorporati nella pagina
    text = page_html.replace("\\/", "/").replace("\\u0026", "&").replace('\\"', '"')
    # <link rel="preload" as="image" href="...">
    for m in re.finditer(r"<link\b[^>]*>", text, re.I):
        tag = m.group(0)
        if re.search(r'\bas=["\']image["\']', tag, re.I):
            h = re.search(r'\bhref=["\']([^"\']+)["\']', tag, re.I)
            if h:
                found.append(h.group(1))
    # chiavi JSON tipo "imageUrl":"https://..." (pagine che costruiscono le immagini via JS)
    for m in re.finditer(
            r'"[A-Za-z_]*(?:image|img|photo|picture|thumb)[A-Za-z_]*"\s*:\s*"(https?://[^"]+)"',
            text, re.I):
        found.append(m.group(1))
    for m in re.finditer(r"https?://[^\s\"'<>\\]+?\.jpe?g(?:\?[^\s\"'<>\\]*)?", text, re.I):
        found.append(m.group(0))
    out, seen = [], set()
    for u in found:
        u = urljoin(base_url, html.unescape(u))
        if urlparse(u).scheme not in ("http", "https"):
            continue
        path = urlparse(u).path.lower()
        if path.endswith(SKIP_EXT):
            continue
        key = u.split("?")[0]
        if key in seen:
            continue
        seen.add(key)
        out.append(u)
    return out


def is_jpeg(resp):
    ct = resp.headers.get("content-type", "").lower().split(";")[0].strip()
    return ct in ("image/jpeg", "image/jpg", "image/pjpeg")


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Scarica immagini JPG")
        self.geometry("900x700")
        self.session = requests.Session()
        self.session.headers["User-Agent"] = UA
        self.stop = threading.Event()
        self.tmp = None
        self.files = []      # percorsi temporanei in ordine
        self.photos = []
        self.host = ""
        self.running = False

        top = ttk.Frame(self, padding=8)
        top.pack(fill="x")
        ttk.Label(top, text="Sito (URL):").grid(row=0, column=0, sticky="w")
        self.url = tk.StringVar()
        ttk.Entry(top, textvariable=self.url).grid(row=0, column=1, columnspan=3, sticky="ew", padx=4)
        ttk.Label(top, text="Pausa (ms):").grid(row=1, column=0, sticky="w")
        self.delay = tk.StringVar(value="400")
        ttk.Entry(top, textvariable=self.delay, width=8).grid(row=1, column=1, sticky="w", padx=4)
        ttk.Label(top, text="Cartella destinazione:").grid(row=2, column=0, sticky="w")
        self.dest = tk.StringVar(value=os.path.join(os.path.expanduser("~"), "Downloads"))
        ttk.Entry(top, textvariable=self.dest).grid(row=2, column=1, columnspan=2, sticky="ew", padx=4)
        ttk.Button(top, text="Sfoglia...", command=self.browse).grid(row=2, column=3)
        row3 = ttk.Frame(top)
        row3.grid(row=3, column=1, columnspan=3, sticky="w", pady=6)
        self.btn_find = ttk.Button(row3, text="Cerca immagini", command=self.start_find)
        self.btn_find.pack(side="left", padx=4)
        self.btn_clear = ttk.Button(row3, text="Pulisci", command=self.clear)
        self.btn_clear.pack(side="left")
        self.ask_exists = tk.BooleanVar(value=False)
        ttk.Checkbutton(row3, text="Chiedi se presente", variable=self.ask_exists
                        ).pack(side="left", padx=(12, 0))
        self.custom_on = tk.BooleanVar(value=False)
        ttk.Checkbutton(row3, text="Scegli la cartella delle immagini", variable=self.custom_on,
                        command=self.toggle_custom).pack(side="left", padx=(12, 0))
        # riga visibile solo se il flag e' attivo
        self.custom_row = ttk.Frame(top)
        self.custom_row.grid(row=4, column=0, columnspan=4, sticky="ew")
        ttk.Label(self.custom_row, text="Cartella immagini:").pack(side="left")
        self.custom = tk.StringVar()
        ttk.Entry(self.custom_row, textvariable=self.custom).pack(
            side="left", fill="x", expand=True, padx=4)
        ttk.Button(self.custom_row, text="Sfoglia...", command=self.browse_custom).pack(side="left")
        self.custom_row.grid_remove()
        top.columnconfigure(2, weight=1)

        self.status = tk.StringVar(value="Inserisci l'indirizzo e premi 'Cerca immagini'.")
        ttk.Label(self, textvariable=self.status, padding=(8, 0)).pack(fill="x")
        self.bar = ttk.Progressbar(self, mode="determinate")
        self.bar.pack(fill="x", padx=8, pady=4)

        mid = ttk.Frame(self)
        mid.pack(fill="both", expand=True, padx=8)
        self.canvas = tk.Canvas(mid, highlightthickness=0)
        sb = ttk.Scrollbar(mid, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.grid_frame = ttk.Frame(self.canvas)
        self.canvas.create_window((0, 0), window=self.grid_frame, anchor="nw")
        self.grid_frame.bind("<Configure>",
                             lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind_all("<MouseWheel>",
                             lambda e: self.canvas.yview_scroll(-1 * (e.delta // 120), "units"))

        bottom = ttk.Frame(self, padding=8)
        bottom.pack(fill="x")
        self.btn_ok = ttk.Button(bottom, text="OK, salva nella cartella", command=self.save, state="disabled")
        self.btn_ok.pack(side="left")
        self.btn_cancel = ttk.Button(bottom, text="Annulla", command=self.cancel, state="disabled")
        self.btn_cancel.pack(side="left", padx=8)
        self.protocol("WM_DELETE_WINDOW", self.on_close)

    # ---------- utilita' ----------
    def ui(self, fn, *a):
        self.after(0, lambda: fn(*a))

    def set_status(self, s):
        self.status.set(s)

    def get_delay(self):
        try:
            return max(0, int(self.delay.get())) / 1000.0
        except ValueError:
            return 0.4

    def browse(self):
        d = filedialog.askdirectory(initialdir=self.dest.get())
        if d:
            self.dest.set(d)

    def toggle_custom(self):
        if self.custom_on.get():
            self.custom_row.grid()
        else:
            self.custom_row.grid_remove()

    def browse_custom(self):
        d = filedialog.askdirectory(initialdir=self.custom.get() or self.dest.get())
        if d:
            self.custom.set(os.path.normpath(d))

    def ask_conflict(self, folder):
        """Chiede cosa fare se la cartella esiste gia'. Ritorna 'sovrascrivi', 'nuova' o 'salta'."""
        win = tk.Toplevel(self)
        win.title("Cartella già presente")
        win.transient(self)
        win.resizable(False, False)
        ttk.Label(win, text=f"La cartella esiste già e contiene dei file:\n{folder}\n\nCosa vuoi fare?",
                  padding=12, justify="left").pack()
        res = {"v": "salta"}

        def pick(v):
            res["v"] = v
            win.destroy()

        bt = ttk.Frame(win, padding=(12, 0, 12, 12))
        bt.pack()
        ttk.Button(bt, text="Sovrascrivi", command=lambda: pick("sovrascrivi")).pack(side="left", padx=4)
        ttk.Button(bt, text="Nuova cartella (_2, _3...)", command=lambda: pick("nuova")).pack(side="left", padx=4)
        b_skip = ttk.Button(bt, text="Salta", command=lambda: pick("salta"))
        b_skip.pack(side="left", padx=4)
        b_skip.focus_set()
        win.bind("<Return>", lambda e: pick("salta"))
        win.bind("<Escape>", lambda e: pick("salta"))
        win.protocol("WM_DELETE_WINDOW", lambda: pick("salta"))
        win.grab_set()
        self.wait_window(win)
        return res["v"]

    def cleanup_tmp(self):
        if self.tmp and os.path.isdir(self.tmp):
            shutil.rmtree(self.tmp, ignore_errors=True)
        self.tmp = None
        self.files = []

    def cancel(self):
        self.stop.set()

    def clear(self):
        """Svuota indirizzo, anteprime e stato. Se una ricerca e' in corso la ferma."""
        self.stop.set()
        self.url.set("")
        for w in self.grid_frame.winfo_children():
            w.destroy()
        self.photos = []
        self.canvas.yview_moveto(0)
        self.bar.config(value=0)
        self.btn_ok.config(state="disabled")
        self.set_status("Inserisci l'indirizzo e premi 'Cerca immagini'.")
        if not self.running:  # altrimenti ci pensa il thread di ricerca a chiudere
            self.cleanup_tmp()

    def on_close(self):
        self.stop.set()
        self.cleanup_tmp()
        self.destroy()

    # ---------- ricerca + anteprima ----------
    def start_find(self):
        url = self.url.get().strip()
        if not url:
            return
        if not urlparse(url).scheme:
            url = "https://" + url
            self.url.set(url)
        self.stop.clear()
        self.cleanup_tmp()
        for w in self.grid_frame.winfo_children():
            w.destroy()
        self.photos = []
        self.btn_find.config(state="disabled")
        self.btn_ok.config(state="disabled")
        self.btn_cancel.config(state="normal")
        self.host = urlparse(url).netloc.split(":")[0]
        self.running = True
        threading.Thread(target=self.find_worker, args=(url,), daemon=True).start()

    def find_worker(self, url):
        delay = self.get_delay()
        try:
            self.ui(self.set_status, "Leggo la pagina...")
            r = self.session.get(url, timeout=30)
            r.raise_for_status()
            cands = find_candidates(r.text, r.url)
            self.tmp = tempfile.mkdtemp(prefix="scarica_img_")
            self.ui(lambda: self.bar.config(maximum=max(1, len(cands)), value=0))
            n = 0
            for i, u in enumerate(cands, 1):
                if self.stop.is_set():
                    break
                self.ui(self.set_status,
                        f"Controllo {i}/{len(cands)}: trovate {n} immagini JPG")
                try:
                    resp = self.session.get(u, timeout=30, headers={"Referer": url})
                except requests.RequestException:
                    continue
                if resp.status_code == 200 and is_jpeg(resp) and resp.content:
                    n += 1
                    path = os.path.join(self.tmp, f"{n:05d}.jpg")
                    with open(path, "wb") as f:
                        f.write(resp.content)
                    self.files.append(path)
                    self.ui(self.add_thumb, n, path)
                self.ui(lambda v=i: self.bar.config(value=v))
                if i < len(cands):
                    self.stop.wait(delay)
            if self.stop.is_set():
                if self.url.get().strip():
                    self.ui(self.set_status, "Operazione annullata.")
                self.cleanup_tmp()
            elif not self.files:
                self.ui(self.set_status, "Nessuna immagine JPG trovata in questa pagina.")
            else:
                self.ui(self.set_status,
                        f"Trovate {len(self.files)} immagini JPG. Controlla le anteprime e premi OK per salvarle.")
                self.ui(lambda: self.btn_ok.config(state="normal"))
        except Exception as e:
            self.ui(self.set_status, f"Errore: {e}")
        finally:
            self.running = False
            self.ui(lambda: self.btn_find.config(state="normal"))
            self.ui(lambda: self.btn_cancel.config(state="disabled"))

    def add_thumb(self, n, path):
        if self.stop.is_set():
            return
        try:
            im = Image.open(path)
            im.draft("RGB", (THUMB * 2, THUMB * 2))
            im.thumbnail((THUMB, THUMB))
            ph = ImageTk.PhotoImage(im)
        except Exception:
            return
        self.photos.append(ph)
        cell = ttk.Frame(self.grid_frame, padding=4)
        cols = 5
        cell.grid(row=(n - 1) // cols, column=(n - 1) % cols, sticky="n")
        tk.Label(cell, image=ph).pack()
        ttk.Label(cell, text=f"{n:03d}").pack()

    # ---------- salvataggio ----------
    def folder_name(self):
        """'sito identificativo': l'UUID nel percorso, altrimenti l'ultimo segmento significativo."""
        host = self.host or "sito"
        segs = [s for s in urlparse(self.url.get()).path.split("/") if s]
        uid = next((s for s in segs if re.fullmatch(
            r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", s, re.I)), None)
        if uid:
            return f"{host} {uid}"
        generic = {"read", "view", "index", "index.html", "page", "gallery"}
        rest = [s for s in segs if s.lower() not in generic]
        return f"{host} {rest[-1]}" if rest else host

    def save(self):
        if self.custom_on.get():
            folder = self.custom.get().strip()
            if not folder:
                messagebox.showerror("Errore", "Scegli la cartella delle immagini.")
                return
            folder = os.path.normpath(folder)
        else:
            dest = self.dest.get().strip()
            if not dest or not os.path.isdir(dest):
                messagebox.showerror("Errore", "Scegli una cartella di destinazione valida.")
                return
            folder = os.path.join(dest, re.sub(r'[<>:"/\\|?*]', "_", self.folder_name()))
        overwrite = False
        if os.path.isfile(folder) or (os.path.isdir(folder) and os.listdir(folder)):
            scelta = self.ask_conflict(folder) if self.ask_exists.get() else "salta"
            if scelta == "salta":
                self.set_status(f"Cartella già presente, salvataggio saltato: {folder}")
                messagebox.showinfo("Saltato", f"La cartella esiste già, non ho salvato nulla:\n{folder}")
                return
            if scelta == "nuova":
                base, k = folder, 2
                while os.path.exists(folder):
                    folder = f"{base}_{k}"
                    k += 1
            else:
                overwrite = True
        os.makedirs(folder, exist_ok=True)
        width = max(3, len(str(len(self.files))))
        for i, src in enumerate(self.files, 1):
            dst = os.path.join(folder, f"{i:0{width}d}.jpg")
            if overwrite and os.path.exists(dst):
                os.remove(dst)
            shutil.move(src, dst)
        n = len(self.files)
        self.files = []
        self.cleanup_tmp()
        self.btn_ok.config(state="disabled")
        self.set_status(f"Fatto: {n} immagini salvate in {folder}")
        if self.show_done(n, folder):
            self.clear()
            self.set_status(f"Fatto: {n} immagini salvate in {folder}")

    def show_done(self, n, folder):
        """Popup di fine salvataggio. Ritorna True se l'utente sceglie 'OK e pulisci'."""
        win = tk.Toplevel(self)
        win.title("Completato")
        win.transient(self)
        win.resizable(False, False)
        ttk.Label(win, text=f"{n} immagini salvate in:\n{folder}", padding=12,
                  justify="left").pack()
        res = {"clear": False}

        def pick(c):
            res["clear"] = c
            win.destroy()

        bt = ttk.Frame(win, padding=(12, 0, 12, 12))
        bt.pack()
        b_ok = ttk.Button(bt, text="OK", command=lambda: pick(False))
        b_ok.pack(side="left", padx=4)
        ttk.Button(bt, text="OK e pulisci", command=lambda: pick(True)).pack(side="left", padx=4)
        b_ok.focus_set()
        win.bind("<Return>", lambda e: pick(False))
        win.bind("<Escape>", lambda e: pick(False))
        win.protocol("WM_DELETE_WINDOW", lambda: pick(False))
        win.grab_set()
        self.wait_window(win)
        return res["clear"]


if __name__ == "__main__":
    App().mainloop()
