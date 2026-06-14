from __future__ import annotations

import argparse
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from .analyzer import analyze_file, save_report_bundle


APP_NAME = "Reverse Engineering Workbench"
APP_VERSION = "1.0.0"


class WorkbenchApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(f"{APP_NAME} {APP_VERSION}")
        self.geometry("1180x760")
        self.minsize(960, 620)

        self.selected_file = tk.StringVar()
        self.output_dir = tk.StringVar(value=str(Path.cwd() / "analysis_reports"))
        self.status = tk.StringVar(value="Ready")
        self.report = None

        self._build_ui()

    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        toolbar = ttk.Frame(self, padding=10)
        toolbar.grid(row=0, column=0, sticky="ew")
        toolbar.columnconfigure(1, weight=1)

        ttk.Button(toolbar, text="Open", command=self.pick_file).grid(row=0, column=0, padx=(0, 8))
        ttk.Entry(toolbar, textvariable=self.selected_file).grid(row=0, column=1, sticky="ew", padx=(0, 8))
        ttk.Button(toolbar, text="Analyze", command=self.analyze_selected).grid(row=0, column=2, padx=(0, 8))
        ttk.Button(toolbar, text="Save Reports", command=self.save_reports).grid(row=0, column=3)

        pane = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        pane.grid(row=1, column=0, sticky="nsew")

        left = ttk.Frame(pane, padding=10)
        left.columnconfigure(0, weight=1)
        left.rowconfigure(1, weight=1)
        pane.add(left, weight=2)

        right = ttk.Frame(pane, padding=10)
        right.columnconfigure(0, weight=1)
        right.rowconfigure(1, weight=1)
        pane.add(right, weight=3)

        ttk.Label(left, text="Summary").grid(row=0, column=0, sticky="w")
        self.summary_text = tk.Text(left, wrap="word", height=12)
        self.summary_text.grid(row=1, column=0, sticky="nsew", pady=(6, 10))

        notebook = ttk.Notebook(right)
        notebook.grid(row=0, column=0, rowspan=2, sticky="nsew")
        self.markdown_text = self._tab_text(notebook, "Report")
        self.json_text = self._tab_text(notebook, "JSON")
        self.code_text = self._tab_text(notebook, "Code Scaffold")
        self.strings_text = self._tab_text(notebook, "Strings")

        footer = ttk.Frame(self, padding=(10, 0, 10, 10))
        footer.grid(row=2, column=0, sticky="ew")
        footer.columnconfigure(1, weight=1)
        ttk.Label(footer, text="Output").grid(row=0, column=0, padx=(0, 8))
        ttk.Entry(footer, textvariable=self.output_dir).grid(row=0, column=1, sticky="ew", padx=(0, 8))
        ttk.Button(footer, text="Choose", command=self.pick_output_dir).grid(row=0, column=2, padx=(0, 8))
        ttk.Label(footer, textvariable=self.status).grid(row=0, column=3)

    def _tab_text(self, notebook: ttk.Notebook, title: str) -> tk.Text:
        frame = ttk.Frame(notebook)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)
        text = tk.Text(frame, wrap="none", undo=False)
        yscroll = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=text.yview)
        xscroll = ttk.Scrollbar(frame, orient=tk.HORIZONTAL, command=text.xview)
        text.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)
        text.grid(row=0, column=0, sticky="nsew")
        yscroll.grid(row=0, column=1, sticky="ns")
        xscroll.grid(row=1, column=0, sticky="ew")
        notebook.add(frame, text=title)
        return text

    def pick_file(self) -> None:
        path = filedialog.askopenfilename(title="Select a file to analyze")
        if path:
            self.selected_file.set(path)

    def pick_output_dir(self) -> None:
        path = filedialog.askdirectory(title="Select report output folder")
        if path:
            self.output_dir.set(path)

    def analyze_selected(self) -> None:
        path = self.selected_file.get().strip()
        if not path:
            messagebox.showwarning(APP_NAME, "Choose a file first.")
            return
        self.status.set("Analyzing...")
        self._clear_text()
        thread = threading.Thread(target=self._analyze_worker, args=(path,), daemon=True)
        thread.start()

    def _analyze_worker(self, path: str) -> None:
        try:
            report = analyze_file(path)
        except Exception as exc:
            self.after(0, lambda: self._analysis_failed(exc))
            return
        self.after(0, lambda: self._show_report(report))

    def _analysis_failed(self, exc: Exception) -> None:
        self.status.set("Failed")
        messagebox.showerror(APP_NAME, str(exc))

    def _show_report(self, report) -> None:
        self.report = report
        self.summary_text.insert("1.0", "\n".join(f"- {line}" for line in report.summary))
        self.markdown_text.insert("1.0", report.to_markdown())
        self.json_text.insert("1.0", report.to_json())
        self.code_text.insert("1.0", report.generated_code)
        self.strings_text.insert("1.0", "\n".join(report.strings))
        self.status.set("Analysis complete")

    def _clear_text(self) -> None:
        for widget in (self.summary_text, self.markdown_text, self.json_text, self.code_text, self.strings_text):
            widget.delete("1.0", tk.END)

    def save_reports(self) -> None:
        if not self.report:
            messagebox.showwarning(APP_NAME, "Analyze a file before saving reports.")
            return
        files = save_report_bundle(self.report, self.output_dir.get())
        self.status.set(f"Saved {len(files)} files")
        messagebox.showinfo(APP_NAME, "Saved:\n" + "\n".join(str(path) for path in files.values()))


def main() -> None:
    parser = argparse.ArgumentParser(description="Static reverse-engineering workbench")
    parser.add_argument("file", nargs="?", help="File to analyze without launching the GUI")
    parser.add_argument("-o", "--output", default="analysis_reports", help="Output folder for CLI reports")
    args = parser.parse_args()

    if args.file:
        report = analyze_file(args.file)
        files = save_report_bundle(report, args.output)
        print(report.to_markdown())
        print("Saved:")
        for path in files.values():
            print(f"  {path}")
        return

    WorkbenchApp().mainloop()


if __name__ == "__main__":
    main()
