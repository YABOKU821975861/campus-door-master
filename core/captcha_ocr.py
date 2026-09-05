"""
验证码获取与 OCR 识别模块
负责从目标系统获取验证码图片并使用 ddddocr 进行自动识别
"""

import base64
import json
import logging
import time
from dataclasses import dataclass
from typing import Optional, Tuple

import requests
import urllib3

from config import (
    BASE_URL,
    CAPTCHA_ENDPOINT,
    CAPTCHA_MAX_RETRIES,
    CAPTCHA_TIMEOUT_SECONDS,
    USER_AGENT,
    ADO_VERIFY_SSL,
)

# 禁用 SSL 警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# 尝试导入 ddddocr
try:
    import ddddocr

    OCR_AVAILABLE = True
except ImportError:
    OCR_AVAILABLE = False
    ddddocr = None  # type: ignore

logger = logging.getLogger(__name__)


class CaptchaError(Exception):
    """验证码相关异常基类"""
    pass


class CaptchaFetchError(CaptchaError):
    """验证码获取失败"""
    pass


class CaptchaRecognitionError(CaptchaError):
    """验证码识别失败"""
    pass


class OCRNotAvailableError(CaptchaError):
    """OCR 库未安装"""
    pass


@dataclass
class CaptchaResult:
    """验证码识别结果"""
    key: str
    code: str
    raw_image_bytes: bytes


class CaptchaOCR:
    """
    验证码获取与 OCR 识别器
    
    流程：
    1. GET /api/captcha 获取 base64 编码的验证码图片及 key
    2. 解码 base64 图片
    3. 使用 ddddocr 识别验证码文本
    4. 返回 (key, code) 供登录使用
    """

    def __init__(self, session: Optional[requests.Session] = None):
        """
        初始化验证码识别器
        
        Args:
            session: 可选的 requests.Session，用于复用连接和 Cookie
        """
        self.captcha_url = f"{BASE_URL.rstrip('/')}{CAPTCHA_ENDPOINT}"
        self.captcha_method = "GET"
        self.session = session or requests.Session()
        self.session.verify = ADO_VERIFY_SSL
        self.session.headers.update({
            "User-Agent": USER_AGENT,
            "Origin": BASE_URL,
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        })

        # 初始化 OCR 引擎
        if OCR_AVAILABLE:
            self._ocr = ddddocr.DdddOcr(show_ad=False)
            logger.info("ddddocr OCR 引擎初始化成功")
        else:
            self._ocr = None
            logger.warning("ddddocr 未安装，无法自动识别验证码")

    def fetch_captcha_image(self) -> Tuple[str, bytes]:
        """
        从服务器获取验证码图片及 key
        
        Returns:
            Tuple[key, image_bytes]: 验证码 key 和原始图片字节
            
        Raises:
            CaptchaFetchError: 获取失败
        """
        last_error = None
        
        for attempt in range(1, CAPTCHA_MAX_RETRIES + 1):
            try:
                logger.debug(f"请求验证码 (尝试 {attempt}/{CAPTCHA_MAX_RETRIES}): {self.captcha_url}")
                request_method = getattr(self.session, self.captcha_method.lower())
                response = request_method(
                    self.captcha_url,
                    timeout=CAPTCHA_TIMEOUT_SECONDS,
                )
                
                if response.status_code != 200:
                    raise CaptchaFetchError(
                        f"HTTP {response.status_code}: {response.text[:200]}"
                    )

                data = response.json()
                
                # 兼容多种返回格式
                key = (
                    data.get("key") 
                    or data.get("data", {}).get("key")
                    or data.get("captcha_key")
                )
                
                img_data = (
                    data.get("img") 
                    or data.get("data", {}).get("img") 
                    or data.get("image")
                    or data.get("captcha_image")
                )

                if not key:
                    raise CaptchaFetchError(f"响应中缺少 key 字段: {data}")
                if not img_data:
                    raise CaptchaFetchError(f"响应中缺少图片数据字段: {data}")

                # 处理 base64 数据（可能包含 data:image/png;base64, 前缀）
                if isinstance(img_data, str) and "," in img_data:
                    img_data = img_data.split(",", 1)[1]
                
                try:
                    image_bytes = base64.b64decode(img_data)
                except Exception as e:
                    raise CaptchaFetchError(f"Base64 解码失败: {e}")

                logger.info(f"验证码获取成功，key 长度: {len(key)}, 图片大小: {len(image_bytes)} 字节")
                return key, image_bytes

            except requests.RequestException as e:
                last_error = CaptchaFetchError(f"网络请求异常: {e}")
                logger.warning(f"获取验证码失败 (尝试 {attempt}/{CAPTCHA_MAX_RETRIES}): {e}")
            except json.JSONDecodeError as e:
                last_error = CaptchaFetchError(f"响应非合法 JSON: {e}")
                logger.warning(f"解析验证码响应失败 (尝试 {attempt}/{CAPTCHA_MAX_RETRIES}): {e}")
            except CaptchaFetchError:
                raise
            except Exception as e:
                last_error = CaptchaFetchError(f"未知错误: {e}")
                logger.exception(f"获取验证码发生异常 (尝试 {attempt}/{CAPTCHA_MAX_RETRIES})")

            # 重试前等待
            if attempt < CAPTCHA_MAX_RETRIES:
                time.sleep(1)

        raise last_error or CaptchaFetchError("验证码获取失败：达到最大重试次数")

    def recognize_captcha(self, image_bytes: bytes) -> str:
        """
        使用 OCR 识别验证码图片
        
        Args:
            image_bytes: 验证码图片字节数据
            
        Returns:
            识别出的验证码文本
            
        Raises:
            OCRNotAvailableError: OCR 库未安装
            CaptchaRecognitionError: 识别失败
        """
        if not OCR_AVAILABLE or self._ocr is None:
            raise OCRNotAvailableError("ddddocr 库未安装，请运行: pip install ddddocr")

        try:
            code = self._ocr.classification(image_bytes).strip()
            
            if not code:
                raise CaptchaRecognitionError("OCR 识别结果为空")
            
            # 验证码通常为 4-6 位字母数字，简单校验
            if len(code) < 3 or len(code) > 8:
                logger.warning(f"OCR 识别结果长度异常: '{code}' (长度: {len(code)})")
            
            # 验证码本身也是短期敏感信息，不写入日志。
            logger.info("OCR 识别验证码成功，长度: %s", len(code))
            return code
            
        except CaptchaRecognitionError:
            raise
        except Exception as e:
            raise CaptchaRecognitionError(f"OCR 识别异常: {e}")

    def get_captcha(self) -> CaptchaResult:
        """
        获取并识别验证码的完整流程
        
        Returns:
            CaptchaResult: 包含 key、code、原始图片字节
            
        Raises:
            CaptchaError: 任一步骤失败
        """
        key, image_bytes = self.fetch_captcha_image()
        code = self.recognize_captcha(image_bytes)
        return CaptchaResult(key=key, code=code, raw_image_bytes=image_bytes)
