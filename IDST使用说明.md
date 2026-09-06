# IDST 接口使用说明

## 启动项目

```bash
cd /Users/z13/Desktop/ADO/campus_door_master
source .venv/bin/activate
python main.py
```

配置已写入 `campus-door-master.env`：

```env
IDST_BASE_URL=https://172.20.196.253
IDST_USERNAME=test906
IDST_PASSWORD=********
```

ADO 地址和账号也统一从同一个环境文件读取：

```env
ADO_BASE_URL=https://你的ADO服务器:端口
ADO_USERNAME=你的ADO账号
ADO_PASSWORD=你的ADO密码
ADO_VERIFY_SSL=false
```

服务启动后监听 `8000` 端口。IDST 的 token 和 WebSocket code 会保存在运行内存中，登录成功后每次请求自动生成新的 `Time` 和 `Sign`。

## Postman 调用

请求：

```text
POST http://127.0.0.1:8000/api/v1/idst/open
```

Headers：

```text
Content-Type: application/json
X-API-Key: storage/api_key 文件中的内容
```

Body 选择 `raw` / `JSON`。IDST 当前只支持开门，服务内部固定发送 `lock: 1`，调用方不需要填写 `lock`。

例如控制 1-604：

```json
{
  "rooms": ["604"]
}
```

`604` 会自动映射为 `1-604`，再映射为设备 ID `2004103660`，实际发送给设备的请求体是：

```json
{
  "id": "2004103660",
  "ctrl": {
    "rf_id": 5,
    "smart_entrance_guard": {"lock": 1}
  }
}
```

目前已知映射：

| 房间 | 设备 ID | rf_id |
|---|---:|---:|
| 1-408 | 2007302751 | 按设备实际配置填写 |
| 1-407 | 2003134696 | 15 |
| 1-405 | 2003432370 | 按设备实际配置填写 |
| 1-406 | 2000119870 | 按设备实际配置填写 |
| 1-603 | 2007185429 | 按设备实际配置填写 |
| 1-604 | 2004103660 | 5 |

批量调用示例（仅适用于 `rf_id` 相同的设备）：

```json
{
  "rooms": ["1-407", "1-604"]
}
```

批量请求会按设备逐个发送；已配置房间会自动使用各自的 `rf_id`。

## 直接使用设备 ID

```json
{
  "device_ids": ["2004103660"],
  "rf_id": 5
}
```

## 查看 IDST 会话状态

```text
GET http://127.0.0.1:8000/api/v1/idst/session/status
```

同样需要 `X-API-Key`。接口不会返回 token 或 code，只返回当前会话是否建立。

手动刷新会话：

```http
POST /api/v1/idst/session/refresh
```

正常情况下不需要手动调用；该接口用于排查登录、token 或 WebSocket code 问题。
