#!/usr/bin/env python3
import hashlib, io, json, os, re, sys, time, zipfile, tarfile, urllib.request
from datetime import datetime, timezone
from pathlib import Path
import yaml

GITHUB_API = "https://api.github.com"

def log(msg: str) -> None:
    print(msg, flush=True)

# ------------------------ HTTP / GH API ------------------------

def gh_api(path, token):
    req = urllib.request.Request(f"{GITHUB_API}{path}")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", "application/vnd.github+json")
    with urllib.request.urlopen(req) as r:
        return json.load(r)

def http_get(url):
    with urllib.request.urlopen(url) as r:
        return r.read()

# ------------------------ helpers ------------------------

def sha256_bytes(b: bytes) -> str:
    h = hashlib.sha256(); h.update(b); return h.hexdigest()

def asset_download_url(owner_repo, tag, asset_name):
    owner, repo = owner_repo.split("/", 1)
    return f"https://github.com/{owner}/{repo}/releases/download/{tag}/{asset_name}"

def load_yaml(path):
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def now_utc_str():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

# --- tolerant JSON loader (no deps) ---
_comment_re = re.compile(r"""(?mx)
    (//[^\n]*$)            # // line comments
  | (/\*.*?\*/)            # /* block comments */
""")
_trailing_comma_re = re.compile(r",\s*([}\]])")  # , }

def json_loads_tolerant(s: str):
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        # strip comments and most trailing commas, then try once more
        s2 = _comment_re.sub("", s)
        s2 = _trailing_comma_re.sub(r"\1", s2)
        return json.loads(s2)

def _select_manifest_name(names):
    """Return 'manifest.json' or 'metadata.json' if present (root or 1st-level)."""
    # exact root
    for n in ("manifest.json", "metadata.json"):
        if n in names: return n
    # one top-level folder (GitHub zips often do this)
    parts = [p.split("/", 1) for p in names if "/" in p]
    toplevels = set(p[0] for p in parts)
    if len(toplevels) == 1:  # single root folder
        root = next(iter(toplevels))
        for n in ("manifest.json", "metadata.json"):
            cand = f"{root}/{n}"
            if cand in names: return cand
    return None

def read_manifest_from_archive(blob: bytes):
    """
    Try reading 'manifest.json' or 'metadata.json' from ZIP or TAR.*.
    Return (manifest_dict, filename) or (None, None).
    """
    # ZIP
    try:
        with zipfile.ZipFile(io.BytesIO(blob)) as z:
            names = z.namelist()
            target = _select_manifest_name(names)
            if target:
                try:
                    return json_loads_tolerant(z.read(target).decode("utf-8")), target
                except Exception as e:
                    log(f"      • parse error in {target}: {e}")
                    return None, None
    except zipfile.BadZipFile:
        pass

    # TAR.* (.tar.gz, .tgz, .tar.xz, etc.)
    try:
        with tarfile.open(fileobj=io.BytesIO(blob), mode="r:*") as t:
            names = [m.name for m in t.getmembers() if m.isfile()]
            target = _select_manifest_name(names)
            if target:
                try:
                    f = t.extractfile(target)
                    if not f:
                        return None, None
                    return json_loads_tolerant(f.read().decode("utf-8")), target
                except Exception as e:
                    log(f"      • parse error in {target}: {e}")
                    return None, None
    except tarfile.ReadError:
        pass

    return None, None

# ------------------------ builders ------------------------

def build_from_release_scan(src, token):
    owner_repo = src["repo"]
    glob_pat = src.get("asset_glob", "*.zip")
    only_latest = src.get("only_latest", False)
    # convert simple glob to regex (case-sensitive to match GitHub names exactly)
    rx = re.compile("^" + re.escape(glob_pat).replace(r"\*", ".*").replace(r"\?", ".") + "$")

    releases = gh_api(f"/repos/{owner_repo}/releases", token)
    releases.sort(key=lambda r: r.get("created_at",""), reverse=True)

    packages = {}
    log(f"Scanning repo {owner_repo} (only_latest={only_latest}, glob='{glob_pat}')")
    if not releases:
        log("  ↳ no releases found.")
    for rel in releases:
        tag = rel.get("tag_name")
        assets = rel.get("assets", [])
        log(f"  release {tag}: {len(assets)} asset(s)")
        matched = 0
        for a in assets:
            name = a.get("name")
            url  = a.get("browser_download_url")
            if not name or not url:
                log("    - skip: asset missing name/url")
                continue
            if not rx.match(name):
                log(f"    - skip: '{name}' (does not match glob)")
                continue
            matched += 1
            log(f"    - fetch: {name}")
            data = http_get(url)
            file_sha = sha256_bytes(data)
            file_size = len(data)

            manifest, mf_name = read_manifest_from_archive(data)
            if manifest is None or not isinstance(manifest, dict):
                log("      • skip: no usable manifest.json/metadata.json")
                continue

            pkg_id = manifest.get("identifier") or src["id"]
            pkg = packages.setdefault(pkg_id, {
                "$schema": "https://go.kicad.org/pcm/schemas/v1",
                "identifier": pkg_id,
                "name": manifest.get("name", pkg_id),
                "type": manifest.get("type", "library"),
                "description": manifest.get("description", f"{pkg_id} package"),
                # optional, if you have a longer one in your manifest:
                **({"description_full": manifest.get("description_full")} if manifest.get("description_full") else {}),
                "license": manifest.get("license", ""),
                # optional author/maintainer passthroughs if present
                **({"author": manifest["author"]} if isinstance(manifest.get("author"), dict) else {}),
                **({"maintainer": manifest["maintainer"]} if isinstance(manifest.get("maintainer"), dict) else {}),
                "resources": manifest.get("resources", {}),  # e.g. {"homepage": "..."}
                "versions": []
            })

            # ---- auto-wire local assets into resources (assets/<identifier>/...) ----
            repo_root = Path(__file__).resolve().parents[1]
            assets_dir = repo_root / "assets" / pkg_id
            if assets_dir.exists():
                pkg.setdefault("resources", {})
                icon_rel = f"{pkg_id}/icon.png"
                shot_rel = f"{pkg_id}/screenshot.png"
                if (assets_dir / "icon.png").exists() and "icon" not in pkg["resources"]:
                    pkg["resources"]["icon"] = icon_rel
                if (assets_dir / "screenshot.png").exists() and "screenshot" not in pkg["resources"]:
                    pkg["resources"]["screenshot"] = shot_rel
            # ------------------------------------------------------------------------

            version_str = (manifest.get("version") or (tag.lstrip("v") if tag else "0.0.0")).strip()
            # de-dupe versions by version string
            if any(v.get("version") == version_str for v in pkg["versions"]):
                log(f"      • note: version {version_str} already present; skipping duplicate asset")
            else:
                version_entry = {
                    "version": version_str,
                    "download_url": asset_download_url(owner_repo, tag, name),
                    "download_sha256": file_sha,
                    "download_size": file_size,
                    "status": str(manifest.get("status", "testing")),
                    "kicad_version": str(manifest.get("kicad_version", "8.0")),
                }
                # optional install size if you know it or if manifest includes it
                if manifest.get("install_size"):
                    try:
                        version_entry["install_size"] = int(manifest["install_size"])
                    except Exception:
                        pass

                pkg["versions"].append(version_entry)
                log(f"      • OK: found {mf_name}; version={version_str}")

        if matched == 0:
            log("    - note: no assets matched the glob for this release")
        if only_latest:
            break

    # sort versions newest-first (lexicographic fallback)
    for pkg in packages.values():
        pkg["versions"].sort(key=lambda v: v.get("version",""), reverse=True)

    return list(packages.values())

def build_from_mirror(src):
    data = http_get(src["packages_url"]).decode("utf-8")
    pkgs = json.loads(data)
    if isinstance(pkgs, dict):
        pkgs = pkgs.get("packages") or pkgs.get("data") or []
    return pkgs

# ------------------------ main ------------------------

def main():
    repo_root = Path(__file__).resolve().parents[1]
    cfg = load_yaml(repo_root / "repos.yaml")
    sources = cfg.get("sources", [])
    maintainer = cfg.get("maintainer", {"name": "Unknown", "contact": {}})
    repo_name = cfg.get("name", "Custom KiCad PCM Repository")

    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")

    all_packages = []
    for src in sources:
        mode = src.get("mode")
        if mode == "release_scan":
            all_packages.extend(build_from_release_scan(src, token))
        elif mode == "mirror_packages_json":
            all_packages.extend(build_from_mirror(src))
        else:
            log(f"WARNING: unknown mode for source {src.get('id')}")

    # write packages.json (KiCad expects an object with "packages": [...])
    packages_obj = {"packages": all_packages}
    packages_path = repo_root / "packages.json"
    with open(packages_path, "w", encoding="utf-8") as f:
        json.dump(packages_obj, f, indent=2, ensure_ascii=False)

    # compute sha on the exact bytes we just wrote
    pk_bytes = packages_path.read_bytes()
    pk_sha = sha256_bytes(pk_bytes)
    repo_fullname = os.environ.get('GITHUB_REPOSITORY', 'justinlevinedotme/jal-kicad-pcm')
    packages_url = f"https://raw.githubusercontent.com/{repo_fullname}/main/packages.json"

    repo_json = {
        "$schema": "https://gitlab.com/kicad/code/kicad/-/raw/master/kicad/pcm/schemas/pcm.v1.schema.json#/definitions/Repository",
        "name": repo_name,
        "maintainer": maintainer,
        "packages": {
            "url": packages_url,
            "sha256": pk_sha,
            "update_time_utc": now_utc_str(),
            "update_timestamp": int(time.time())
        }
    }

    # optional resources.zip
    res_path = repo_root / "resources.zip"
    if res_path.exists():
        res_bytes = res_path.read_bytes()
        repo_json["resources"] = {
            "url": f"https://raw.githubusercontent.com/{repo_fullname}/main/resources.zip",
            "sha256": sha256_bytes(res_bytes),
            "update_time_utc": now_utc_str(),
            "update_timestamp": int(time.time())
        }

    with open(repo_root / "repository.json", "w", encoding="utf-8") as f:
        json.dump(repo_json, f, indent=2, ensure_ascii=False)

    log(f"Wrote {len(all_packages)} package entries.")

if __name__ == "__main__":
    main()
