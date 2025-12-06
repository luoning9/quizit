#!/usr/bin/env python
"""
Vector Store CLI 工具

功能：
- 列出所有 vector store
- 查看某个 vector store 下的文件
- 创建新的 vector store
- 向指定 vector store 上传文件
- 从指定 vector store 删除文件

使用示例（假设文件名为 vs_cli.py）：

1) 列出所有 vector store：
   python vs_cli.py list-stores

2) 创建一个新的 vector store：
   python vs_cli.py create-store --name "history-kb"

3) 查看某个 vector store 下的文件：
   python vs_cli.py list-files --store-id vs_XXXXXXXX

4) 向某个 vector store 上传文件：
   python vs_cli.py upload-file --store-id vs_XXXXXXXX --file /path/to/doc.pdf

5) 从某个 vector store 删除文件：
   python vs_cli.py delete-file --store-id vs_XXXXXXXX --file-id file_YYYYYYYY
"""

import os
import sys
import argparse
from typing import Optional
from pathlib import Path

from openai import OpenAI, APIError

ENV_LOCAL_PATH = Path(__file__).resolve().parent / ".env.local"

def get_client() -> OpenAI:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key and ENV_LOCAL_PATH.exists():
        # 简单读取 .env.local 中的 OPENAI_API_KEY=... 行
        for line in ENV_LOCAL_PATH.read_text().splitlines():
            if line.strip().startswith("OPENAI_API_KEY="):
                api_key = line.split("=", 1)[1].strip().strip('"').strip("'")
                break

    if not api_key:
        print("❌ 请先设置环境变量 OPENAI_API_KEY", file=sys.stderr)
        print("   例如：export OPENAI_API_KEY='sk-xxxxxx'", file=sys.stderr)
        sys.exit(1)
    return OpenAI(api_key=api_key)


def cmd_list_stores(args: argparse.Namespace) -> None:
    client = get_client()
    try:
        stores = client.vector_stores.list(limit=args.limit)
    except APIError as e:
        print(f"❌ 调用 API 失败: {e}", file=sys.stderr)
        sys.exit(1)

    if not stores.data:
        print("（没有任何 vector store）")
        return

    print(f"共 {len(stores.data)} 个 vector store：\n")
    for s in stores.data:
        print(f"- id      : {s.id}")
        print(f"  name    : {getattr(s, 'name', '')}")
        print(f"  created : {s.created_at}")
        print(f"  usage   : {getattr(s, 'usage_bytes', 'N/A')} bytes")
        print()


def cmd_create_store(args: argparse.Namespace) -> None:
    client = get_client()
    try:
        store = client.vector_stores.create(name=args.name)
    except APIError as e:
        print(f"❌ 创建 vector store 失败: {e}", file=sys.stderr)
        sys.exit(1)

    print("✅ 创建成功：")
    print(f"  id   : {store.id}")
    print(f"  name : {store.name}")


def cmd_list_files(args: argparse.Namespace) -> None:
    client = get_client()
    try:
        files = client.vector_stores.files.list(
            vector_store_id=args.store_id,
            limit=args.limit,
        )
    except APIError as e:
        print(f"❌ 获取文件列表失败: {e}", file=sys.stderr)
        sys.exit(1)

    if not files.data:
        print(f"（vector store {args.store_id} 中没有文件）")
        return

    print(f"vector store {args.store_id} 中共有 {len(files.data)} 个文件：\n")
    for f in files.data:
        filename = ""
        byte_size = "N/A"
        try:
            meta = client.files.retrieve(f.id)
            filename = getattr(meta, "filename", "") or ""
            byte_size = getattr(meta, "bytes", "N/A")
        except APIError as e:
            filename = ""
            byte_size = "N/A"
            print(f"  ⚠️ 获取文件元信息失败 {f.id}: {e}", file=sys.stderr)

        print(f"- file_id : {f.id}")
        print(f"  name    : {filename}")
        print(f"  bytes   : {byte_size}")
        print(f"  status  : {getattr(f, 'status', 'N/A')}")
        print()


def cmd_upload_file(args: argparse.Namespace) -> None:
    client = get_client()

    path = args.file
    if not os.path.isfile(path):
        print(f"❌ 文件不存在：{path}", file=sys.stderr)
        sys.exit(1)

    # 1. 先上传文件
    try:
        print(f"📤 正在上传文件到 Files：{path}")
        uploaded = client.files.create(
            file=open(path, "rb"),
            purpose="assistants",  # 用于向量库 / 检索
        )
    except APIError as e:
        print(f"❌ 上传文件失败: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"✅ 文件上传成功，file_id = {uploaded.id}")

    # 2. 把文件加入指定 vector store
    try:
        print(f"📎 正在把文件加入 vector store {args.store_id} ...")
        client.vector_stores.files.create(
            vector_store_id=args.store_id,
            file_id=uploaded.id,
        )
    except APIError as e:
        print(f"❌ 将文件加入 vector store 失败: {e}", file=sys.stderr)
        sys.exit(1)

    print("✅ 已加入 vector store，后台会自动切片 + 向量化。")


def cmd_delete_file(args: argparse.Namespace) -> None:
    client = get_client()
    try:
        client.vector_stores.files.delete(
            vector_store_id=args.store_id,
            file_id=args.file_id,
        )
    except APIError as e:
        print(f"❌ 删除失败: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"✅ 已从 vector store {args.store_id} 删除文件 {args.file_id}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="OpenAI Vector Store 命令行管理工具",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # list-stores
    p_list_stores = subparsers.add_parser(
        "list-stores",
        help="列出所有 vector store",
    )
    p_list_stores.add_argument(
        "--limit",
        type=int,
        default=20,
        help="最多返回多少个（默认 20）",
    )
    p_list_stores.set_defaults(func=cmd_list_stores)

    # create-store
    p_create_store = subparsers.add_parser(
        "create-store",
        help="创建一个新的 vector store",
    )
    p_create_store.add_argument(
        "--name",
        required=True,
        help="vector store 名称",
    )
    p_create_store.set_defaults(func=cmd_create_store)

    # list-files
    p_list_files = subparsers.add_parser(
        "list-files",
        help="列出某个 vector store 中的文件",
    )
    p_list_files.add_argument(
        "--store-id",
        required=True,
        help="vector store 的 id",
    )
    p_list_files.add_argument(
        "--limit",
        type=int,
        default=50,
        help="最多返回多少个文件（默认 50）",
    )
    p_list_files.set_defaults(func=cmd_list_files)

    # upload-file
    p_upload = subparsers.add_parser(
        "upload-file",
        help="上传文件并加入某个 vector store",
    )
    p_upload.add_argument(
        "--store-id",
        required=True,
        help="目标 vector store id",
    )
    p_upload.add_argument(
        "--file",
        required=True,
        help="要上传的本地文件路径",
    )
    p_upload.set_defaults(func=cmd_upload_file)

    # delete-file
    p_delete = subparsers.add_parser(
        "delete-file",
        help="从 vector store 中删除一个文件",
    )
    p_delete.add_argument(
        "--store-id",
        required=True,
        help="vector store id",
    )
    p_delete.add_argument(
        "--file-id",
        required=True,
        help="要删除的 file_id",
    )
    p_delete.set_defaults(func=cmd_delete_file)

    return parser


def main(argv: Optional[list[str]] = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
