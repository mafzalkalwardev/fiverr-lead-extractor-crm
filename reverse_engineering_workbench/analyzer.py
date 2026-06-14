from __future__ import annotations

import ast
import base64
import hashlib
import json
import math
import mimetypes
import os
import re
import stat
import string
import zipfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


TEXT_EXTENSIONS = {
    ".bat",
    ".cmd",
    ".css",
    ".csv",
    ".html",
    ".js",
    ".json",
    ".md",
    ".ps1",
    ".py",
    ".sh",
    ".ts",
    ".tsx",
    ".txt",
    ".xml",
    ".yml",
    ".yaml",
}

SCRIPT_EXTENSIONS = {
    ".bat",
    ".cmd",
    ".js",
    ".ps1",
    ".py",
    ".sh",
    ".vbs",
}

NETWORK_TERMS = [
    "http://",
    "https://",
    "socket",
    "requests",
    "Invoke-WebRequest",
    "Invoke-RestMethod",
    "Net.WebClient",
    "curl",
    "wget",
]

PERSISTENCE_TERMS = [
    "Run\\",
    "RunOnce",
    "schtasks",
    "New-Service",
    "Start-Process",
    "Startup",
    "crontab",
    "systemd",
]

EXECUTION_TERMS = [
    "eval(",
    "exec(",
    "Invoke-Expression",
    "IEX",
    "powershell -enc",
    "FromBase64String",
    "subprocess",
    "CreateProcess",
    "ShellExecute",
]

SECRET_TERMS = [
    "password",
    "passwd",
    "token",
    "api_key",
    "apikey",
    "secret",
    "private_key",
]

PE_MAGIC = b"MZ"
ELF_MAGIC = b"\x7fELF"
MACHO_MAGICS = {b"\xfe\xed\xfa\xce", b"\xfe\xed\xfa\xcf", b"\xcf\xfa\xed\xfe", b"\xca\xfe\xba\xbe"}


@dataclass
class FileIdentity:
    path: str
    name: str
    extension: str
    size_bytes: int
    modified_utc: str
    mime_guess: str
    sha256: str
    sha1: str
    md5: str
    file_type: str
    entropy: float


@dataclass
class Indicator:
    category: str
    value: str
    evidence: str
    severity: str = "info"


@dataclass
class AnalysisReport:
    identity: FileIdentity
    summary: list[str] = field(default_factory=list)
    capabilities: list[str] = field(default_factory=list)
    indicators: list[Indicator] = field(default_factory=list)
    strings: list[str] = field(default_factory=list)
    decoded_payloads: list[str] = field(default_factory=list)
    structure: dict[str, Any] = field(default_factory=dict)
    generated_code: str = ""
    limitations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["indicators"] = [asdict(indicator) for indicator in self.indicators]
        return data

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)

    def to_markdown(self) -> str:
        lines = [
            f"# Reverse-Engineering Report: {self.identity.name}",
            "",
            "## Summary",
            *[f"- {item}" for item in self.summary],
            "",
            "## Identity",
            f"- Path: `{self.identity.path}`",
            f"- Type: `{self.identity.file_type}`",
            f"- Size: `{self.identity.size_bytes}` bytes",
            f"- SHA256: `{self.identity.sha256}`",
            f"- Entropy: `{self.identity.entropy:.2f}`",
            "",
            "## Capabilities",
            *[f"- {item}" for item in (self.capabilities or ["No strong capability indicators found."])],
            "",
            "## Indicators",
        ]
        if self.indicators:
            lines.extend(
                f"- `{indicator.severity}` {indicator.category}: {indicator.value} ({indicator.evidence})"
                for indicator in self.indicators
            )
        else:
            lines.append("- No notable indicators found.")
        lines.extend(["", "## Structure", "```json", json.dumps(self.structure, indent=2), "```"])
        if self.decoded_payloads:
            lines.extend(["", "## Decoded Payload Samples"])
            lines.extend(f"```text\n{payload}\n```" for payload in self.decoded_payloads)
        lines.extend(["", "## Generated Code Scaffold", "```python", self.generated_code.rstrip(), "```"])
        if self.limitations:
            lines.extend(["", "## Limits", *[f"- {item}" for item in self.limitations]])
        return "\n".join(lines) + "\n"


def analyze_file(path: str | os.PathLike[str], max_strings: int = 250) -> AnalysisReport:
    target = Path(path).expanduser().resolve()
    if not target.exists() or not target.is_file():
        raise FileNotFoundError(f"File does not exist: {target}")

    data = target.read_bytes()
    identity = _identity(target, data)
    text = _safe_decode(data) if identity.file_type in {
        "Python source",
        "PowerShell script",
        "Text file",
        "BAT script",
        "CMD script",
        "SH script",
        "JS script",
        "VBS script",
    } else ""
    report = AnalysisReport(identity=identity)

    report.strings = _extract_strings(data, limit=max_strings)
    report.indicators.extend(_detect_common_indicators(text, report.strings))
    report.capabilities.extend(_capabilities_from_indicators(report.indicators))

    if identity.file_type == "Windows PE executable":
        _analyze_pe(target, data, report)
    elif identity.file_type == "Python source":
        _analyze_python(text, report)
    elif identity.file_type == "PowerShell script":
        _analyze_powershell(text, report)
    elif identity.file_type == "Zip archive":
        _analyze_zip(target, report)
    elif identity.file_type.endswith("script") or identity.extension in SCRIPT_EXTENSIONS:
        _analyze_script(text, report)
    elif identity.file_type == "Text file":
        _analyze_text(text, report)
    else:
        _analyze_unknown(data, report)

    report.decoded_payloads = _decode_base64_samples(text)
    report.summary = _build_summary(report)
    report.generated_code = _generate_behavior_scaffold(report)
    report.limitations.extend(_default_limitations(report))
    return report


def save_report_bundle(report: AnalysisReport, output_dir: str | os.PathLike[str]) -> dict[str, Path]:
    output = Path(output_dir).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "_", report.identity.name).strip("_") or "analysis"
    files = {
        "markdown": output / f"{slug}.report.md",
        "json": output / f"{slug}.report.json",
        "scaffold": output / f"{slug}.scaffold.py",
    }
    files["markdown"].write_text(report.to_markdown(), encoding="utf-8")
    files["json"].write_text(report.to_json(), encoding="utf-8")
    files["scaffold"].write_text(report.generated_code, encoding="utf-8")
    return files


def _identity(path: Path, data: bytes) -> FileIdentity:
    digest_sha256 = hashlib.sha256(data).hexdigest()
    digest_sha1 = hashlib.sha1(data).hexdigest()
    digest_md5 = hashlib.md5(data).hexdigest()
    extension = path.suffix.lower()
    mime_guess = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    modified = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat()
    return FileIdentity(
        path=str(path),
        name=path.name,
        extension=extension,
        size_bytes=len(data),
        modified_utc=modified,
        mime_guess=mime_guess,
        sha256=digest_sha256,
        sha1=digest_sha1,
        md5=digest_md5,
        file_type=_classify(path, data),
        entropy=_entropy(data),
    )


def _classify(path: Path, data: bytes) -> str:
    extension = path.suffix.lower()
    if data.startswith(PE_MAGIC):
        return "Windows PE executable"
    if data.startswith(ELF_MAGIC):
        return "ELF executable"
    if data[:4] in MACHO_MAGICS:
        return "Mach-O executable"
    if zipfile.is_zipfile(path):
        return "Zip archive"
    if extension == ".py":
        return "Python source"
    if extension == ".ps1":
        return "PowerShell script"
    if extension in {".bat", ".cmd", ".sh", ".js", ".vbs"}:
        return f"{extension[1:].upper()} script"
    if extension in TEXT_EXTENSIONS or _looks_text(data):
        return "Text file"
    return "Binary file"


def _safe_decode(data: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-16", "utf-16-le", "cp1252"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="ignore")


def _looks_text(data: bytes) -> bool:
    if not data:
        return True
    sample = data[:4096]
    allowed = bytes(string.printable, "ascii") + b"\x00"
    printable = sum(byte in allowed for byte in sample)
    return printable / len(sample) > 0.85


def _entropy(data: bytes) -> float:
    if not data:
        return 0.0
    counts = [0] * 256
    for byte in data:
        counts[byte] += 1
    total = len(data)
    return -sum((count / total) * math.log2(count / total) for count in counts if count)


def _extract_strings(data: bytes, limit: int = 250, min_length: int = 5) -> list[str]:
    ascii_re = re.compile(rb"[\x20-\x7e]{%d,}" % min_length)
    utf16_re = re.compile((rb"(?:[\x20-\x7e]\x00){%d,}" % min_length))
    unique: list[str] = []
    seen = set()

    def add_value(value: str) -> None:
        cleaned = value.strip()
        if cleaned and cleaned not in seen and len(unique) < limit:
            unique.append(cleaned[:500])
            seen.add(cleaned)

    priority = []
    for pattern in (rb"https?://[^\s'\"<>]+", rb"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"):
        for match in re.finditer(pattern, data):
            priority.append(match.group(0).decode("ascii", errors="ignore"))
            if len(priority) >= max(40, limit // 3):
                break

    for value in priority:
        add_value(value)
    for match in ascii_re.finditer(data):
        add_value(match.group(0).decode("ascii", errors="ignore"))
        if len(unique) >= limit:
            return unique
    for match in utf16_re.finditer(data):
        add_value(match.group(0).decode("utf-16-le", errors="ignore"))
        if len(unique) >= limit:
            return unique
    return unique


def _detect_common_indicators(text: str, strings_found: list[str]) -> list[Indicator]:
    haystack = "\n".join([text, *strings_found])
    indicators: list[Indicator] = []
    for url in sorted(set(re.findall(r"https?://[^\s'\"<>]+", haystack))):
        indicators.append(Indicator("network", url[:240], "URL string", "medium"))
    for email in sorted(set(re.findall(r"[\w.+-]{2,}@[A-Za-z0-9-]{2,}(?:\.[A-Za-z0-9-]{2,})+", haystack))):
        if re.search(r"(?i)@2x\.|@3x\.|\.(png|jpg|jpeg|gif|svg|webp)$", email):
            continue
        indicators.append(Indicator("identity", email[:160], "Email-like string"))
    for term in NETWORK_TERMS:
        if term.lower() in haystack.lower():
            indicators.append(Indicator("network", term, "Network API or command", "medium"))
    for term in PERSISTENCE_TERMS:
        if term.lower() in haystack.lower():
            indicators.append(Indicator("persistence", term, "Persistence-related string", "high"))
    for term in EXECUTION_TERMS:
        if term.lower() in haystack.lower():
            indicators.append(Indicator("execution", term, "Dynamic execution indicator", "high"))
    for term in SECRET_TERMS:
        if term.lower() in haystack.lower():
            indicators.append(Indicator("credential", term, "Credential-like keyword", "medium"))
    return _dedupe_indicators(indicators)


def _dedupe_indicators(indicators: list[Indicator]) -> list[Indicator]:
    result = []
    seen = set()
    for indicator in indicators:
        key = (indicator.category, indicator.value.lower(), indicator.evidence)
        if key not in seen:
            result.append(indicator)
            seen.add(key)
    return result


def _capabilities_from_indicators(indicators: list[Indicator]) -> list[str]:
    categories = {indicator.category for indicator in indicators}
    capabilities = []
    if "network" in categories:
        capabilities.append("Network communication or web access")
    if "persistence" in categories:
        capabilities.append("Startup, scheduled task, or service persistence behavior")
    if "execution" in categories:
        capabilities.append("Dynamic code execution or child process launch")
    if "credential" in categories:
        capabilities.append("Possible credential, token, or secret handling")
    return capabilities


def _analyze_pe(path: Path, data: bytes, report: AnalysisReport) -> None:
    structure: dict[str, Any] = {
        "format": "PE",
        "pyinstaller": b"PyInstaller" in data or b"pyi-windows-manifest-filename" in data,
        "overlay_bytes": None,
        "sections": [],
        "imports": [],
    }
    try:
        import pefile  # type: ignore

        pe = pefile.PE(str(path), fast_load=False)
        structure["machine"] = hex(pe.FILE_HEADER.Machine)
        structure["timestamp"] = pe.FILE_HEADER.TimeDateStamp
        structure["entry_point"] = hex(pe.OPTIONAL_HEADER.AddressOfEntryPoint)
        structure["image_base"] = hex(pe.OPTIONAL_HEADER.ImageBase)
        for section in pe.sections:
            structure["sections"].append(
                {
                    "name": section.Name.rstrip(b"\x00").decode("ascii", errors="ignore"),
                    "virtual_address": hex(section.VirtualAddress),
                    "virtual_size": section.Misc_VirtualSize,
                    "raw_size": section.SizeOfRawData,
                    "entropy": round(section.get_entropy(), 2),
                }
            )
        if hasattr(pe, "DIRECTORY_ENTRY_IMPORT"):
            for entry in pe.DIRECTORY_ENTRY_IMPORT:
                structure["imports"].append(
                    {
                        "dll": entry.dll.decode("ascii", errors="ignore"),
                        "symbols": [
                            imported.name.decode("ascii", errors="ignore") if imported.name else f"ord_{imported.ordinal}"
                            for imported in entry.imports[:80]
                        ],
                    }
                )
        overlay = pe.get_overlay()
        structure["overlay_bytes"] = len(overlay) if overlay else 0
    except Exception as exc:
        structure["pe_parse_error"] = str(exc)
        report.limitations.append("Install `pefile` for deeper PE section and import parsing.")

    if structure["pyinstaller"]:
        report.capabilities.append("Likely PyInstaller-packaged Python application")
        report.indicators.append(Indicator("packaging", "PyInstaller", "PyInstaller bootloader strings", "medium"))
    high_entropy = [section for section in structure["sections"] if section.get("entropy", 0) >= 7.2]
    if high_entropy:
        report.indicators.append(Indicator("packing", "High-entropy PE section", "Packed or compressed section", "medium"))
    report.structure.update(structure)


def _analyze_python(text: str, report: AnalysisReport) -> None:
    structure: dict[str, Any] = {"language": "Python", "imports": [], "functions": [], "classes": []}
    try:
        tree = ast.parse(text)
    except SyntaxError as exc:
        report.structure["syntax_error"] = str(exc)
        _analyze_script(text, report)
        return
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            structure["imports"].extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            structure["imports"].extend(f"{module}.{alias.name}" for alias in node.names)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            structure["functions"].append({"name": node.name, "line": node.lineno, "args": [arg.arg for arg in node.args.args]})
        elif isinstance(node, ast.ClassDef):
            structure["classes"].append({"name": node.name, "line": node.lineno})
    report.structure.update(structure)


def _analyze_powershell(text: str, report: AnalysisReport) -> None:
    functions = re.findall(r"(?im)^\s*function\s+([A-Za-z0-9_-]+)", text)
    params = re.findall(r"(?im)^\s*param\s*\((.*?)\)", text, flags=re.DOTALL)
    cmdlets = sorted(set(re.findall(r"\b[A-Z][A-Za-z]+-[A-Za-z]+\b", text)))
    report.structure.update(
        {
            "language": "PowerShell",
            "functions": functions,
            "param_blocks": [param.strip()[:500] for param in params[:10]],
            "cmdlets": cmdlets[:120],
            "line_count": len(text.splitlines()),
        }
    )
    if re.search(r"(?i)FromBase64String|EncodedCommand|\s-enc\s", text):
        report.indicators.append(Indicator("obfuscation", "Base64 or encoded command", "PowerShell encoded execution", "high"))


def _analyze_script(text: str, report: AnalysisReport) -> None:
    report.structure.update(
        {
            "line_count": len(text.splitlines()),
            "non_empty_lines": sum(1 for line in text.splitlines() if line.strip()),
            "comments": sum(1 for line in text.splitlines() if line.strip().startswith(("#", "//", "::", "REM "))),
        }
    )


def _analyze_text(text: str, report: AnalysisReport) -> None:
    report.structure.update(
        {
            "line_count": len(text.splitlines()),
            "characters": len(text),
            "preview": text[:1200],
        }
    )


def _analyze_zip(path: Path, report: AnalysisReport) -> None:
    entries = []
    with zipfile.ZipFile(path) as archive:
        for info in archive.infolist()[:500]:
            mode = info.external_attr >> 16
            entries.append(
                {
                    "name": info.filename,
                    "size": info.file_size,
                    "compressed_size": info.compress_size,
                    "is_executable": bool(mode and mode & stat.S_IXUSR),
                }
            )
    report.structure.update({"format": "zip", "entries": entries, "entry_count": len(entries)})


def _analyze_unknown(data: bytes, report: AnalysisReport) -> None:
    report.structure.update(
        {
            "byte_count": len(data),
            "magic_hex": data[:16].hex(),
            "printable_string_count": len(report.strings),
        }
    )


def _decode_base64_samples(text: str, limit: int = 8) -> list[str]:
    samples = []
    candidates = re.findall(r"(?:[A-Za-z0-9+/]{40,}={0,2})", text)
    for candidate in candidates:
        try:
            decoded = base64.b64decode(candidate, validate=True)
        except Exception:
            continue
        if not decoded:
            continue
        decoded_text = _safe_decode(decoded).strip()
        if decoded_text and _looks_text(decoded):
            samples.append(decoded_text[:1000])
        if len(samples) >= limit:
            break
    return samples


def _build_summary(report: AnalysisReport) -> list[str]:
    identity = report.identity
    lines = [
        f"{identity.name} is classified as {identity.file_type}.",
        f"It is {identity.size_bytes:,} bytes with SHA256 {identity.sha256[:16]}...",
    ]
    if identity.entropy >= 7.2:
        lines.append("Overall entropy is high, which can mean compression, packing, or encrypted data.")
    if report.capabilities:
        lines.append("Observed capabilities: " + ", ".join(sorted(set(report.capabilities))) + ".")
    if report.structure.get("pyinstaller"):
        lines.append("The executable contains PyInstaller markers, so original Python modules may exist inside the bundle.")
    if report.decoded_payloads:
        lines.append("Base64-like payloads were decoded for review.")
    if not report.indicators:
        lines.append("No strong risk indicators were found in the static pass.")
    return lines


def _generate_behavior_scaffold(report: AnalysisReport) -> str:
    capabilities = sorted(set(report.capabilities)) or ["No strong behavior identified"]
    indicators = report.indicators[:25]
    structure = report.structure
    lines = [
        '"""',
        f"Behavior scaffold for {report.identity.name}.",
        "",
        "This is not recovered original source. It is a runnable static-analysis scaffold",
        "that documents the behavior inferred from metadata, strings, and parsed structure.",
        '"""',
        "",
        "from __future__ import annotations",
        "",
        "",
        "def summarize_behavior() -> dict:",
        "    return {",
        f"        'file_name': {report.identity.name!r},",
        f"        'file_type': {report.identity.file_type!r},",
        f"        'sha256': {report.identity.sha256!r},",
        f"        'capabilities': {capabilities!r},",
        "        'indicators': [",
    ]
    for indicator in indicators:
        lines.append(
            "            "
            + repr(
                {
                    "category": indicator.category,
                    "value": indicator.value,
                    "evidence": indicator.evidence,
                    "severity": indicator.severity,
                }
            )
            + ","
        )
    lines.extend(
        [
            "        ],",
            f"        'structure': {structure!r},",
            "    }",
            "",
            "",
            "def main() -> None:",
            "    import json",
            "",
            "    print(json.dumps(summarize_behavior(), indent=2))",
            "",
            "",
            "if __name__ == '__main__':",
            "    main()",
            "",
        ]
    )
    return "\n".join(lines)


def _default_limitations(report: AnalysisReport) -> list[str]:
    limits = [
        "The analyzer never executes the target file.",
        "Native binaries cannot be perfectly converted back to original source code.",
        "Generated code is a behavior scaffold, not a decompiler output.",
    ]
    if report.identity.file_type == "Windows PE executable":
        limits.append("Use a dedicated disassembler/decompiler such as Ghidra for full control-flow recovery.")
    return limits
