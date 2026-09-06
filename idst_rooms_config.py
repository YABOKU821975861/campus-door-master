"""IDST 房间号到数字设备 ID 的映射。"""

IDST_DEVICE_MAP = {
    "1-408": {"id": "2007302751", "rf_id": None},
    "1-407": {"id": "2003134696", "rf_id": 15},
    "1-405": {"id": "2003432370", "rf_id": None},
    "1-406": {"id": "2000119870", "rf_id": None},
    "1-603": {"id": "2007185429", "rf_id": None},
    "1-604": {"id": "2004103660", "rf_id": 5},
}


def normalize_idst_room(room: str) -> str:
    value = room.strip().replace("栋", "-").replace("楼", "-")
    value = value.replace("室", "").replace("号", "")
    if value.isdigit():
        suffix = f"-{value}"
        for room_name in IDST_DEVICE_MAP:
            if room_name.endswith(suffix):
                return room_name
    return value


def get_idst_device_id(room: str) -> str | None:
    item = IDST_DEVICE_MAP.get(normalize_idst_room(room))
    return item["id"] if item else None


def get_idst_device(room: str) -> dict | None:
    return IDST_DEVICE_MAP.get(normalize_idst_room(room))
