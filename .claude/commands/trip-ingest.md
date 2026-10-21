---
description: 投入新物料（网页/PDF/文字），抽取内容并更新行程配置
---

投入物料：$ARGUMENTS

按 `trip-planner` 技能的流程走，**严格按顺序**：

1. **收材料**。`$ARGUMENTS` 是 URL 或文件路径就用 `--add`；是一段话就用
   `--add-text` 配 `--label`：
   ```bash
   python3 -I engine/materials.py --trip <trip> --add <...>
   ```

2. **读材料**。PDF 直接用 Read 工具；网页读下载下来的 html。
   把抽取结果写进 `materials/<id>/extract.md`，**标明每条信息在原文的位置**。

3. **过闸门**。材料里出现的每个鸟名都要解析：
   ```bash
   python3 -I engine/materials.py --trip <trip> --resolve "名字…"
   ```
   解析不出的**不要猜**——列出来问用户，确认后加进 `targets.md` 的别名表。

4. **提议配置改动**。把要改的配置逐条列出来（改哪个文件、哪一行、改成什么、
   依据是材料里的哪句话），**展示 diff 并等用户确认**，确认后才落盘。

5. **重建并报变化**：
   ```bash
   python3 -I engine/build.py --trip <trip>
   ```
   报告：种数变化、预期种数变化、受影响的时段。

如果没指定行程，先 `ls trips/` 并问用户是哪一趟。
