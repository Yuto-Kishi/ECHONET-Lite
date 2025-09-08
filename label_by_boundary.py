# label_by_boundary.py
import csv, argparse
from datetime import datetime, timedelta

FMT = "%Y-%m-%d %H:%M:%S"  # あなたのCSVのtimestamp形式

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in",  dest="inp",  required=True)
    ap.add_argument("--out", dest="outp", required=True)
    ap.add_argument("--boundary", required=True, help="YYYY-mm-dd HH:MM:SS 例: 2025-09-09 01:00:00")
    ap.add_argument("--label-before", type=int, default=0)
    ap.add_argument("--label-after",  type=int, default=1)
    ap.add_argument("--buffer-sec",   type=int, default=0, help="境界±秒を空欄に（0で無効）")
    ap.add_argument("--tz-shift-sec", type=int, default=0, help="必要なら時刻補正(秒)")
    args = ap.parse_args()

    boundary = datetime.strptime(args.boundary, FMT)
    buf = timedelta(seconds=args.buffer_sec)

    with open(args.inp, newline="") as fin:
        r = csv.DictReader(fin)
        fns = r.fieldnames[:] if r.fieldnames else []
        if "ground_truth" not in fns: fns.append("ground_truth")
        rows = []
        for row in r:
            ts = datetime.strptime(row["timestamp"], FMT) + timedelta(seconds=args.tz_shift_sec)
            if args.buffer_sec and (boundary - buf <= ts <= boundary + buf):
                row["ground_truth"] = ""          # バッファ帯は未定義
            else:
                row["ground_truth"] = str(args.label_after if ts >= boundary else args.label_before)
            rows.append(row)

    with open(args.outp, "w", newline="") as fout:
        w = csv.DictWriter(fout, fieldnames=fns)
        w.writeheader(); w.writerows(rows)
    print("✅ wrote:", args.outp)

if __name__ == "__main__":
    main()
