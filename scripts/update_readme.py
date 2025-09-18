#!/usr/bin/env python3
import json, re, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PKG_PATH = ROOT / "packages.json"
README = ROOT / "README.md"

START = "<!-- AUTO-INDEX:START -->"
END   = "<!-- AUTO-INDEX:END -->"

def load_packages():
    data = json.loads(PKG_PATH.read_text(encoding="utf-8"))
    if isinstance(data, dict) and "packages" in data:
        return data["packages"]
    return data

def pkg_display_name(pkg):
    return pkg.get("name", pkg.get("identifier", "(unknown)"))

def pkg_home_link(pkg):
    home = (pkg.get("resources") or {}).get("homepage")
    name = pkg_display_name(pkg)
    return f"[{name}]({home})" if home else name

# ---------- Maintainer helpers ----------
_URL_KEYS = ("homepage", "website", "web", "url", "github", "gitlab", "source", "repo", "repository", "twitter")

def first_url_like(d):
    if not isinstance(d, dict):
        return None
    for k in _URL_KEYS:
        v = d.get(k)
        if isinstance(v, str) and v.startswith(("http://", "https://")):
            return v
    return None

def get_maintainer(pkg):
    m = pkg.get("maintainer") or {}
    name = (m.get("name") or "").strip()
    contact = m.get("contact") or {}
    url = first_url_like(contact)
    if name:
        return f"[{name}]({url})" if url else name
    a = pkg.get("author") or {}
    aname = (a.get("name") or "").strip()
    aurl = first_url_like(a.get("contact") or {})
    if aname:
        return f"[{aname}]({aurl})" if aurl else aname
    return "-"

# ---------- License helpers ----------
def normalize_license_field(value):
    if not value:
        return None
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, dict):
        for k in ("spdx_id", "id", "name", "license", "title"):
            v = value.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip()
    if isinstance(value, (list, tuple)):
        parts = [normalize_license_field(item) for item in value if normalize_license_field(item)]
        return ", ".join(parts) if parts else None
    return None

def get_license(pkg):
    for candidate in (pkg.get("license"), pkg.get("licenses")):
        s = normalize_license_field(candidate)
        if s:
            return s
    res = pkg.get("resources") or {}
    s = normalize_license_field(res.get("license") or res.get("licenses"))
    if s:
        return s
    versions = pkg.get("versions") or []
    if versions:
        newest = versions[0]
        s = normalize_license_field(newest.get("license") or newest.get("licenses"))
        if s:
            return s
        s = normalize_license_field((newest.get("resources") or {}).get("license"))
        if s:
            return s
    return "not specified"

# ---------- Table ----------
def pkg_row(pkg):
    disp  = pkg_home_link(pkg)
    maint = get_maintainer(pkg)
    lic   = get_license(pkg)
    return f"| {disp} | {maint} | {lic} |"

def build_table(pkgs):
    if not pkgs:
        return "_No packages indexed yet._"
    header = "| 📦 Package | 👤 Maintainer | 🧾 License |\n|---|---|---|"
    rows = [pkg_row(p) for p in sorted(pkgs, key=lambda x: pkg_display_name(x).lower())]
    return "\n".join([header, *rows])

def render_block(pkgs):
    ts = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())
    count = len(pkgs)
    table = build_table(pkgs)
    preface = (
        "> ⚖️ **Licensing Note:** This index aggregates third-party KiCad packages. "
        "Please review and respect each project’s license before use or redistribution. "
        "If a license isn’t specified here, check the upstream repository."
        "While this repository itself is MIT-licensed, the packages included retain their original licenses."
    )
    return (
f"""{START}

{preface}

{table}

_Last updated: **{ts}** • Packages: **{count}**_
{END}"""
    )

# ---------- README plumbing ----------
def ensure_markers(text: str) -> str:
    if START in text and END in text:
        return text
    return text.rstrip() + "\n\n## Packages\n\n" + START + "\n" + END + "\n"

def replace_block(text: str, new_block: str) -> str:
    pattern = re.compile(re.escape(START) + r".*?" + re.escape(END), flags=re.DOTALL)
    return pattern.sub(new_block, text)

def main():
    pkgs = load_packages()
    block = render_block(pkgs)
    if README.exists():
        content = README.read_text(encoding="utf-8")
        content = ensure_markers(content)
    else:
        content = "# JAL KiCad PCM Repository\n\nThis repository hosts a custom KiCad PCM index.\n\n## Packages\n\n" + START + "\n" + END + "\n"
    updated = replace_block(content, block)
    if updated != content:
        README.write_text(updated, encoding="utf-8")
        print("README.md updated.")
    else:
        print("README.md is already up to date.")

if __name__ == "__main__":
    main()
