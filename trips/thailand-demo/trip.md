# 泰国 2 天 demo（通用性验收）

**这趟不是真行程**，是用来验证「换国家不改一行引擎代码」的最小实例。

## 基本

- id: thailand-demo
- title: 泰国 2 天 demo
- region: TH
- home_region: CN
- dates: 2027-01-10..2027-01-11
- party: 2

## 数据取样

- ebird_years: 2026
- ebird_window: 01-05..01-15
- hotspots_per_site: 2

## 类群

- taxa_primary: birds

## 机会判定阈值

- thresholds: gbif_min=20, freq_min=0.15, veto_min_days=5

## 概率模型参数

- ref_hours: 4.0
- guide_mult: 自助=1.0, 鸟导=1.35, 顶级=1.6
- mode_mult: birding=1.0, pelagic=1.0, hike=0.9, safari=0.8, night-walk=0.7, night-drive=0.7, transfer=0.3, rest=0
