# Reverse Engineering Workbench

A local static-analysis app for understanding files without executing them.

It supports:

- Windows EXE / PE metadata, imports, sections, entropy, strings, hashes, and PyInstaller markers
- PowerShell, Python, shell, batch, JavaScript, and text-file structure summaries
- ZIP archive inventories
- decoded Base64 samples when they look text-like
- Markdown, JSON, and runnable Python behavior-scaffold exports

The generated scaffold is intentionally honest: it is not recovered original source code. It is runnable documentation of inferred behavior, useful for triage, handoff, and follow-up analysis.

## Run The GUI

```powershell
py -3 -m reverse_engineering_workbench.app
```

## Analyze From The CLI

```powershell
py -3 -m reverse_engineering_workbench.app "path\to\file.exe" -o analysis_reports
```

## Optional PE Detail

Install `pefile` for deeper PE import and section parsing:

```powershell
py -3 -m pip install pefile
```

## Safety

The analyzer does not execute target files. Use it only on files you own or are authorized to inspect.
