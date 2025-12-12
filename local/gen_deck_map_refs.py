#!/usr/bin/env python3
"""
根据 deck title 从 Supabase 读取该 deck 的所有卡片，生成引用地图册的文件（可上传到 storage）。
地图册的存储地址是<storage>:quizit_big_medias/geo_8_1/page_*.pdf, *代表页码，从1开始

环境变量（或 .env.local）：
  VITE_SUPABASE_URL
  VITE_SUPABASE_ANON_KEY
  OPENAI_API_KEY
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Optional, Dict

from openai import OpenAI, APIError

from quizit_storage import (
    load_env,
    upload_to_storage,
    fetch_cards_by_deck_title,
    find_deck_by_title,
)


def get_openai_client(env: Dict[str, str]) -> Optional[OpenAI]:
    api_key = env.get("OPENAI_API_KEY")
    if not api_key:
        print("⚠️ 未设置 OPENAI_API_KEY，将跳过在线生成", file=sys.stderr)
        return None
    return OpenAI(api_key=api_key)

SYSTEM_PROMPT = '''
你是一名初中地理教师。我将提供给你一张知识卡片的内容，你需要根据我给出的《地图册图片索引表》为该卡片挑选出相关的图片。

下面是markdown格式的《地图册图片索引表》：

| 章节标题 | 图片名称 | 页码 | 位置 |
| 第一章 从世界看中国 · 第一节 疆域 | 中国在地球上的位置示意 | 3 | 左上 |
| 第一章 从世界看中国 · 第一节 疆域 | 中国在北半球的位置示意 | 3 | 上中 |
| 第一章 从世界看中国 · 第一节 疆域 | 中国在东半球的位置示意 | 3 | 右上 |
| 第一章 从世界看中国 · 第一节 疆域 | 中国、俄罗斯、巴西纬度位置比较图 | 3 | 左下 |
| 第一章 从世界看中国 · 第一节 疆域 | 中国与哈萨克斯坦陆地位置比较图 | 3 | 下中 |
| 第一章 从世界看中国 · 第一节 疆域 | 中国疆域和邻国示意图 | 3 | 右下 |
| 第一章 从世界看中国 · 第一节 疆域 | 中国省级行政区分布示意图 | 4 | 左页全图 |
| 第一章 从世界看中国 · 第一节 疆域 | 中国各省人口柱状图 | 4 | 右侧纵向图 |
| 第一章 从世界看中国 · 第二节 人口 | 中国人口迁移流向示意图 | 5 | 左上 |
| 第一章 从世界看中国 · 第二节 人口 | 中国人口增长趋势图（1953–2022） | 5 | 右上 |
| 第一章 从世界看中国 · 第二节 人口 | 中国人口年龄结构变化图（历次普查） | 5 | 上中 |
| 第一章 从世界看中国 · 第二节 人口 | 中国县级人口密度图 | 5 | 左下 |
| 第一章 从世界看中国 · 第二节 人口 | 人口结构情景图（人口变化） | 5 | 下中 |
| 第一章 从世界看中国 · 第二节 人口 | 中国各省人口密度图 | 6 | 左上 |
| 第一章 从世界看中国 · 第二节 人口 | 中国县级人口密度点图（含胡焕庸线） | 6 | 右上 |
| 第一章 从世界看中国 · 第二节 人口 | 中国人口地理分界线示意（胡焕庸线） | 6 | 上中 |
| 第一章 从世界看中国 · 第二节 人口 | 各省城镇人口数量柱状图 | 6 | 左下 |
| 第一章 从世界看中国 · 第二节 人口 | 中国城镇化进程折线图 | 6 | 下中 |
| 第一章 从世界看中国 · 第二节 人口 | 人口分布东密西疏示意图（饼图） | 6 | 右下 |
| 第一章 从世界看中国 · 第三节 民族 | 云南主要民族分布图 | 7 | 左上 |
| 第一章 从世界看中国 · 第三节 民族 | 云南民族人口数量柱状图 | 7 | 下中 |
| 第一章 从世界看中国 · 第三节 民族 | 云南民族人口比重饼图 | 7 | 右上 |
| 第一章 从世界看中国 · 第三节 民族 | 中国少数民族人口数量排序图 | 7 | 右下 |
| 第一章 从世界看中国 · 第三节 民族 | 民族文化照片（火把节等） | 7 | 左下 |
| 第二章 中国的自然环境 · 第一节 地形 | 中国地势三级阶梯示意图 | 8 | 上中 |
| 第二章 中国的自然环境 · 第一节 地形 | 30°N 地形剖面图 | 8 | 下中 |
| 第二章 中国的自然环境 · 第一节 地形 | 中国地形图（主要山脉走向） | 9 | 全页大图 |
| 第二章 中国的自然环境 · 第二节 气候 | 中国1月平均气温分布图 | 10 | 左上 |
| 第二章 中国的自然环境 · 第二节 气候 | 中国7月平均气温分布图 | 10 | 右上 |
| 第二章 中国的自然环境 · 第二节 气候 | 三城市气温对比折线图（北京/广州/哈尔滨） | 10 | 下中 |
| 第二章 中国的自然环境 · 第二节 气候 | 中国年降水量分布图 | 11 | 左上 |
| 第二章 中国的自然环境 · 第二节 气候 | 中国干湿地区划图 | 11 | 右上 |
| 第二章 中国的自然环境 · 第二节 气候 | 典型干湿地区景观照片 | 11 | 下中 |
| 第二章 中国的自然环境 · 第二节 气候 | 中国气候类型分布图 | 12 | 左上 |
| 第二章 中国的自然环境 · 第二节 气候 | 中国温度带划分图 | 12 | 右上 |
| 第二章 中国的自然环境 · 第二节 气候 | 气候类型典型景观照片 | 12 | 下中 |
| 第二章 中国的自然环境 · 第三节 河流与湖泊 | 中国主要河流分布图 | 13 | 左上 |
| 第二章 中国的自然环境 · 第三节 河流与湖泊 | 中国主要湖泊分布图 | 13 | 右上 |
| 第二章 中国的自然环境 · 第三节 河流与湖泊 | 内流区/外流区面积比较示意 | 13 | 下中 |
| 第二章 中国的自然环境 · 第三节 河流与湖泊 | 长江流域示意图 | 14 | 左上 |
| 第二章 中国的自然环境 · 第三节 河流与湖泊 | 长江干流地形剖面图 | 14 | 上中 |
| 第二章 中国的自然环境 · 第三节 河流与湖泊 | 长江开发与治理示意图 | 14 | 下中 |
| 第二章 中国的自然环境 · 第三节 河流与湖泊 | 黄河流域分布图 | 15 | 左上 |
| 第二章 中国的自然环境 · 第三节 河流与湖泊 | 黄河干流剖面图 | 15 | 上中 |
| 第二章 中国的自然环境 · 第三节 河流与湖泊 | 黄河水资源分布图 | 15 | 右上 |
| 第二章 中国的自然环境 · 第三节 河流与湖泊 | 黄河中上游治理示意图 | 15 | 左下 |
| 第二章 中国的自然环境 · 第三节 河流与湖泊 | 黄河下游治理示意图（束水攻沙） | 15 | 下中 |
| 第二章 中国的自然环境 · 第三节 河流与湖泊 | 黄河下游历史河道变迁图 | 16 | 上中 |
| 第二章 中国的自然环境 · 第三节 河流与湖泊 | 堤防结构示意（束水攻沙） | 16 | 下中 |
| 第三章 中国的自然资源 · 土地资源 | 世界陆地面积对比图 | 17 | 左上 |
| 第三章 中国的自然资源 · 土地资源 | 世界耕地分布图 | 17 | 上中 |
| 第三章 中国的自然资源 · 土地资源 | 世界人均耕地面积比较 | 17 | 右上 |
| 第三章 中国的自然资源 · 土地资源 | 中国土地利用类型分布图 | 17 | 左下 |
| 第三章 中国的自然资源 · 土地资源 | 中国耕地与梯田分布图 | 17 | 下中 |
| 第三章 中国的自然资源 · 土地资源 | 山水林田湖草沙一体化治理示意图 | 17 | 右下 |
| 第三章 中国的自然资源 · 水资源 | 中国水资源分布图 | 18 | 左上 |
| 第三章 中国的自然资源 · 水资源 | 径流丰枯带分布图 | 18 | 右上 |
| 第三章 中国的自然资源 · 水资源 | 用水量变化折线图 | 18 | 左下 |
| 第三章 中国的自然资源 · 水资源 | 省级人均水资源与用水结构图 | 18 | 右下 |
| 第三章 中国的自然资源 · 水资源 | 生活污水处理利用示意图 | 19 | 上中 |
| 第三章 中国的自然资源 · 水资源 | 雨水收集利用示意图 | 19 | 下中 |
| 第三章 中国的自然资源 · 矿产资源 | 中国主要矿产资源分布图 | 20 | 左上 |
| 第三章 中国的自然资源 · 矿产资源 | 中国矿产储量/产量/消费量比较 | 20 | 上中 |
| 第三章 中国的自然资源 · 矿产资源 | 中国矿产进口来源分布图 | 20 | 右上 |
| 第三章 中国的自然资源 · 矿产资源 | 国家石油储备与管道分布图 | 20 | 下中 |
| 第三章 中国的自然资源 · 海洋资源 | 中国近海资源分布图 | 21 | 左上 |
| 第三章 中国的自然资源 · 海洋资源 | 台湾盐场示意图 | 21 | 左下 |
| 第三章 中国的自然资源 · 海洋资源 | 中国沿海主要港口与航线分布图 | 21 | 右上 |
| 第三章 中国的自然资源 · 海洋资源 | 海洋空间开发示意图 | 21 | 右下 |
| 跨学科主题：世界灌溉工程遗产 | 中国灌溉工程遗产分布图 | 22 | 上中 |
| 跨学科主题：世界灌溉工程遗产 | 都江堰灌区示意图 | 22 | 下中 |
| 第四章 中国的经济发展 · 农业 | 中国主要经济作物分布图 | 23 | 左上 |
| 第四章 中国的经济发展 · 农业 | 中国林区和主要牧区示意图 | 23 | 右上 |
| 第第四章 中国的经济发展 · 农业 | 农作物水热条件差异示意图 | 23 | 下中 |
| 第四章 中国的经济发展 · 农业 | 国家现代农业产业园分布图 | 24 | 左上 |
| 第四章 中国的经济发展 · 农业 | 无锡惠山区农业产业案例布局图 | 24 | 下中 |
| 第四章 中国的经济发展 · 工业 | 各省工业增加值图 | 24 | 右上 |
| 第第四章 中国的经济发展 · 工业 | 制造业创新中心分布图 | 24 | 右下 |
| 第第四章 中国的经济发展 · 工业 | 东数西算工程示意图 | 25 | 左上 |
| 第第四章 中国的经济发展 · 工业 | 清洁能源利用地图 | 25 | 上中 |
| 第第四章 中国的经济发展 · 工业 | 二氧化碳排放强度变化折线图 | 25 | 右上 |
| 第四章 中国的经济发展 · 交通运输 | 中国铁路网分布图 | 25 | 下中 |
| 第四章 中国的经济发展 · 交通运输 | 中国航空线与内河航运图 | 26 | 上中 |
| 第四章 中国的经济发展 · 交通运输 | 村庄交通路线示意图 | 26 | 左下 |
| 第四章 中国的经济发展 · 交通运输 | 国际航线与边境通道分布图 | 26 | 右下 |
| 第五章 建设美丽中国 · 自然灾害与防灾减灾 | 中国重大自然灾害分布图 | 27 | 上中 |
| 第五章 建设美丽中国 · 自然灾害与防灾减灾 | 多灾种预警系统示意图 | 27 | 下中 |
| 第五章 建设美丽中国 · 环境保护与发展 | 重点生态修复工程分布图 | 28 | 左上 |
| 第五章 建设美丽中国 · 环境保护与发展 | 森林覆盖率变化折线图 | 28 | 上中 |
| 第五章 建设美丽中国 · 环境保护与发展 | 酸雨分布与空气质量示意图 | 28 | 右上 |
| 第五章 建设美丽中国 · 环境保护与发展 | 清洁能源基地布局图 | 28 | 下中 |

---

任务要求如下：

1. 从索引表中自动选择 **1～3 张最符合卡片核心知识点** 的地图。
2. 输出格式必须是 JSON 数组。
3. 每个元素必须使用以下固定结构（map_file 固定为 "geo_8_1"）：

{
  "map_file": "geo_8_1",
  "name": "<图片名称>",
  "page": <页码数字>,
  "position": "<图片在该页的位置>"
}

4. 严格只输出 JSON，不要解释过程，不要加入多余文字。
5. 如果挑出多张图片，这些图片跟内容的相关度应基本一致，否则就只输出相关性最高的那一张图片。

'''
def generate_map_ref_prompt(card_info: str) -> str:
    return f'''
请根据下面的卡片内容，从《地图册图片索引表》挑出密切相关的图片，自动生成关联图片数组：
[卡片内容]
    {card_info}'''

def make_map_refs(
    oa_client: OpenAI,
    keyword: str,
    model: str,
) -> Optional[str]:
    if not keyword:
        return None
    try:
        resp = oa_client.responses.create(
            model=model,
            input=f"{SYSTEM_PROMPT}\n\n{generate_map_ref_prompt(keyword)}",
        )
    except APIError as e:
        print(f"⚠️ 调用 OpenAI 失败（{keyword}）: {e}", file=sys.stderr)
        return None

    text = getattr(resp, "output_text", None)
    if not text and getattr(resp, "output", None):
        try:
            for item in resp.output:
                if hasattr(item, "content"):
                    for part in item.content:
                        if getattr(part, "type", "") == "output_text":
                            text = getattr(part, "text", None)
                            if text:
                                break
                if text:
                    break
        except Exception:
            text = None
    return text


def main(argv: Optional[list[str]] = None) -> None:
    parser = argparse.ArgumentParser(description="根据 deck title 获取 deck 内的所有卡片，并生成地图册引用文件back.map存放在后端")
    parser.add_argument("--title", required=True, help="deck 的 title，需精确匹配")
    parser.add_argument("--model", default="gpt-5-mini", help="OpenAI 模型，默认 gpt-5-mini")
    args = parser.parse_args(argv)

    if "地理" not in args.title:
        print(f"❌ deck title 应包含“地理”，请确认是否输入错误：{args.title}", file=sys.stderr)
        sys.exit(1)

    env = load_env()
    oa_client = get_openai_client(env)
    cards = fetch_cards_by_deck_title(args.title)
    if not cards:
        print(f"未找到 deck 或该 deck 无卡片：{args.title}")
        sys.exit(0)
    deck = find_deck_by_title(args.title)

    cache_dir = Path("tmp/maps")
    cache_dir.mkdir(parents=True, exist_ok=True)

    ordered = []
    for card in cards:
        cid = card["id"]
        front = card.get("front")
        assert front

        print(f"processing {front} ...")
        map_path = cache_dir / f"{cid}.map"
        map_ref_text: Optional[str]
        if map_path.exists():
            map_ref_text = map_path.read_text(encoding="utf-8")
            print("found local map ref file")
        elif oa_client:
            map_ref_text = make_map_refs(
                oa_client,
                f"{front}:{card.get('back') or ''}",
                args.model,
            )
        else:
            print(f"⚠️ 未提供 OpenAI 配置且本地无 {map_path.name}，跳过 {cid}")
            map_ref_text = None
        if map_ref_text:
            if not map_path.exists():
                map_path.write_text(map_ref_text, encoding="utf-8")
            map_ref_parsed = None
            try:
                map_ref_parsed = json.loads(map_ref_text)
            except Exception:
                map_ref_parsed = None

            if isinstance(map_ref_parsed, list):
                valid_refs = []
                for idx, ref in enumerate(map_ref_parsed):
                    if not isinstance(ref, dict):
                        print(f"⚠️ map ref #{idx} 不是对象，已跳过 ({cid})")
                        continue
                    if not all(k in ref for k in ("map_file", "name", "page", "position")):
                        print(f"⚠️ map ref #{idx} 缺少字段，已跳过 ({cid})")
                        continue
                    ref_content = json.dumps(ref, ensure_ascii=False, indent=2)
                    upload_to_storage(cid, ref_content.encode("utf-8"), f"back{idx}.map")
                    valid_refs.append(ref)
                if valid_refs:
                    card = dict(card)
                    card["map"] = valid_refs
                    print(f"map refs saved to card {cid} ({len(valid_refs)} files).")
                else:
                    print(map_ref_text)
                    print(f"{front}:{card.get('back') or ''}")
                    print(f"⚠️ 未找到有效 map ref，未上传 ({cid})")
            else:
                upload_to_storage(cid, map_ref_text.encode("utf-8"), "back.map")
                print(f"map ref saved to card {cid}.")
                card = dict(card)
                card["map"] = map_ref_text
        ordered.append(card)

    print(json.dumps({
        "title": deck["title"] if deck else args.title,
        "count": len(ordered),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
