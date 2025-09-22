#!/usr/bin/env python3
import sys, yaml, re
from pathlib import Path


def load_cfg(p):
    return yaml.safe_load(p.read_text(encoding="utf-8"))


def dump_cfg(p, d):
    p.write_text(yaml.safe_dump(d, sort_keys=False), encoding="utf-8")


def main():
    if len(sys.argv) < 2:
        print("Usage: manage_repos.py <add_release|add_mirror|remove> ...")
        sys.exit(1)

    action = sys.argv[1]
    cfg_path = Path("repos.yaml")
    cfg = load_cfg(cfg_path)
    sources = cfg.setdefault("sources", [])

    if action == "add_release":
        if len(sys.argv) < 5:
            print("add_release <owner/repo> <asset_glob> <only_latest:true|false>")
            sys.exit(1)
        owner_repo, glob, only_latest = (
            sys.argv[2],
            sys.argv[3],
            sys.argv[4].lower() == "true",
        )
        new = {
            "id": re.sub(r"[^a-z0-9-_]+", "-", owner_repo.split("/")[-1].lower()),
            "mode": "release_scan",
            "repo": owner_repo,
            "asset_glob": glob,
            "only_latest": only_latest,
        }
        sources.append(new)

    elif action == "add_mirror":
        if len(sys.argv) < 3:
            print("add_mirror <packages_json_url>")
            sys.exit(1)
        url = sys.argv[2]
        new = {
            "id": re.sub(r"[^a-z0-9-_]+", "-", Path(url).stem.lower()),
            "mode": "mirror_packages_json",
            "packages_url": url,
        }
        sources.append(new)

    elif action == "remove":
        if len(sys.argv) < 3:
            print("remove <id>")
            sys.exit(1)
        rid = sys.argv[2]
        sources[:] = [s for s in sources if s.get("id") != rid]

    else:
        print("Unknown action")
        sys.exit(1)

    dump_cfg(cfg_path, cfg)
    print("repos.yaml updated.")


if __name__ == "__main__":
    main()
