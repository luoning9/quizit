#!/usr/bin/env python3
"""
封装 Supabase 相关工具：环境加载、客户端创建、存储上传。
"""

import os
import sys
from pathlib import Path
from typing import Dict, Optional, List

from supabase import Client, create_client  # pip install supabase

ENV_LOCAL_PATH = Path(__file__).resolve().parent / ".env.local"
SUPABASE_BUCKET = "quizit_card_medias"


def load_env() -> Dict[str, str]:
    """读取环境变量，合并 .env.local（不覆盖已存在的环境变量）。"""
    env = dict(os.environ)
    if ENV_LOCAL_PATH.exists():
        for line in ENV_LOCAL_PATH.read_text().splitlines():
            if "=" not in line or line.strip().startswith("#"):
                continue
            k, v = line.split("=", 1)
            env.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    return env


def get_sp_client() -> Client:
    """创建 Supabase 客户端，需 VITE_SUPABASE_URL/VITE_SUPABASE_ANON_KEY。"""
    env = load_env()
    url = env.get("VITE_SUPABASE_URL")
    key = env.get("VITE_SUPABASE_ANON_KEY")
    if not url or not key:
        print("❌ 请设置 VITE_SUPABASE_URL 和 VITE_SUPABASE_ANON_KEY（环境变量或 .env.local）", file=sys.stderr)
        sys.exit(1)
    return create_client(url, key)


def upload_to_storage(
    card_id: str,
    content: bytes,
    filename: str = "card.dot",
    content_type: Optional[str] = None,
) -> Optional[str]:
    path = f"{card_id}/{filename}"
    try:
        client = get_sp_client()
        ct = content_type
        if not ct:
            ct = "text/dot" if filename.endswith(".dot") else "application/octet-stream"
        res = client.storage.from_(SUPABASE_BUCKET).upload(
            path,
            content,
            file_options={
                "content-type": ct,
                "upsert": "true",
            },
        )
        # supabase-py 返回 {'path': '...'}
        if isinstance(res, dict) and res.get("path"):
            return res["path"]
        if hasattr(res, "path"):
            return res.path  # type: ignore[attr-defined]
        return path
    except Exception as e:
        print(f"⚠️ 上传到 storage 失败 ({path}): {e}", file=sys.stderr)
        return None


def _fetch_deck_cards(card_ids: List[str]) -> list[dict]:
    """批量读取 cards（id, front, back）。"""
    if not card_ids:
        return []
    client = get_sp_client()
    res = client.table("cards").select("id, front, back").in_("id", card_ids).execute()
    return res.data or []


def find_deck_by_title(title: str) -> Optional[dict]:
    """按 title 精确匹配 deck，返回单条记录。"""
    client = get_sp_client()
    res = client.table("decks").select("id, title, items").eq("title", title).maybe_single().execute()
    data = getattr(res, "data", None)
    return data if isinstance(data, dict) else None


def find_quiz_by_name(name: str) -> Optional[dict]:
    """按 title 精确匹配 quiz_templates，返回单条记录。"""
    client = get_sp_client()
    res = client.table("quiz_templates").select("id, title, description, items").eq("title", name).maybe_single().execute()
    data = getattr(res, "data", None)
    return data if isinstance(data, dict) else None


def fetch_cards_by_deck_title(title: str) -> list[dict]:
    """
    先按 title 查 deck，再按 items 中的 card_id 顺序拉取 cards。
    返回的 cards 保持 deck.items 顺序。
    """
    deck = find_deck_by_title(title)
    if not deck:
        return []
    items = (deck.get("items") or {}).get("items") or []
    ordered = sorted(items, key=lambda it: it.get("position", 0))
    card_ids = [it.get("card_id") for it in ordered if it.get("card_id")]
    cards = _fetch_deck_cards(card_ids)
    card_map = {c["id"]: c for c in cards}
    return [card_map[cid] for cid in card_ids if cid in card_map]


def fetch_cards_by_quiz_title(title: str) -> list[dict]:
    """
    按 quiz_templates.title 精确匹配，按 items 顺序返回 cards。
    """
    quiz = find_quiz_by_name(title)
    if not quiz:
        return []
    items = (quiz.get("items") or {}).get("items") or []
    ordered = sorted(items, key=lambda it: it.get("position", 0))
    card_ids = [it.get("card_id") for it in ordered if it.get("card_id")]
    cards = _fetch_deck_cards(card_ids)
    card_map = {c["id"]: c for c in cards}
    return [card_map[cid] for cid in card_ids if cid in card_map]


__all__ = [
    "load_env",
    "get_sp_client",
    "upload_to_storage",
    "SUPABASE_BUCKET",
    "fetch_deck_cards",
    "find_deck_by_title",
    "find_quiz_by_name",
    "fetch_cards_by_deck_title",
    "fetch_cards_by_quiz_title",
]
