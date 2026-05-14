"""Tkinter control panel for the autonomous Builder supervisor."""

from __future__ import annotations

import argparse
import queue
import socket
import sys
import threading
import time
import webbrowser
from datetime import datetime, timezone
from pathlib import Path
from tkinter import BOTH, DISABLED, END, LEFT, NORMAL, RIGHT, VERTICAL, TclError, Text, Tk, W, X, Y, ttk
from typing import Any, Callable

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import tools.autonomous_builder_supervisor as supervisor

APP_TITLE = "Backtest Core - Superviseur Builder"
BG = "#08111f"
PANEL = "#101b2d"
PANEL_2 = "#142238"
BORDER = "#27405f"
TEXT = "#e8f1ff"
MUTED = "#93a8c2"
GREEN = "#22c55e"
RED = "#ef4444"
AMBER = "#f59e0b"
BLUE = "#60a5fa"
PANEL_LOCK_PORT = 38504


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _format_age(seconds: Any) -> str:
    if seconds is None:
        return "n/a"
    try:
        value = max(0, int(float(seconds)))
    except (TypeError, ValueError):
        return "n/a"
    if value < 60:
        return f"{value}s"
    minutes, sec = divmod(value, 60)
    if minutes < 60:
        return f"{minutes}m {sec:02d}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes:02d}m"


def _format_countdown(seconds: float) -> str:
    value = max(0, int(seconds))
    minutes, sec = divmod(value, 60)
    if minutes < 60:
        return f"{minutes:02d}:{sec:02d}"
    hours, minutes = divmod(minutes, 60)
    return f"{hours:02d}:{minutes:02d}:{sec:02d}"


def _read_tail(path: Path, lines: int = 80) -> str:
    try:
        if not path.exists():
            return ""
        raw_lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    return "\n".join(raw_lines[-lines:])


def _acquire_single_instance_lock() -> socket.socket | None:
    lock_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        lock_socket.bind(("127.0.0.1", PANEL_LOCK_PORT))
        lock_socket.listen(1)
        return lock_socket
    except OSError:
        try:
            lock_socket.close()
        except Exception:
            pass
        return None


class SupervisorPanel:
    def __init__(self, root: Tk, *, smoke_test: bool = False) -> None:
        self.root = root
        self.config = supervisor.load_config()
        self.disable_file = self._resolve_disable_file()
        self.interval_sec = max(60, int(float(self.config.get("check_interval_minutes") or 30) * 60))
        self.queue: queue.Queue[tuple[str, Any]] = queue.Queue()
        self.worker_running = False
        self.enabled = not self.disable_file.exists()
        self.next_check_at: float | None = time.time() + self.interval_sec if self.enabled else None
        self.status: dict[str, Any] = {}
        self.smoke_test = smoke_test

        self.root.title(APP_TITLE)
        self.root.geometry("980x700")
        self.root.minsize(900, 620)
        self.root.configure(bg=BG)

        self._build_styles()
        self._build_ui()
        self._set_message("Interface prete. Play active la supervision sans arreter ni forcer un run existant.")
        self._refresh_status_async()
        self.root.after(250, self._poll_worker_queue)
        self.root.after(1000, self._tick)
        if smoke_test:
            self.root.after(900, self.root.destroy)

    def _resolve_disable_file(self) -> Path:
        configured = str(self.config.get("disable_file") or "").strip()
        if configured:
            return Path(configured)
        return supervisor.builder_sessions_dir(self.config) / "supervisor.disabled"

    def _build_styles(self) -> None:
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except TclError:
            pass
        style.configure("Root.TFrame", background=BG)
        style.configure("Panel.TFrame", background=PANEL, borderwidth=1, relief="solid")
        style.configure("Card.TFrame", background=PANEL_2, borderwidth=1, relief="solid")
        style.configure("Title.TLabel", background=BG, foreground=TEXT, font=("Segoe UI", 22, "bold"))
        style.configure("Subtitle.TLabel", background=BG, foreground=MUTED, font=("Segoe UI", 10))
        style.configure("PanelTitle.TLabel", background=PANEL, foreground=TEXT, font=("Segoe UI", 12, "bold"))
        style.configure("Label.TLabel", background=PANEL_2, foreground=MUTED, font=("Segoe UI", 9))
        style.configure("Value.TLabel", background=PANEL_2, foreground=TEXT, font=("Segoe UI", 13, "bold"))
        style.configure("Muted.TLabel", background=BG, foreground=MUTED, font=("Segoe UI", 9))
        style.configure("Action.TButton", font=("Segoe UI", 11, "bold"), padding=(16, 12))
        style.configure("Ghost.TButton", font=("Segoe UI", 10), padding=(12, 9))

    def _build_ui(self) -> None:
        root_frame = ttk.Frame(self.root, style="Root.TFrame", padding=22)
        root_frame.pack(fill=BOTH, expand=True)

        header = ttk.Frame(root_frame, style="Root.TFrame")
        header.pack(fill=X)
        title_block = ttk.Frame(header, style="Root.TFrame")
        title_block.pack(side=LEFT, fill=X, expand=True)
        ttk.Label(title_block, text="Superviseur Builder autonome", style="Title.TLabel").pack(anchor=W)
        ttk.Label(
            title_block,
            text="Controle Play/Stop sans interrompre une strategie deja en cours.",
            style="Subtitle.TLabel",
        ).pack(anchor=W, pady=(4, 0))
        self.big_state = ttk.Label(header, text="", style="Title.TLabel")
        self.big_state.pack(side=RIGHT)

        actions = ttk.Frame(root_frame, style="Panel.TFrame", padding=16)
        actions.pack(fill=X, pady=(20, 14))
        self.play_button = ttk.Button(actions, text="Play - Activer la supervision", style="Action.TButton", command=self.play)
        self.play_button.pack(side=LEFT, padx=(0, 10))
        self.stop_button = ttk.Button(actions, text="Stop - Suspendre seulement la supervision", style="Action.TButton", command=self.stop)
        self.stop_button.pack(side=LEFT, padx=(0, 10))
        self.check_button = ttk.Button(actions, text="Controle maintenant", style="Ghost.TButton", command=self.check_now)
        self.check_button.pack(side=LEFT, padx=(0, 10))
        self.recover_button = ttk.Button(actions, text="Relance si panne", style="Ghost.TButton", command=self.recover_if_needed)
        self.recover_button.pack(side=LEFT, padx=(0, 10))
        ttk.Button(actions, text="Ouvrir UI", style="Ghost.TButton", command=self.open_streamlit).pack(side=RIGHT)

        self.message = ttk.Label(root_frame, text="", style="Subtitle.TLabel")
        self.message.pack(anchor=W, fill=X, pady=(0, 14))

        cards = ttk.Frame(root_frame, style="Root.TFrame")
        cards.pack(fill=X)
        self.card_vars: dict[str, tuple[ttk.Label, ttk.Label]] = {}
        for idx, key in enumerate(("supervision", "streamlit", "ollama", "builder")):
            card = ttk.Frame(cards, style="Card.TFrame", padding=14)
            card.grid(row=0, column=idx, sticky="nsew", padx=(0 if idx == 0 else 10, 0))
            cards.columnconfigure(idx, weight=1)
            label = ttk.Label(card, text=key.upper(), style="Label.TLabel")
            label.pack(anchor=W)
            value = ttk.Label(card, text="...", style="Value.TLabel")
            value.pack(anchor=W, pady=(7, 0))
            self.card_vars[key] = (label, value)

        detail = ttk.Frame(root_frame, style="Panel.TFrame", padding=16)
        detail.pack(fill=X, pady=(14, 14))
        ttk.Label(detail, text="Details runtime", style="PanelTitle.TLabel").grid(row=0, column=0, sticky=W, columnspan=4)
        self.detail_vars: dict[str, ttk.Label] = {}
        detail_items = (
            ("modele", "Modele"),
            ("heartbeat", "Dernier heartbeat"),
            ("next", "Prochaine verification"),
            ("event", "Dernier evenement"),
            ("url", "URL Streamlit"),
            ("disable", "Fichier Stop"),
        )
        for idx, (key, label_text) in enumerate(detail_items):
            row = 1 + idx // 3
            col = (idx % 3) * 2
            ttk.Label(detail, text=label_text, style="Subtitle.TLabel").grid(row=row, column=col, sticky=W, pady=(12, 0), padx=(0, 8))
            value = ttk.Label(detail, text="...", style="Subtitle.TLabel")
            value.grid(row=row, column=col + 1, sticky=W, pady=(12, 0), padx=(0, 24))
            self.detail_vars[key] = value
        for col in range(6):
            detail.columnconfigure(col, weight=1 if col % 2 else 0)

        log_frame = ttk.Frame(root_frame, style="Panel.TFrame", padding=16)
        log_frame.pack(fill=BOTH, expand=True)
        log_header = ttk.Frame(log_frame, style="Panel.TFrame")
        log_header.pack(fill=X)
        ttk.Label(log_header, text="Journal de supervision", style="PanelTitle.TLabel").pack(side=LEFT)
        ttk.Button(log_header, text="Rafraichir", style="Ghost.TButton", command=self.refresh_log).pack(side=RIGHT)

        text_frame = ttk.Frame(log_frame, style="Panel.TFrame")
        text_frame.pack(fill=BOTH, expand=True, pady=(10, 0))
        scroll = ttk.Scrollbar(text_frame, orient=VERTICAL)
        self.log_text = Text(
            text_frame,
            height=12,
            bg="#07111f",
            fg="#dbeafe",
            insertbackground=TEXT,
            relief="flat",
            wrap="word",
            font=("Cascadia Mono", 9),
        )
        self.log_text.pack(side=LEFT, fill=BOTH, expand=True)
        scroll.pack(side=RIGHT, fill=Y)
        self.log_text.configure(yscrollcommand=scroll.set)
        scroll.configure(command=self.log_text.yview)
        self.refresh_log()

    def _set_message(self, text: str) -> None:
        self.message.configure(text=text)
        self._append_local_log(text)

    def _append_local_log(self, text: str) -> None:
        stamp = datetime.now().strftime("%H:%M:%S")
        try:
            self.log_text.insert(END, f"{stamp} | UI | {text}\n")
            self.log_text.see(END)
        except Exception:
            pass

    def _set_buttons_state(self) -> None:
        state = DISABLED if self.worker_running else NORMAL
        for button in (self.play_button, self.stop_button, self.check_button, self.recover_button):
            button.configure(state=state)

    def _run_background(self, name: str, fn: Callable[[], Any]) -> None:
        if self.worker_running:
            self._set_message("Une operation est deja en cours.")
            return
        self.worker_running = True
        self._set_buttons_state()

        def _target() -> None:
            try:
                self.queue.put((name, fn()))
            except Exception as exc:
                self.queue.put((name, exc))

        threading.Thread(target=_target, daemon=True).start()

    def _refresh_status_async(self) -> None:
        self._run_background("status", lambda: supervisor.inspect_status(self.config))

    def _poll_worker_queue(self) -> None:
        try:
            while True:
                name, payload = self.queue.get_nowait()
                self.worker_running = False
                self._set_buttons_state()
                if isinstance(payload, Exception):
                    self._set_message(f"Erreur {name}: {payload}")
                elif name == "status":
                    self.status = dict(payload or {})
                    self._render_status()
                else:
                    self._set_message(str(payload or f"Operation {name} terminee."))
                    self.status = supervisor.inspect_status(self.config)
                    self._render_status()
                    self.refresh_log()
        except queue.Empty:
            pass
        self.root.after(250, self._poll_worker_queue)

    def _render_status(self) -> None:
        self.enabled = not self.disable_file.exists()
        streamlit_ok = bool(self.status.get("streamlit_healthy"))
        ollama_ok = bool(self.status.get("ollama_healthy"))
        runtime_ok = bool(self.status.get("runtime_active")) and not bool(self.status.get("runtime_manual_stop"))

        card_values = {
            "supervision": ("ACTIVE" if self.enabled else "SUSPENDUE", GREEN if self.enabled else AMBER),
            "streamlit": ("OK" if streamlit_ok else "HORS LIGNE", GREEN if streamlit_ok else RED),
            "ollama": ("OK" if ollama_ok else "HORS LIGNE", GREEN if ollama_ok else RED),
            "builder": ("RUN ACTIF" if runtime_ok else "INACTIF", GREEN if runtime_ok else AMBER),
        }
        for key, (text, color) in card_values.items():
            _label, value = self.card_vars[key]
            value.configure(text=text, foreground=color)

        self.big_state.configure(
            text="ON" if self.enabled else "OFF",
            foreground=GREEN if self.enabled else AMBER,
        )
        model_detected = bool(
            self.status.get(
                "ollama_model_detected",
                self.status.get("ollama_model_present_in_tags"),
            )
        )
        self.detail_vars["modele"].configure(
            text=(
                f"{self.status.get('ollama_model', '')} "
                f"({'detecte' if model_detected else 'non detecte'})"
            ),
        )
        self.detail_vars["heartbeat"].configure(text=_format_age(self.status.get("runtime_heartbeat_age_seconds")))
        self.detail_vars["event"].configure(text=str(self.status.get("runtime_last_event") or "n/a")[:44])
        self.detail_vars["url"].configure(text=str(self.status.get("streamlit_url") or "n/a"))
        self.detail_vars["disable"].configure(text=str(self.disable_file))
        self._update_next_check_label()

    def _update_next_check_label(self) -> None:
        if not self.enabled:
            text = "suspendue"
        elif self.next_check_at is None:
            text = "planification en attente"
        else:
            text = _format_countdown(self.next_check_at - time.time())
        self.detail_vars["next"].configure(text=text)

    def _tick(self) -> None:
        self.enabled = not self.disable_file.exists()
        if self.enabled and self.next_check_at is not None and time.time() >= self.next_check_at and not self.worker_running:
            self._run_background("periodic_check", self._periodic_check)
        self._update_next_check_label()
        self.root.after(1000, self._tick)

    def _periodic_check(self) -> str:
        supervisor.check_once(self.config)
        self.next_check_at = time.time() + self.interval_sec
        return "Verification periodique terminee."

    def play(self) -> None:
        try:
            if self.disable_file.exists():
                self.disable_file.unlink()
        except OSError as exc:
            self._set_message(f"Impossible d'activer la supervision: {exc}")
            return
        self.enabled = True
        self.next_check_at = time.time() + self.interval_sec
        self._set_message(
            "Play: supervision activee. Aucun run n'est force par ce bouton; controle automatique dans 30 min.",
        )
        self._refresh_status_async()

    def stop(self) -> None:
        try:
            self.disable_file.parent.mkdir(parents=True, exist_ok=True)
            self.disable_file.write_text(
                "Supervision suspended by Tkinter control panel.\n"
                "The active Strategy Builder runtime is intentionally left untouched.\n",
                encoding="utf-8",
            )
        except OSError as exc:
            self._set_message(f"Impossible de suspendre la supervision: {exc}")
            return
        self.enabled = False
        self.next_check_at = None
        self._set_message("Stop: supervision suspendue uniquement. La strategie en cours continue.")
        self._refresh_status_async()

    def check_now(self) -> None:
        self._set_message("Diagnostic immediat lance: lecture des statuts sans relance forcee.")
        self._refresh_status_async()

    def recover_if_needed(self) -> None:
        self._run_background("recover", self._recover_if_needed)

    def _recover_if_needed(self) -> str:
        status = supervisor.inspect_status(self.config)
        streamlit_ok = bool(status.get("streamlit_healthy"))
        ollama_ok = bool(status.get("ollama_healthy"))
        heartbeat_age = status.get("runtime_heartbeat_age_seconds")
        stale_after = float(self.config.get("stale_heartbeat_minutes") or 20) * 60.0
        runtime_stale = heartbeat_age is None or float(heartbeat_age) > stale_after
        runtime_active = bool(status.get("runtime_active"))
        if streamlit_ok and ollama_ok and runtime_active and not runtime_stale:
            return "Aucune panne detectee: aucun lancement effectue."
        supervisor.check_once(self.config)
        self.next_check_at = time.time() + self.interval_sec
        return "Procedure de relance appliquee uniquement parce qu'une panne ou un etat stale a ete detecte."

    def open_streamlit(self) -> None:
        webbrowser.open(str(self.status.get("streamlit_url") or supervisor.streamlit_url(self.config)))

    def refresh_log(self) -> None:
        path = supervisor.supervisor_log_path(self.config)
        content = _read_tail(path)
        if not content:
            content = "Aucun journal superviseur disponible pour l'instant."
        self.log_text.delete("1.0", END)
        self.log_text.insert(END, content + "\n")
        self.log_text.see(END)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Tkinter control panel for the Backtest Core Builder supervisor")
    parser.add_argument("--smoke-test", action="store_true")
    args = parser.parse_args(argv)

    lock_socket = _acquire_single_instance_lock()
    if lock_socket is None:
        print("Supervisor control panel already running.", flush=True)
        return 0
    root = Tk()
    root._supervisor_panel_lock = lock_socket  # type: ignore[attr-defined]
    SupervisorPanel(root, smoke_test=bool(args.smoke_test))
    root.mainloop()
    try:
        lock_socket.close()
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
