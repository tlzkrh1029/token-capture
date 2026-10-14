# -*- coding: utf-8 -*-
# 사용: 저장소 루트에서 python3 artifact/gen_boot.py [출력 경로]. 생성된 boot.js 는 커밋하지 않고 아티팩트에 index.html 과 함께 올린다.
"""data/latest.json 과 data/universe.json 에서 boot.js(BOOT, BOOT_UNI)를 만든다."""
import json, sys
latest=json.load(open('data/latest.json',encoding='utf-8'))
U=json.load(open('data/universe.json',encoding='utf-8'))
boot={"date":latest["date"],"rows":latest["rows"]}
KEEP=["t","n","sector","policy","circ","fdv","acc","auto","hist_k","hist","inc30","inc_qty30","inc_qty30_window","inc_qty30_est","inc_basis",
      "inc_method","inc_confidence","inc_ref_price","inc_ref_date","unlocks","flags","note","research_date"]
uni={"updated":U["updated"],"tokens":[{k:t[k] for k in KEEP if k in t} for t in U["tokens"]]}
js="const BOOT="+json.dumps(boot,ensure_ascii=False,separators=(',',':'))+";\nconst BOOT_UNI="+json.dumps(uni,ensure_ascii=False,separators=(',',':'))+";\n"
open(sys.argv[1] if len(sys.argv)>1 else 'artifact/boot.js','w',encoding='utf-8').write(js)
print("boot.js", len(js.encode()), "bytes; BOOT date", boot["date"], "rows", len(boot["rows"]), "; BOOT_UNI updated", uni["updated"], "tokens", len(uni["tokens"]))
