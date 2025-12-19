#!/usr/bin/env python3
"""
使用 Google GenAI 的 Imagen 接口根据提示词生成一张图片。

示例：
  python local/gen_image.py --subject P "a cozy reading room with green plants" reading.jpg

依赖：
  pip install google-genai

所需环境变量：
  GOOGLE_API_KEY   或在仓库根目录 .env.local 中提供同名字段
"""

import argparse
import base64
import os
import sys
from io import BytesIO
from pathlib import Path
from typing import Optional

from PIL import Image  # pillow 必须安装，否则直接抛异常

DEFAULT_MODEL = "gemini-2.5-flash-image"
# DEFAULT_MODEL = "gemini-3-pro-image-preview"

ENV_LOCAL_PATH = Path(__file__).resolve().parent / ".env.local"


def load_google_api_key() -> str:
    key = os.getenv("GOOGLE_API_KEY") or os.getenv("GOOLE_API_KEY")
    if not key and ENV_LOCAL_PATH.exists():
        for line in ENV_LOCAL_PATH.read_text().splitlines():
            stripped = line.strip()
            if stripped.startswith("GOOGLE_API_KEY=") or stripped.startswith("GOOLE_API_KEY="):
                key = stripped.split("=", 1)[1].strip().strip('"').strip("'")
                break
    if not key:
        print("❌ 请设置 GOOGLE_API_KEY 环境变量或在 .env.local 中提供。", file=sys.stderr)
        sys.exit(1)
    return key


def save_image_from_b64(data_b64: str, out_path: Path) -> None:
    raw = base64.b64decode(data_b64)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(raw)


def compress_to_jpeg(raw: bytes, target_kb: int = 50, max_dim: int = 1600) -> tuple[bytes, str]:
    """
    将图片转成 JPEG，并尝试压到目标体积附近；即便不需压缩也统一输出 JPG。
    返回 (bytes, mime)。
    """
    with BytesIO(raw) as bio:
        with Image.open(bio) as img:
            img = img.convert("RGB")
            w, h = img.size
            scale = min(1.0, max_dim / max(w, h))
            min_dim = 320  # 避免缩得过小导致严重失真
            best_bytes: Optional[bytes] = None
            best_size_kb: Optional[float] = None

            def jpeg_bytes(im, quality: int) -> bytes:
                buf = BytesIO()
                im.save(buf, format="JPEG", quality=quality, optimize=True, progressive=True)
                return buf.getvalue()

            while True:
                work = img
                if scale < 1.0:
                    work = img.resize((max(1, int(w * scale)), max(1, int(h * scale))), Image.LANCZOS)

                lo, hi = 10, 95
                local_best = None
                local_size = None
                while lo <= hi:
                    q = (lo + hi) // 2
                    data = jpeg_bytes(work, q)
                    size_kb = len(data) / 1024
                    if size_kb <= target_kb:
                        local_best = data
                        local_size = size_kb
                        hi = q - 1
                    else:
                        lo = q + 1

                if local_best:
                    best_bytes, best_size_kb = local_best, local_size
                    break

                # 如果压到最低质量仍大于目标，则继续缩尺寸
                scale *= 0.85
                if max(work.size) <= min_dim or scale <= 0.2:
                    # 兜底使用最低质量结果
                    fallback = jpeg_bytes(work, 10)
                    best_bytes, best_size_kb = fallback, len(fallback) / 1024
                    break

            if best_bytes and best_size_kb is not None:
                if best_size_kb > target_kb:
                    print(f"⚠️ 仅压到约 {best_size_kb:.1f}KB（目标 {target_kb}KB），已尽量保持清晰。", file=sys.stderr)
                return best_bytes, "image/jpeg"
    return raw, "image/jpeg"

HISTORY_PROMPT_TIP = '''
请生成一张用于中学/高中历史知识点讲解或试卷题目的黑白配图。
图片应以服务历史理解和试题情境构建为目的，构图简洁、信息指向明确，线条清晰、对比适中，在缩小为试卷或教材版面尺寸后仍保持清楚可辨。图片不追求艺术表现，避免装饰性设计。
人物、服饰、发型、器物、建筑及整体场景必须严格符合对应历史时期的真实背景，时代特征清晰，不得出现任何现代元素、跨时代物品或模糊时代的混合特征。人物身份、社会等级或职业特征应通过形象细节自然体现，但不夸张、不符号化。
背景应尽量简化或适度虚化，仅保留有助于理解历史事件、制度、社会结构或生产生活方式的必要环境信息，避免无关细节干扰学生对关键信息的判断。
若配图用于历史事件类知识点或试题情境，应表现事件发生的典型场景、关键行为或人物之间的空间关系，但不得直接呈现结论性结果或明显指向答案的细节。
若配图用于制度、社会生活、经济形态或文化现象类知识点，应通过场所布局、人物互动方式、器物特征等体现时代特征与制度内涵，而不使用文字标注、箭头或象征性符号进行解释。
若配图用于选择题、材料分析题等试卷题目，应合理控制信息密度，仅提供理解情境所需的关键线索，避免因画面过于直观而降低试题区分度。
图片整体风格应严肃、客观、规范、易识别，符合考试与教学用图标准，便于学生进行历史情境识别、比较与分析。
'''

PHYSICS_PROMPT_TIP = '''
请生成一张用于中学/高中物理知识点讲解或试卷题目的黑白配图。
图片应以服务物理概念理解、规律呈现或试题情境构建为目的，构图简洁、信息指向明确，线条清晰、比例准确，在缩小为试卷或教材版面尺寸后仍保持清楚可辨。图片不追求艺术表现，避免装饰性设计。
图中所呈现的物理对象、装置结构、空间关系和运动状态必须符合物理规律与实际条件，不得出现违背基本物理原理或引起概念混淆的设计。实验装置应结构清楚、部件位置合理，但不过度复杂。
背景应尽量简化或留白，仅保留与物理情境相关的必要环境（如水平面、支架、导轨、光路环境等），避免无关元素干扰学生对关键物理量和关系的判断。
若配图用于物理规律或实验类知识点，应清楚呈现实验情境或典型模型，突出研究对象及其相互作用关系，但不直接给出结论、不标注公式或数值结果。
若配图用于力学、电磁学、光学、热学或近代物理等概念与模型，应体现理想化条件（如光滑、轻质、匀强、电阻忽略等）但不以文字说明的方式显性标注，避免暗示解题路径。
若配图用于选择题、计算题或综合题的情境配图，应合理控制信息量，仅呈现构建物理模型所必需的条件，避免通过画面直接暴露解题方法或结论，保持试题的区分度。
图片整体风格应规范、严谨、客观、易识别，符合考试与教学用图标准，便于学生进行物理情境建模、变量分析与规律推断。
'''

BIOLOGY_PROMPT_TIP = '''
请生成一张用于中学/高中生物知识点讲解或试卷题目的黑白配图。
图片应以服务生物学概念理解、结构功能认知或试题情境构建为目的，构图简洁、信息指向明确，线条清晰、比例合理，在缩小为试卷或教材版面尺寸后仍保持清楚可辨。图片不追求艺术表现，避免装饰性设计。
图中所呈现的生物结构、器官、组织、细胞形态及其相对位置必须符合生物学事实与教材规范，不得出现结构错误、功能混淆或不符合比例关系的表现。示意图应准确反映典型特征，而非个体差异。
背景应尽量简化或留白，仅保留与生物学情境相关的必要环境或结构层次，避免无关细节干扰学生对关键结构、层级关系或功能联系的判断。
若配图用于结构与功能类知识点（如器官结构、细胞结构、生理过程），应突出关键结构及其相互关系，但不直接给出功能结论、不使用文字标注解释。
若配图用于遗传、进化、生态或调节等过程性知识点，应通过阶段性场景、结构变化或相互作用体现过程特点，但避免用箭头、编号或符号直接暗示结论。
若配图用于选择题、实验设计题或综合分析题的情境配图，应合理控制信息密度，仅呈现理解生物学情境或构建分析思路所必需的条件，避免通过画面直接暴露答案或分析路径。
图片整体风格应规范、科学、客观、易识别，符合考试与教学用图标准，便于学生进行结构识别、过程理解与科学推理。'''

PROMPT_OF_SUBJECTS = {'B': BIOLOGY_PROMPT_TIP,
                      'H': HISTORY_PROMPT_TIP,
                      'P': PHYSICS_PROMPT_TIP}

SUBJECT_KEYWORDS = {
    "B": ("生物", "biology", "bio "),
    "H": ("历史", "史纲", "history", "hist "),
    "P": ("物理", "physics", "phys "),
}

def guess_subject_from_title(title: str) -> Optional[str]:
    """
    根据 deck/quiz 的标题猜测学科，返回 'B'/'H'/'P'，无法判断则返回 None。
    支持中英文关键词匹配（不区分大小写）。
    """
    if not title:
        return None
    text = title.lower()
    for code, keywords in SUBJECT_KEYWORDS.items():
        for kw in keywords:
            if kw in title or kw.lower() in text:
                return code
    return None

def build_prompt(img_desc: str, subject: str) -> str:
    if not img_desc:
        raise ValueError("img_desc 不能为空")
    if not subject:
        raise ValueError("subject 不能为空（例如：P/H/B）")

    key = str(subject).strip()[:1].upper()
    tip = PROMPT_OF_SUBJECTS.get(key)
    if not tip:
        valid = "/".join(sorted(PROMPT_OF_SUBJECTS.keys()))
        raise ValueError(f"不支持的 subject={subject!r}，仅支持：{valid}")

    return f"{tip.strip()}\n\n图片内容如下：{img_desc}"


def generate_image_bytes(
    prompt: str,
    subject: str,
    target_kb: int = 50,
    model_name: str = DEFAULT_MODEL,
    aspect_ratio: str = "4:3",
) -> tuple[bytes, str]:
    """根据提示词生成图片并压缩到目标体积，返回 (字节流, mime_type)。"""
    try:
        from google import genai
    except ImportError as e:
        raise RuntimeError("未找到 google-genai，请先安装：pip install google-genai") from e

    api_key = load_google_api_key()
    client = genai.Client(api_key=api_key)
    prompt_bw = build_prompt(prompt, subject)

    try:
        resp = client.models.generate_content(
            model=model_name,
            contents=prompt_bw,
            config=genai.types.GenerateContentConfig(
                response_modalities=["image"],
                image_config=genai.types.ImageConfig(
                    aspect_ratio=aspect_ratio,
                ),
            ),
        )
    except Exception as e:
        raise RuntimeError(f"调用生成接口失败: {e}") from e

    raw_bytes: Optional[bytes] = None
    mime_type: str = "image/png"
    parts: list = []
    if hasattr(resp, "candidates") and resp.candidates:
        for cand in resp.candidates:
            content = getattr(cand, "content", None)
            if content and getattr(content, "parts", None):
                parts.extend(content.parts)
            finish = getattr(cand, "finish_reason", None)
            if finish and finish not in ("STOP", "MAX_TOKENS"):
                print(f"⚠️ 候选被终止，finish_reason={finish}", file=sys.stderr)
    if not parts and hasattr(resp, "parts") and getattr(resp, "parts") is not None:
        parts = list(getattr(resp, "parts"))

    for part in parts:
        inline = getattr(part, "inline_data", None)
        if inline and getattr(inline, "data", None):
            raw_bytes = inline.data
            if getattr(inline, "mime_type", None):
                mime_type = str(inline.mime_type)
            break
        data_field = getattr(part, "data", None)
        if isinstance(data_field, bytes):
            raw_bytes = data_field
            break
        if isinstance(data_field, str):
            try:
                raw_bytes = base64.b64decode(data_field)
                break
            except Exception:
                pass

    if not raw_bytes:
        raise RuntimeError("无法从响应中提取图片数据（可能被安全过滤或响应为空）。")

    compressed, mime_type = compress_to_jpeg(raw_bytes, target_kb=target_kb)
    return compressed, mime_type


def generate_image(prompt: str, subject: str, model_name: str, out_path: Path, mime_type: Optional[str]) -> None:
    try:
        raw_bytes, _mime = generate_image_bytes(prompt, subject=subject, target_kb=50, model_name=model_name)
    except RuntimeError as e:
        print(f"❌ {e}", file=sys.stderr)
        sys.exit(1)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(raw_bytes)
    print(f"✅ 已保存到 {out_path}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="调用 Google GenAI Imagen 生成一张图片")
    parser.add_argument(
        "--subject",
        required=True,
        choices=sorted(PROMPT_OF_SUBJECTS.keys()),
        help="学科：P(物理)/H(历史)/B(生物)",
    )
    parser.add_argument("desc", help="图片描述")
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help="模型名称，默认 gemini-2.5-flash-image",
    )
    parser.add_argument(
        "--target-kb",
        type=int,
        default=50,
        help="目标文件大小（KB），默认 50",
    )
    parser.add_argument(
        "out",
        type=Path,
        help="输出文件路径",
    )
    return parser


def main(argv: Optional[list[str]] = None) -> None:
    args = build_parser().parse_args(argv)

    # 复用 CLI 输出，调用接口函数生成图片
    try:
        raw, mime = generate_image_bytes(
            args.desc,
            subject=args.subject,
            target_kb=args.target_kb,
            model_name=args.model,
        )
    except RuntimeError as e:
        print(f"❌ {e}", file=sys.stderr)
        sys.exit(1)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_bytes(raw)
    print(f"✅ 已保存到 {args.out} （{mime}）")


if __name__ == "__main__":
    main()
