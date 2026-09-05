# Campus Door Master

校园门禁与 IDST 智能设备统一中转服务。项目使用 FastAPI 提供本地 REST API，并通过 API Key 保护所有业务接口。

当前包含两套相互独立的上游接口体系：

| 体系 | 用途 | 凭证机制 |
|---|---|---|
| ADO 门禁 | 房间门锁开门、落锁 | 独立 TokenManager |
| IDST 设备 | RF 智能设备开门 | 独立 token + WebSocket code |

两套体系不共享 token、登录状态、WebSocket 或签名。

## 快速部署

### Windows

1. 安装 Python 3.10～3.13，并勾选 `Add Python to PATH`。
2. 将整个项目复制到 Windows，例如 `D:\campus_door_master`。
3. 首次运行项目目录中的 `init.bat`。
4. 编辑 `campus-door-master.env`，填写 ADO 和 IDST 配置。
5. 双击 `start.bat` 启动服务。

也可以在 PowerShell 中执行：

```powershell
cd D:\campus_door_master
.\.venv\Scripts\Activate.ps1
python main.py
```

### Linux/macOS

```bash
cd /path/to/campus_door_master
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python main.py
```

启动后访问 `http://127.0.0.1:8000/docs` 查看 Swagger 接口文档。

### CentOS 10

项目提供 `deploy_centos10.sh` 和 `campus-door-master.centos10.service`。将发布包解压到 `/opt/campus_door_master` 后执行：

```bash
cd /opt/campus_door_master
sudo bash deploy_centos10.sh
sudo vi /opt/campus_door_master/campus-door-master.env
sudo systemctl start campus-door-master
sudo systemctl status campus-door-master
```

查看日志：

```bash
sudo journalctl -u campus-door-master -f
```

完整接口说明请查看：[API接口文档.md](API接口文档.md)。

## 目录结构

```text
campus_door_master/
├── main.py                         # FastAPI 入口
├── config.py                       # 全局配置
├── rooms_config.py                 # ADO 门锁映射
├── idst_rooms_config.py            # IDST 房间到设备 ID 映射
├── core/
│   ├── token_manager.py             # ADO Token 管理
│   ├── door_driver.py               # ADO 门禁驱动
│   ├── captcha_ocr.py               # 验证码获取与 OCR
│   ├── idst_session_manager.py      # IDST 登录、token、WebSocket code
│   └── idst_driver.py               # IDST rf-ctrl 驱动
├── api/
│   └── idst_routes.py               # IDST API 路由
├── storage/
│   ├── api_key                     # 本地 API 鉴权密钥
│   ├── token.json                  # ADO token 缓存
│   └── idst_token.json             # IDST token/code 缓存
├── logs/app.log                    # 服务日志
├── campus-door-master.env          # 本地运行配置，不提交 Git
├── campus-door-master.env.example  # 配置模板
├── init.bat                         # Windows 首次初始化
├── start.bat                        # Windows 启动脚本
└── door_service.service             # systemd 配置示例
```

## 环境要求

- Python 3.10 或更高版本
- 可访问 ADO 门禁服务器和 IDST 设备服务器
- IDST 登录账号和密码

## 安装

```bash
cd /Users/z13/Desktop/ADO/campus_door_master
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 配置

编辑：

```text
campus-door-master.env
```

IDST 配置示例：

```env
IDST_BASE_URL=https://your-idst-server
IDST_USERNAME=你的IDST账号
IDST_PASSWORD=你的IDST密码
IDST_LOGIN_TIMEOUT_SECONDS=10
IDST_WS_TIMEOUT_SECONDS=10
IDST_TOKEN_CACHE_TTL=600
IDST_VERIFY_SSL=false
```

ADO 配置示例：

```env
ADO_BASE_URL=https://你的ADO服务器:端口
ADO_USERNAME=你的ADO账号
ADO_PASSWORD=你的ADO密码
ADO_VERIFY_SSL=false
```

从示例创建配置：

```bash
cp campus-door-master.env.example campus-door-master.env
```

Windows 可直接复制该文件后编辑。`campus-door-master.env` 不应提交到代码仓库。

默认接口路径也可以通过以下变量覆盖：

```env
ADO_LOGIN_ENDPOINT=/api/login
ADO_CAPTCHA_ENDPOINT=/api/captcha
ADO_OPEN_DOOR_ENDPOINT=/api/remote/openDoors/open
ADO_CLOSE_DOOR_ENDPOINT=/api/remote/openDoors/keep_close
```

IDST 设备使用自签名 HTTPS 证书，当前配置为：

```python
IDST_VERIFY_SSL = False
```

这等价于 curl 的 `--insecure`。正式部署时建议改为可信 CA 证书校验。

## 启动

Windows 首次部署可以直接双击项目目录中的 `init.bat`。它会自动创建 `.venv`、升级 pip 并安装全部依赖。

初始化脚本只需执行一次；依赖更新后可以再次运行。

`start.bat` 会自动激活虚拟环境并执行 `python main.py`。

之后在 PowerShell 中运行：

```powershell
cd D:\campus_door_master
.\.venv\Scripts\Activate.ps1
python main.py
```

```bash
cd /Users/z13/Desktop/ADO/campus_door_master
source .venv/bin/activate
python main.py
```

服务默认监听：

```text
http://0.0.0.0:8000
```

健康检查：

```bash
curl http://127.0.0.1:8000/health
```

从其他电脑访问时，将 `127.0.0.1` 换成部署电脑 IP，并确认防火墙放行 TCP 8000。

## API 鉴权

首次启动时，如果没有配置 `ADO_API_KEY`，程序会自动生成：

```text
storage/api_key
```

读取密钥：

```bash
cat storage/api_key
```

所有业务请求都需要：

```text
X-API-Key: storage/api_key 的内容
```

## ADO 门禁接口

### 开门

```http
POST /api/v1/doors/open
```

请求体示例：

```json
{
  "rooms": ["1-906"],
  "reason": "日常使用"
}
```

也可以直接传门锁 ID：

```json
{
  "lock_ids": ["门锁UUID"],
  "reason": "日常使用"
}
```

### 落锁

```http
POST /api/v1/doors/close
```

请求格式与开门接口相同。

### ADO Token 管理

```http
POST /api/v1/token/refresh
GET  /api/v1/token/status
```

ADO token 默认在内存中缓存，并写入 `storage/token.json`。

## IDST 开门接口

IDST 当前只使用开门指令，不提供锁门接口。

### 按房间号开门

```http
POST /api/v1/idst/open
```

Headers：

```text
Content-Type: application/json
X-API-Key: storage/api_key 的内容
```

604 房间示例：

```json
{
  "rooms": ["604"],
  "reason": "测试"
}
```

服务会自动执行：

```text
604 → 1-604 → 设备 ID 2004103660 → rf_id 5
```

407 房间示例：

```json
{
  "rooms": ["1-407"]
}
```

服务会自动映射为设备 ID `2003134696`，并在内部使用 `rf_id=15`、`lock=1`。

支持批量房间：

```json
{
  "rooms": ["1-407", "1-604"],
  "reason": "批量测试"
}
```

### 直接按设备 ID 开门

```json
{
  "device_ids": ["2004103660"],
  "reason": "测试"
}
```

### IDST 原始控制接口

为兼容调试，仍保留：

```http
POST /api/v1/idst/rf-control
```

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

业务调用建议使用 `/api/v1/idst/open`，由服务自动根据房间映射生成原始请求体。

## IDST token、code 和 Sign

IDST 登录流程：

```text
POST /api2/site/captcha-image
  → OCR 识别验证码
POST /api2/site/login
  → 获取 token
WebSocket /wss/
  → 发送 site/login
  → 获取 data.code
每次请求
  → Time = 当前毫秒时间戳
  → Sign = MD5(token + Time + code)
```

凭证缓存文件：

```text
storage/idst_token.json
```

该文件包含 token、code 和获取时间，权限为当前用户可读写。服务不会把完整 token 或 code 输出到接口响应中。

IDST 控制请求在线程池中执行，不会阻塞 FastAPI 主事件循环；WebSocket 使用心跳维持连接。验证码、token、code 和 Sign 不写入日志。

查看会话状态：

```http
GET /api/v1/idst/session/status
```

手动刷新会话：

```http
POST /api/v1/idst/session/refresh
```

该接口会重新登录并更新缓存，只返回 token 长度和 code 是否获取成功，不返回实际凭据。

## IDST 房间映射

映射文件：

```text
idst_rooms_config.py
```

当前已配置：

| 房间 | 设备 ID | rf_id |
|---|---:|---:|
| 1-408 | 2007302751 | 15 |
| 1-407 | 2003134696 | 15 |
| 1-405 | 2003432370 | 15 |
| 1-406 | 2000119870 | 15 |
| 1-603 | 2007185429 | 5 |
| 1-604 | 2004103660 | 5 |

IDST 业务接口按房间映射自动选择 `rf_id`，内部固定使用 `lock=1`，调用方只需要传房间号和可选的 `reason`。

## 常驻运行

### Windows 任务计划程序

建议创建“计算机启动时”任务：

```text
程序：D:\campus_door_master\.venv\Scripts\python.exe
参数：main.py
起始位置：D:\campus_door_master
```

勾选“无论用户是否登录都运行”。也可以直接双击 `start.bat` 手动启动。

### Linux systemd

将项目部署到目标目录后，修改 `door_service.service` 中的：

```text
WorkingDirectory
ExecStart
EnvironmentFile
```

然后执行：

```bash
sudo cp door_service.service /etc/systemd/system/campus-door-master.service
sudo systemctl daemon-reload
sudo systemctl enable --now campus-door-master
sudo systemctl status campus-door-master
```

查看日志：

```bash
journalctl -u campus-door-master -f
```

### macOS 临时后台运行

```bash
cd /Users/z13/Desktop/ADO/campus_door_master
source .venv/bin/activate
nohup python main.py > logs/console.log 2>&1 &
```

查看进程：

```bash
ps aux | grep '[p]ython main.py'
```

## 故障排查

### `ModuleNotFoundError`

确认使用的是项目虚拟环境：

```bash
which python
```

路径应包含：

```text
.../campus_door_master/.venv/bin/python
```

然后重新安装：

```bash
pip install -r requirements.txt
```

### IDST 验证码错误

服务已经配置为：

- `POST /api2/site/captcha-image`
- OCR 失败后更换验证码重试 3 次

如果仍然失败，查看 `logs/app.log`，确认设备验证码是否发生变化或 OCR 是否无法识别。

### SSL 校验失败

确认 `campus-door-master.env` 中：

```env
ADO_VERIFY_SSL=false
IDST_VERIFY_SSL=false
```

WebSocket 也会使用相同的 SSL 配置。

### 端口被占用

```bash
lsof -i :8000
```

停止旧进程后再启动服务。

## 安全注意事项

- 不要提交 `campus-door-master.env`、`storage/token.json`、`storage/idst_token.json` 和 `storage/api_key`。
- 不要在日志中打印完整 token、密码、code 或 Sign。
- 生产环境建议开启 SSL 证书校验，并限制服务监听地址和来源 IP。
- API Key 必须通过请求头传递，不要放入业务请求体。
- IDST token 和 code 属于动态会话凭证，服务重启后会自动恢复或重新登录。
