#!/usr/bin/env python3
import json, argparse, re
import pandas as pd

ROOM_KEYS = ["washitsu", "living", "sleeping_room"]
EVENT_KEYS = [
    "pir",
    "motion",
    "thermal",
    "sound_trig",
    "sound_amp",
    "sound",
    "presence",
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", required=True)
    ap.add_argument("--out", default="label_config_auto.json")
    args = ap.parse_args()

    df = pd.read_csv(args.csv, nrows=1, low_memory=False)
    cols = list(df.columns)

    rules = {}
    for room in ROOM_KEYS:
        any_true = []
        for c in cols:
            lc = c.lower()
            if room in lc and any(k in lc for k in EVENT_KEYS):
                any_true.append(c)
        rules[room] = {"any_true": sorted(any_true)}

    cfg = {"none_label": "unknown", "drop_if_multi_true": True, "label_rules": rules}
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    print(f"✓ wrote {args.out}")
    for r, d in rules.items():
        print(r, len(d["any_true"]), "cols")


if __name__ == "__main__":
    main()
