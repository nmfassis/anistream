"""Menus: fzf when it is installed (like the yt-terminal port), plain numbered menus otherwise. No dependencies."""
import os
import shutil
import subprocess
import sys


class Quit(Exception):
    """The user asked to leave the program."""


class UI:
    def __init__(self, use_fzf=True, input_fn=input, print_fn=print, which=shutil.which, runner=subprocess.run, color=None, tty=None, debug=False):
        self.input, self.print, self.which, self.runner = input_fn, print_fn, which, runner
        self.debug = bool(debug)
        interactive = sys.stdin.isatty() and sys.stdout.isatty() if tty is None else tty
        self.use_fzf = bool(use_fzf and interactive and which("fzf"))
        self.color = (interactive and not os.environ.get("NO_COLOR")) if color is None else color

    # ------------------------------------------------------------------ output
    def _c(self, code, text):
        return f"\033[{code}m{text}\033[0m" if self.color else text

    def say(self, text=""):
        self.print(text)

    def ok(self, text):
        self.print(self._c("32", "✓ ") + text)

    def warn(self, text):
        self.print(self._c("33", "! ") + text)

    def error(self, text):
        self.print(self._c("31", "✗ ") + text)

    def dim(self, text):
        self.print(self._c("2", text))

    def log(self, text):
        """Diagnostic output is silent unless --debug is enabled."""
        if self.debug:
            self.dim(text)

    def bold(self, text):
        return self._c("1", text)

    # ------------------------------------------------------------------- input
    def ask(self, prompt, default=""):
        try:
            raw = self.input(f"{prompt}{f' [{default}]' if default else ''}: ").strip()
        except EOFError:
            raise Quit()
        return raw or default

    def confirm(self, prompt, default=False):
        hint = "[Y/n]" if default else "[y/N]"
        while True:
            try:
                raw = self.input(f"{prompt} {hint} ").strip().lower()
            except EOFError:
                raise Quit()
            if not raw:
                return default
            if raw in ("y", "yes", "s", "sim"):
                return True
            if raw in ("n", "no", "nao", "não"):
                return False

    def pick(self, title, items, default=None):
        """Index of the chosen item, or None for 'back'. Raises Quit on q."""
        if not items:
            return None
        if self.use_fzf:
            return self._pick_fzf(title, items)
        return self._pick_numbered(title, items, default)

    def _pick_fzf(self, title, items):
        data = "\n".join(f"{i}\t{label.replace(chr(10), ' ')}" for i, label in enumerate(items))
        try:
            kwargs = {"input": data, "stdout": subprocess.PIPE, "text": True}
            # fzf uses the controlling terminal for its UI; silence incidental stderr chatter.
            if not self.debug and self.runner is subprocess.run:
                kwargs["stderr"] = subprocess.DEVNULL
            p = self.runner(["fzf", "--prompt", f"{title} > ", "--layout=reverse", "--height=80%", "--delimiter", "\t",
                             "--with-nth", "2..", "--no-sort", "--tiebreak=index"], **kwargs)
        except OSError:
            self.use_fzf = False
            return self._pick_numbered(title, items, None)
        if p.returncode in (130, 1) or not (p.stdout or "").strip():       # Esc / Ctrl-C / no match
            return None
        try:
            return int(p.stdout.split("\t", 1)[0])
        except ValueError:
            return None

    def _pick_numbered(self, title, items, default):
        shown = list(range(len(items)))
        self.say(self.bold(title))
        while True:
            for i in shown:
                self.say(f" {i + 1:>3}) {items[i]}")
            try:
                raw = self.input("number, text to filter, b = back, q = quit > ").strip()
            except EOFError:
                raise Quit()
            low = raw.lower()
            if raw == "" and default is not None:
                return default
            if low in ("b", "back"):
                return None
            if low in ("q", "quit", "exit"):
                raise Quit()
            if raw.isdigit():
                n = int(raw) - 1
                if 0 <= n < len(items):
                    return n
                self.warn("No such number.")
                continue
            if raw:
                matches = [i for i, label in enumerate(items) if low in label.lower()]
                if not matches:
                    self.warn("Nothing matches; showing everything.")
                    shown = list(range(len(items)))
                elif len(matches) == 1:
                    return matches[0]
                else:
                    shown = matches
