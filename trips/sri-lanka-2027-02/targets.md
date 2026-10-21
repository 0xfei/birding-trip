# 目标与别名

## 别名表

把**本项目之外的叫法**显式映射到 eBird `speciesCode`。

什么时候需要往这里加：`taxonomy.resolve()` 报「查无此名」或「名字有歧义」时。
**不要为了让脚本跑通而猜**——解析不出来就是真的对不上，
要么是叫法太老、要么是分类已拆分、要么根本是另一种鸟。

> `code` 一列必须是 eBird 的 `speciesCode`，
> 可用 `python3 -I engine/taxonomy.py "<名字>"` 查。

| 别名 | code | 为什么需要 |
|---|---|---|
| Pompadour Green Pigeon | pogpig1 | 用户与老图鉴的叫法。`Treron pompadora` 已拆分，IOC 现称 Sri Lanka Green Pigeon |
| Sri Lanka Lorikeet | cehpar1 | 老图鉴叫法，IOC/eBird 现均称 Hanging Parrot（鹦鹉而非吸蜜鹦鹉） |
| 白燕鸥 | whiter4 | 中文名有歧义：whiter3=Gygis alba（大西洋，LK 名录无）、whiter4=Gygis candida（LK 名录有）|

## 关注科目

按 eBird `familyComName` 匹配。命中的种进**「重点关注」**档。

> 迁移前这是 `build_target_list.py` 里 60 个**中文科名**的硬编码常量，
> 换个国家就全部失效——这正是原项目无法复用的根因。
> 现在按 eBird 英文科名匹配，任何国家通用。

| 科（eBird familyComName） | 为什么关注 |
|---|---|
| Owls | 夜探主目标 |
| Barn-Owls | 夜探主目标 |
| Frogmouths | 夜探主目标 |
| Nightjars and Allies | 夜探主目标 |
| Kingfishers | 热带亮丽类群 |
| Bee-eaters | 热带亮丽类群 |
| Hornbills | 热带亮丽类群 |
| Old World Parrots | 热带亮丽类群 |
| Asian Barbets | 热带亮丽类群 |
| Pittas | 热带亮丽类群 |
| Trogons | 热带亮丽类群 |
| Sunbirds and Spiderhunters | 热带亮丽类群 |
| Shearwaters and Petrels | 远洋，仅 02-11 出海窗口 |
| Northern Storm-Petrels | 远洋，仅 02-11 出海窗口 |
| Southern Storm-Petrels | 远洋，仅 02-11 出海窗口 |
| Tropicbirds | 远洋，仅 02-11 出海窗口 |
| Frigatebirds | 远洋，仅 02-11 出海窗口 |
| Boobies and Gannets | 远洋，仅 02-11 出海窗口 |
| Skuas and Jaegers | 远洋，仅 02-11 出海窗口 |

## 用户点名

参考行程或用户明确点名、但不在上述规则内的种。一律进「重点关注」档。

| 名字 | 为什么点名 |
|---|---|
| Black-backed Dwarf-Kingfisher | 三份参考行程反复点名，是本线路的招牌种之一 |
