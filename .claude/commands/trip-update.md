---
description: 按一句话变更改行程配置并重建（酒店变动、行程调整、鸟导确认等）
---

变更：$ARGUMENTS

1. **定位**。判断这句话影响哪个配置文件：
   - 时间/地点/活动形式/带队 → `itinerary.md`
   - 点位坐标、eBird 热点 → `sites.md`
   - 鸟名叫法、关注科目、点名 → `targets.md`
   - 报价、汇率 → `logistics.md`
   - 待办 → `todos.md`
   - 日期、地区码、模型参数、阈值 → `trip.md`

2. **涉及鸟名就先过闸门**：
   ```bash
   python3 -I engine/materials.py --trip <trip> --resolve "名字…"
   ```

3. **展示 diff，等用户确认**。不要直接改。

4. **重建并报影响**：
   ```bash
   python3 -I engine/build.py --trip <trip>
   ```
   明确报告：预期种数变了多少、哪些时段的目标鸟变了、敏感性排序有没有变。

5. 如果这条变更有出处（邮件、确认信、网页），顺手用
   `engine/materials.py --add-text` 把它登记成材料，保留证据。
