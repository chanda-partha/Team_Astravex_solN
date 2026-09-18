"""Extract all `input` objects from the public sample pack for testing."""

import json
import sys

def main() -> None:
    src = sys.argv[1] if len(sys.argv) > 1 else "samples/BUP_CSE_FEST_2026_Preli_Public_Sample_Cases.json"
    with open(src, "r", encoding="utf-8") as f:
        data = json.load(f)
    for case in data["cases"]:
        cid = case["id"].replace("SAMPLE-", "").zfill(2)
        with open(f"samples/case_{cid}.json", "w", encoding="utf-8") as out:
            json.dump(case["input"], out, indent=2, ensure_ascii=False)
    print(f"Wrote {len(data['cases'])} case files to samples/")

if __name__ == "__main__":
    main()
