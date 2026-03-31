#!/usr/bin/env python3

import argparse
import json
from pathlib import Path


def resolve_optional(path: str) -> str:
    if not path:
        return ""
    return str(Path(path).resolve())


def resolve_required(path: str, label: str) -> str:
    if not path:
        raise SystemExit(f"ERROR: missing required argument for {label}")
    resolved = Path(path).resolve()
    if not resolved.exists():
        raise SystemExit(f"ERROR: missing {label}: {resolved}")
    return str(resolved)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-root", default="")
    parser.add_argument("--model-name", default="M11")
    parser.add_argument("--source", default="external_m11_model")
    parser.add_argument("--model-dir", default="")
    parser.add_argument("--final-mdl", default="")
    parser.add_argument("--tree", default="")
    parser.add_argument("--phones-txt", default="")
    parser.add_argument("--mfcc-conf", default="")
    parser.add_argument("--online-conf", default="")
    parser.add_argument("--ivector-extractor-dir", default="")
    args = parser.parse_args()

    script_dir = Path(__file__).resolve().parent
    s5_root = script_dir.parent
    runtime_root = Path(args.runtime_root).resolve() if args.runtime_root else s5_root / "runtime"
    manifests_dir = runtime_root / "manifests"
    manifests_dir.mkdir(parents=True, exist_ok=True)

    model_dir = resolve_optional(args.model_dir)
    model_root = Path(model_dir) if model_dir else None

    final_mdl = resolve_required(args.final_mdl or (str(model_root / "final.mdl") if model_root else ""), "final.mdl")
    tree = resolve_required(args.tree or (str(model_root / "tree") if model_root else ""), "tree")
    phones_txt = resolve_required(args.phones_txt or (str(model_root / "phones.txt") if model_root else ""), "phones.txt")
    mfcc_conf = resolve_required(args.mfcc_conf or (str(model_root / "conf/mfcc.conf") if model_root else ""), "mfcc.conf")

    online_conf = resolve_optional(args.online_conf or (str(model_root / "conf/online.conf") if model_root else ""))
    ivector_extractor_dir = resolve_optional(
        args.ivector_extractor_dir or (str(model_root / "ivector_extractor") if model_root else "")
    )

    manifest = {
        "model_name": args.model_name,
        "source": args.source,
        "model_dir": model_dir,
        "final_mdl": final_mdl,
        "tree": tree,
        "phones_txt": phones_txt,
        "mfcc_conf": mfcc_conf,
        "online_conf": online_conf or None,
        "ivector_extractor_dir": ivector_extractor_dir or None,
        "asset_status": {
            "final_mdl": True,
            "tree": True,
            "phones_txt": True,
            "mfcc_conf": True,
            "online_conf": bool(online_conf),
            "ivector_extractor_dir": bool(ivector_extractor_dir),
        },
    }

    manifest_path = manifests_dir / "model_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")

    env_lines = [
        f'T12_MODEL_DIR="{model_dir}"',
        f'T12_FINAL_MDL="{final_mdl}"',
        f'T12_TREE="{tree}"',
        f'T12_PHONES_TXT="{phones_txt}"',
        f'T12_MFCC_CONF="{mfcc_conf}"',
        f'T12_ONLINE_CONF="{online_conf}"',
        f'T12_IVECTOR_EXTRACTOR_DIR="{ivector_extractor_dir}"',
    ]
    env_path = manifests_dir / "model_paths.env"
    env_path.write_text("\n".join(env_lines) + "\n", encoding="utf-8")

    print(json.dumps({"model_manifest": str(manifest_path), "model_env": str(env_path)}, ensure_ascii=True))


if __name__ == "__main__":
    main()
