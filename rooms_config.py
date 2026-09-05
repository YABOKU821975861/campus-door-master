"""
独立房间门禁映射配置
房间号 -> lock_ids UUID 列表的映射字典
支持单房间/多房间批量解析
"""

import re

# 房间号与硬件锁 UUID 的映射关系
# 格式: "房间号": ["lock_id_1", "lock_id_2", ...]
ROOM_LOCK_MAP = {
    "3-202": ["dafc56b1-470f-34ff-b37c-8642cf907929"],
    "2-202": ["b93a48c0-a2d2-3fd3-ba7a-153aa5ec256c"],
    "5-604": ["6bd0422a-bb9f-3a16-b0ae-c1f3c727e030"],
    "5-605": ["b2af497f-e3b7-3e6e-bd5d-68b26f468939"],
    "1-803": ["f5314ec6-0560-35da-a784-8eaa2742a55e"],
    "1-807": ["75b87883-3cc3-3fcc-97cc-ac5bf8c5161d"],
    "1-808": ["b3cce9b4-ddef-3839-84fe-c9842c3b3e7c"],
    "1-809": ["4f08d6f1-91a6-3fae-b2c3-f28ccfa25d36"],
    "1-810": ["51d081cf-bf2a-33fc-bb1f-8e0b601ea0f1"],
    "1-903": ["d73571fd-7957-36b3-b2dd-fae00d338655"],
    "1-904": ["a7e64909-c9f4-340a-ac9a-0e5040857fae"],
    "1-905": ["aabaeaf0-dfd5-3136-9c9a-3efecf502f89"],
    "1-906": ["ee194bc1-539a-348d-af26-c1f21b316a3a"],
    "1-907": ["b0b7ede1-6067-38c6-8a33-34712dda18bd"],
    "1-908": ["a01dbb50-1c3b-30ef-abc5-d5d448b97820"],
    "1-909": ["aac9c96e-c1c2-3c98-a59c-9ee6de67c71b"],
    "1-910": ["3c4453e7-80f3-338c-a2fc-c53feb3f01c9"],
    "1-911": ["752b7855-9171-3c83-948b-81ee1db052f5"],
}


def normalize_room_name(room_name: str) -> str:
    """
    将各种输入格式规范化为标准格式（如 "1-910"）

    支持的输入格式：
      "1-910"      → "1-910"    标准格式，原样返回
      "1栋910"     → "1-910"    中文"栋"替换为 "-"
      "1楼910"     → "1-910"    中文"楼"替换为 "-"
      "1号楼910"   → "1-910"    中文"号楼"替换为 "-"
      "1-910室"    → "1-910"    去除尾部"室"
      "1-910号"    → "1-910"    去除尾部"号"
      "1--910"     → "1-910"    去除多余连字符
      "1 — 910"    → "1-910"    去除空格和特殊连字符
      "910"        → "1-910"    仅房间号时模糊匹配（多栋时取第一个）
      " 1-910 "    → "1-910"    去除首尾空格

    Args:
        room_name: 原始输入

    Returns:
        规范化后的房间号，无法识别则返回清理后的原始输入
    """
    s = room_name.strip()

    # 去除常见后缀：室、号、房
    s = re.sub(r'[室号房]$', '', s)

    # 将中文楼栋标识替换为 "-"
    s = re.sub(r'(\d+)\s*(?:号楼|栋|楼)', r'\1-', s)

    # 将各种连字符统一为 "-"
    s = re.sub(r'(\d+)\s*[—–\-－–]+\s*(\d+)', r'\1-\2', s)

    # 如果清理后已经是 "数字-数字" 格式，直接返回
    if re.match(r'^\d+-\d+$', s):
        return s

    # 如果只有数字（如 "910"），尝试模糊匹配
    if s.isdigit():
        for key in ROOM_LOCK_MAP:
            if key.endswith(f"-{s}"):
                return key
        return room_name.strip()

    return s


def get_lock_ids_by_room(room_name: str) -> list:
    """
    根据房间号获取对应的 lock_ids UUID 列表（单房间）

    支持智能容错：自动处理 "1栋910"、"910"、"1-910室" 等各种输入格式

    Args:
        room_name: 房间号

    Returns:
        lock_ids 列表，不存在返回空列表
    """
    normalized = normalize_room_name(room_name)
    return ROOM_LOCK_MAP.get(normalized, [])


def get_lock_ids_by_rooms(room_names: list) -> list:
    """
    批量获取多个房间的 lock_ids UUID 列表（自动去重）

    示例:
        get_lock_ids_by_rooms(["910", "1-803"])
        → ["3c4453e7...", "f5314ec6..."]

    Args:
        room_names: 房间号列表

    Returns:
        去重后的 lock_ids UUID 列表
    """
    aggregated = []
    for name in room_names:
        ids = get_lock_ids_by_room(name)
        for lock_id in ids:
            if lock_id not in aggregated:
                aggregated.append(lock_id)
    return aggregated


def get_all_rooms() -> dict:
    """获取所有房间映射"""
    return ROOM_LOCK_MAP.copy()


def room_exists(room_name: str) -> bool:
    """
    检查房间是否存在（支持智能容错）

    Args:
        room_name: 房间号

    Returns:
        True 表示存在
    """
    normalized = normalize_room_name(room_name)
    return normalized in ROOM_LOCK_MAP