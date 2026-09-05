# Campus Door Master API 接口文档

## 1. 基础信息

服务默认地址：

```text
http://127.0.0.1:8000
```

Swagger 在线文档：

```text
http://127.0.0.1:8000/docs
```

所有接口均使用 JSON；除健康检查外，业务接口都需要 API Key。

## 2. API 鉴权

请求头：

```http
X-API-Key: API_KEY
```

API Key 文件位置：

```text
storage/api_key
```

Linux/macOS 查看：

```bash
cat storage/api_key
```

Windows 查看：

```powershell
type storage\api_key
```

如果没有配置 `ADO_API_KEY`，服务首次启动时会自动生成 API Key，并在后续重启中保持不变。

## 3. 接口体系说明

项目包含两套完全独立的上游系统：

| 接口前缀 | 系统 | 功能 |
|---|---|---|
| `/api/v1/doors/*` | 原 ADO 门禁 | 开门、落锁 |
| `/api/v1/idst/*` | IDST 设备 | RF 设备开门 |

注意：`1-906` 属于原 ADO 门禁映射，不属于 IDST 映射。

## 4. 健康检查

### GET `/health`

不需要 API Key。

请求：

```bash
curl http://127.0.0.1:8000/health
```

响应：

```json
{
  "status": "ok",
  "service": "Campus Door Master",
  "version": "1.0.0",
  "token_valid": true,
  "cache_age_seconds": 12.5
}
```

## 5. 原 ADO 门禁接口

### POST `/api/v1/doors/open`

原 ADO 门禁开门，支持按房间号或直接传门锁 UUID。

#### 按房间号开门

```json
{
  "rooms": ["1-906"],
  "reason": "测试"
}
```

说明：`1-906` 使用原 ADO 的 `rooms_config.py` 映射。

#### 按门锁 ID 开门

```json
{
  "lock_ids": ["门锁UUID"],
  "reason": "测试"
}
```

#### curl 示例

```bash
curl -X POST http://127.0.0.1:8000/api/v1/doors/open \
  -H "Content-Type: application/json" \
  -H "X-API-Key: API_KEY" \
  -d '{
    "rooms": ["1-906"],
    "reason": "测试"
  }'
```

#### 成功响应

```json
{
  "code": 200,
  "message": "开门成功",
  "detail": {},
  "executed_locks_count": 1
}
```

### POST `/api/v1/doors/close`

原 ADO 门禁落锁。

请求体与 `/api/v1/doors/open` 相同：

```json
{
  "rooms": ["1-906"],
  "reason": "测试落锁"
}
```

#### curl 示例

```bash
curl -X POST http://127.0.0.1:8000/api/v1/doors/close \
  -H "Content-Type: application/json" \
  -H "X-API-Key: API_KEY" \
  -d '{
    "rooms": ["1-906"],
    "reason": "测试落锁"
  }'
```

### POST `/api/v1/token/refresh`

强制刷新原 ADO token。

```bash
curl -X POST http://127.0.0.1:8000/api/v1/token/refresh \
  -H "X-API-Key: API_KEY"
```

响应：

```json
{
  "code": 200,
  "message": "Token 刷新成功",
  "token": null,
  "cache_age_seconds": 0
}
```

完整 token 不会通过 API 返回。

### GET `/api/v1/token/status`

查询原 ADO token 状态。

```bash
curl http://127.0.0.1:8000/api/v1/token/status \
  -H "X-API-Key: API_KEY"
```

响应示例：

```json
{
  "code": 200,
  "message": "Token 缓存有效",
  "token": "前20位...",
  "cache_age_seconds": 42.3
}
```

## 6. IDST 开门接口

IDST 当前只提供开门业务，不提供锁门接口。

服务内部自动完成：

```text
获取验证码
→ 登录获取 IDST token
→ WebSocket /wss/ 获取 code
→ 生成当前 Time
→ Sign = MD5(token + Time + code)
→ POST /api2/device/rf-ctrl
```

IDST 业务接口固定发送：

```text
lock = 1
```

`rf_id` 根据房间映射自动选择：

```text
1-405、1-406、1-407、1-408 → rf_id=15
1-603、1-604              → rf_id=5
```

### POST `/api/v1/idst/open`

推荐使用的 IDST 开门接口。

#### 按房间号开门

```json
{
  "rooms": ["1-604"],
  "reason": "测试"
}
```

也支持简写：

```json
{
  "rooms": ["604"],
  "reason": "测试"
}
```

#### 批量开门

```json
{
  "rooms": ["1-405", "1-604"],
  "reason": "批量测试"
}
```

#### 按设备 ID 开门

```json
{
  "device_ids": ["2004103660"],
  "reason": "测试"
}
```

直接传 `device_ids` 时，服务默认使用 `rf_id=5`。

#### curl 示例

```bash
curl -X POST http://127.0.0.1:8000/api/v1/idst/open \
  -H "Content-Type: application/json" \
  -H "X-API-Key: API_KEY" \
  -d '{
    "rooms": ["604"],
    "reason": "测试"
  }'
```

#### 成功响应

```json
{
  "code": 200,
  "message": "操作成功",
  "results": [
    {
      "device_id": "2004103660",
      "reason": "测试",
      "result": {
        "status": 0,
        "message": "操作成功"
      }
    }
  ]
}
```

### POST `/api/v1/idst/control`

`/api/v1/idst/open` 的兼容别名，参数和行为完全相同。

### POST `/api/v1/idst/rf-control`

IDST 原始调试接口。适合已经明确知道设备 ID 和协议参数时使用。

请求体：

```json
{
  "id": "2004103660",
  "ctrl": {
    "rf_id": 5,
    "smart_entrance_guard": {
      "lock": 1
    }
  }
}
```

curl 示例：

```bash
curl -X POST http://127.0.0.1:8000/api/v1/idst/rf-control \
  -H "Content-Type: application/json" \
  -H "X-API-Key: API_KEY" \
  -d '{
    "id": "2004103660",
    "ctrl": {
      "rf_id": 5,
      "smart_entrance_guard": {"lock": 1}
    }
  }'
```

该接口仍由服务自动生成 `access_token`、`Time` 和 `Sign`，调用方不需要手动传递这些字段。

## 7. IDST 会话接口

### GET `/api/v1/idst/session/status`

查看 IDST 会话状态，不返回 token 和 code。

```bash
curl http://127.0.0.1:8000/api/v1/idst/session/status \
  -H "X-API-Key: API_KEY"
```

响应：

```json
{
  "code": 200,
  "message": "IDST 会话状态",
  "data": {
    "token_valid": true,
    "code_valid": true,
    "age_seconds": 36.2,
    "websocket_connected": true
  }
}
```

### POST `/api/v1/idst/session/refresh`

强制重新获取 IDST token 和 WebSocket code。

```bash
curl -X POST http://127.0.0.1:8000/api/v1/idst/session/refresh \
  -H "X-API-Key: API_KEY"
```

响应：

```json
{
  "code": 200,
  "message": "IDST 会话刷新成功",
  "data": {
    "token_length": 32,
    "code_received": true
  }
}
```

## 8. 通用错误响应

### 缺少或错误 API Key

```http
401 Unauthorized
```

### API Key 未配置

```http
503 Service Unavailable
```

### 房间不存在

```http
400 Bad Request
```

示例：

```json
{
  "detail": "未找到 IDST 房间映射: ['1-906']"
}
```

### 上游登录、WebSocket 或网络失败

```http
502 Bad Gateway
```

### 请求超时

```http
504 Gateway Timeout
```

## 9. Postman 配置

以 IDST 604 开门为例：

```text
Method: POST
URL: http://127.0.0.1:8000/api/v1/idst/open
```

Headers：

```text
Content-Type: application/json
X-API-Key: storage/api_key 中的内容
```

Body → raw → JSON：

```json
{
  "rooms": ["604"],
  "reason": "Postman 测试"
}
```

Postman 不需要设置 IDST 的 `access_token`、`Sign`、`Time` 或 WebSocket `code`，这些由后台自动处理。

## 10. 运行和部署

### Windows

首次部署：

```text
双击 init.bat
```

启动服务：

```text
双击 start.bat
```

或 PowerShell：

```powershell
cd D:\campus_door_master
.\.venv\Scripts\Activate.ps1
python main.py
```

### Linux/macOS

```bash
cd /path/to/campus_door_master
source .venv/bin/activate
python main.py
```

常驻部署建议使用单 worker，避免多个进程分别维护 IDST WebSocket 会话：

```bash
uvicorn main:app --host 0.0.0.0 --port 8000 --workers 1
```

## 11. 安全注意事项

- 不要提交 `campus-door-master.env`。
- 不要提交 `storage/api_key`、`storage/token.json`、`storage/idst_token.json`。
- 不要在日志、截图或聊天中公开账号、密码、token、code 和 API Key。
- IDST 使用自签名证书时，`IDST_VERIFY_SSL=false`；正式环境应配置可信 CA。
- 只在可信内网开放 8000 端口。
