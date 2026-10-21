---
description: 重建一趟行程的全部产出文档
---

重建行程：$ARGUMENTS（没给就 `ls trips/` 问用户）

```bash
python3 -I engine/build.py --trip trips/<id>
```

要重新取数（慢，会被 eBird 限流）才加 `--fetch --rate 25`。

跑完报告五份产出各自的行数，以及关键数字：总种数、特有种数、预期种数与区间。
若某一步非零退出，**明确说文档停在旧版本**，不要当作成功。
