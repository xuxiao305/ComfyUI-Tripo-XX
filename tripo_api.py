"""
Tripo3D API Client (Leihuo Gateway)
Tripo3D 3D模型生成 API 客户端 — 雷火网关版

通过 ai.leihuo.netease.com 代理访问 Tripo API，
支持 v3.1-20260211 等最新模型版本。
"""

import requests
import json
import os
import tempfile
from typing import Optional, Dict, Any, List


class TripoAPIError(Exception):
    """Tripo API 错误异常"""

    def __init__(self, status_code: int, error_message: str, error_code: int = 0, task_id: str = ""):
        self.status_code = status_code
        self.error_message = error_message
        self.error_code = error_code
        self.task_id = task_id
        super().__init__(self._build_message())

    def _build_message(self) -> str:
        parts = []
        if self.error_code:
            parts.append(f"错误码: {self.error_code}")
        parts.append(f"信息: {self.error_message}")
        if self.task_id:
            parts.append(f"任务ID: {self.task_id}")
        return " | ".join(parts)


def load_tripo_config(config_path: str) -> Dict[str, str]:
    """加载 Tripo 配置文件"""
    if not os.path.exists(config_path):
        return {"api_token": "", "base_url": "https://ai.leihuo.netease.com"}
    with open(config_path, 'r', encoding='utf-8') as f:
        return json.load(f)


class TripoAPIClient:
    """
    Tripo3D API 客户端 — 雷火网关版

    支持所有 Tripo API 任务类型：
    - text_to_model: 文字生成3D模型
    - image_to_model: 单图生成3D模型
    - multiview_to_model: 多视角图生成3D模型
    - texture_model: 为模型生成纹理
    - refine_model: 精化草稿模型
    - rig_model: 绑骨
    - retarget_animation: 动画重定向
    - convert_model: 模型格式转换
    """

    # 支持的模型版本（含最新 v3.1）
    MODEL_VERSIONS = [
        "v3.1-20260211",
        "P1-20260311",
        "v3.0-20250812",
        "v2.5-20250123",
        "v2.0-20240919",
        "v1.4-20240625",
    ]

    def __init__(self, api_token: str, base_url: str):
        self.api_token = api_token
        self.base_url = base_url.rstrip('/')
        self.headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_token}"
        }

    def _log_request(self, method: str, url: str, payload: dict = None, is_multipart: bool = False):
        """打印请求详情"""
        token_preview = self.api_token[:8] + "..." if self.api_token else "(空)"
        print(f"[Tripo API] >>> {method} {url}")
        print(f"[Tripo API]     Authorization: Bearer {token_preview}")
        if is_multipart:
            print(f"[Tripo API]     Content-Type: multipart/form-data")
        else:
            print(f"[Tripo API]     Content-Type: application/json")
        if payload:
            print(f"[Tripo API]     Body: {json.dumps(payload, ensure_ascii=False, indent=2)}")

    def _log_response(self, response):
        """打印响应详情"""
        print(f"[Tripo API] <<< HTTP {response.status_code}")
        try:
            body = json.dumps(response.json(), ensure_ascii=False, indent=2)
            if len(body) > 1000:
                body = body[:1000] + "\n... (截断)"
            print(f"[Tripo API]     Body: {body}")
        except Exception:
            print(f"[Tripo API]     Body (raw): {response.text[:500]}")

    def upload_image(self, image_bytes: bytes, filename: str = "image.jpg") -> str:
        """
        上传图片，获取 image_token

        Args:
            image_bytes: JPEG 图片字节数据
            filename: 文件名

        Returns:
            image_token 字符串
        """
        url = f"{self.base_url}/v2/openapi/upload"
        headers_auth = {"Authorization": f"Bearer {self.api_token}"}

        self._log_request("POST", url, is_multipart=True)
        print(f"[Tripo API]     File: {filename} ({len(image_bytes) // 1024}KB)")

        try:
            files = {"file": (filename, image_bytes, "image/jpeg")}
            response = requests.post(url, headers=headers_auth, files=files, timeout=60)
            self._log_response(response)

            if response.status_code != 200:
                self._handle_api_error(response)

            data = response.json()
            if data.get("code", -1) != 0:
                raise TripoAPIError(
                    status_code=response.status_code,
                    error_message=data.get("message", "上传失败"),
                    error_code=data.get("code", -1)
                )

            image_token = data.get("data", {}).get("image_token", "")
            if not image_token:
                raise TripoAPIError(
                    status_code=response.status_code,
                    error_message="响应中未找到 image_token",
                    error_code=0
                )

            print(f"[Tripo API] 图片上传成功，image_token: {image_token}")
            return image_token

        except TripoAPIError:
            raise
        except Exception as e:
            print(f"[Tripo API] 上传图片错误: {e}")
            raise TripoAPIError(status_code=0, error_message=str(e), error_code=0)

    def create_task(self, payload: dict) -> str:
        """
        通用任务创建接口

        Args:
            payload: 任务请求体，包含 type 和其他参数

        Returns:
            task_id 字符串
        """
        url = f"{self.base_url}/v2/openapi/task"

        self._log_request("POST", url, payload)

        try:
            response = requests.post(
                url,
                headers=self.headers,
                json=payload,
                timeout=60
            )
            self._log_response(response)

            if response.status_code != 200:
                self._handle_api_error(response)

            data = response.json()
            if data.get("code", -1) != 0:
                error_msg = data.get("message", "未知错误")
                raise TripoAPIError(
                    status_code=response.status_code,
                    error_message=error_msg,
                    error_code=data.get("code", -1)
                )

            task_id = data.get("data", {}).get("task_id", "")
            if not task_id:
                raise TripoAPIError(
                    status_code=response.status_code,
                    error_message="响应中未找到 task_id",
                    error_code=0
                )

            print(f"[Tripo API] 任务已创建: {task_id} (type: {payload.get('type', 'unknown')})")
            return task_id

        except TripoAPIError:
            raise
        except Exception as e:
            print(f"[Tripo API] 网络错误: {e}")
            raise TripoAPIError(status_code=0, error_message=str(e), error_code=0)

    def create_text_to_model_task(
        self,
        prompt: str,
        negative_prompt: str = "",
        model_version: str = "v3.1-20260211",
        texture: bool = True,
        pbr: bool = True,
        face_limit: int = 0,
        image_seed: int = -1,
        model_seed: int = -1,
        texture_seed: int = -1,
        texture_quality: str = "standard",
        geometry_quality: str = "standard",
        style: str = "",
        auto_size: bool = False,
        quad: bool = False,
    ) -> str:
        """提交 text-to-model 生成任务"""
        payload = {
            "type": "text_to_model",
            "prompt": prompt,
            "model_version": model_version,
            "texture": texture,
            "pbr": pbr,
            "texture_quality": texture_quality,
            "geometry_quality": geometry_quality,
            "auto_size": auto_size,
            "quad": quad,
        }
        if negative_prompt:
            payload["negative_prompt"] = negative_prompt
        if face_limit > 0:
            payload["face_limit"] = face_limit
        if image_seed >= 0:
            payload["image_seed"] = image_seed
        if model_seed >= 0:
            payload["model_seed"] = model_seed
        if texture_seed >= 0:
            payload["texture_seed"] = texture_seed
        if style:
            payload["style"] = style

        return self.create_task(payload)

    def create_image_to_model_task(
        self,
        file_token: str,
        model_version: str = "v3.1-20260211",
        texture: bool = True,
        pbr: bool = True,
        face_limit: int = 0,
        enable_image_autofix: bool = False,
        model_seed: int = -1,
        texture_seed: int = -1,
        texture_quality: str = "standard",
        texture_alignment: str = "original_image",
        auto_size: bool = False,
        orientation: str = "default",
        quad: bool = False,
        smart_low_poly: bool = False,
        geometry_quality: str = "standard",
        export_uv: bool = True,
    ) -> str:
        """提交 image-to-model 生成任务"""
        payload = {
            "type": "image_to_model",
            "model_version": model_version,
            "file": {
                "type": "jpg",
                "file_token": file_token
            },
            "texture": texture,
            "pbr": pbr,
            "enable_image_autofix": enable_image_autofix,
            "texture_quality": texture_quality,
            "texture_alignment": texture_alignment,
            "auto_size": auto_size,
            "orientation": orientation,
            "quad": quad,
            "smart_low_poly": smart_low_poly,
            "export_uv": export_uv,
        }
        if face_limit > 0:
            payload["face_limit"] = face_limit
        if model_seed >= 0:
            payload["model_seed"] = model_seed
        if texture_seed >= 0:
            payload["texture_seed"] = texture_seed
        if geometry_quality != "standard":
            payload["geometry_quality"] = geometry_quality

        return self.create_task(payload)

    def create_multiview_to_model_task(
        self,
        file_tokens: List[Optional[str]],
        model_version: str = "v3.1-20260211",
        orthographic_projection: bool = False,
        texture: bool = True,
        pbr: bool = True,
        face_limit: int = 0,
        model_seed: int = -1,
        texture_seed: int = -1,
        texture_quality: str = "standard",
        texture_alignment: str = "original_image",
        auto_size: bool = False,
        orientation: str = "default",
        quad: bool = False,
        geometry_quality: str = "standard",
    ) -> str:
        """
        提交 multiview-to-model 生成任务

        Args:
            file_tokens: 4个 image_token 列表 [front, left, back, right]
                        front 必填，其他可以为 None
            model_version: 模型版本
            orthographic_projection: 是否使用正交投影
            texture: 是否生成纹理
            pbr: 是否使用 PBR 材质
            face_limit: 面数限制（0 = 自动）
            model_seed: 模型种子（-1 = 随机）
            texture_seed: 纹理种子（-1 = 随机）
            texture_quality: 纹理质量
            texture_alignment: 纹理对齐
            auto_size: 是否自动缩放
            orientation: 方向
            quad: 是否输出四边面
            geometry_quality: 几何精度

        Returns:
            task_id 字符串
        """
        # 构建 files 列表：有 token 的用 file_token 引用，没有的用空对象
        files = []
        for i, token in enumerate(file_tokens):
            if token:
                files.append({"type": "jpg", "file_token": token})
            else:
                files.append({})

        payload = {
            "type": "multiview_to_model",
            "model_version": model_version,
            "files": files,
            "orthographic_projection": orthographic_projection,
            "texture": texture,
            "pbr": pbr,
            "texture_quality": texture_quality,
            "texture_alignment": texture_alignment,
            "auto_size": auto_size,
            "orientation": orientation,
            "quad": quad,
            "geometry_quality": geometry_quality,
        }
        if face_limit > 0:
            payload["face_limit"] = face_limit
        if model_seed >= 0:
            payload["model_seed"] = model_seed
        if texture_seed >= 0:
            payload["texture_seed"] = texture_seed

        return self.create_task(payload)

    def create_texture_task(
        self,
        original_model_task_id: str,
        texture: bool = True,
        pbr: bool = True,
        texture_seed: int = -1,
        texture_quality: str = "standard",
        texture_alignment: str = "original_image",
    ) -> str:
        """提交纹理生成任务"""
        payload = {
            "type": "texture_model",
            "original_model_task_id": original_model_task_id,
            "texture": texture,
            "pbr": pbr,
            "texture_quality": texture_quality,
            "texture_alignment": texture_alignment,
        }
        if texture_seed >= 0:
            payload["texture_seed"] = texture_seed

        return self.create_task(payload)

    def create_rig_task(
        self,
        original_model_task_id: str,
    ) -> str:
        """提交绑骨任务"""
        payload = {
            "type": "rig_model",
            "original_model_task_id": original_model_task_id,
            "out_format": "glb",
            "spec": "tripo",
        }
        return self.create_task(payload)

    def create_retarget_task(
        self,
        original_model_task_id: str,
        animation: str = "preset:idle",
    ) -> str:
        """提交动画重定向任务"""
        payload = {
            "type": "retarget_animation",
            "original_model_task_id": original_model_task_id,
            "animation": animation,
            "out_format": "glb",
            "bake_animation": True,
        }
        return self.create_task(payload)

    def create_convert_task(
        self,
        original_model_task_id: str,
        format: str = "GLTF",
        quad: bool = False,
        face_limit: int = 0,
        texture_size: int = 4096,
        texture_format: str = "JPEG",
        force_symmetry: bool = False,
        flatten_bottom: bool = False,
        flatten_bottom_threshold: float = 0.0,
        pivot_to_center_bottom: bool = False,
        scale_factor: float = 1.0,
        with_animation: bool = False,
        pack_uv: bool = False,
        bake: bool = False,
        part_names: list = None,
        fbx_preset: str = "blender",
        export_vertex_colors: bool = False,
        export_orientation: str = "default",
        animate_in_place: bool = False,
    ) -> str:
        """提交模型格式转换任务"""
        payload = {
            "type": "convert_model",
            "original_model_task_id": original_model_task_id,
            "format": format,
        }
        if quad:
            payload["quad"] = quad
        if face_limit > 0:
            payload["face_limit"] = face_limit
        if texture_size != 4096:
            payload["texture_size"] = texture_size
        if texture_format != "JPEG":
            payload["texture_format"] = texture_format
        if force_symmetry:
            payload["force_symmetry"] = force_symmetry
        if flatten_bottom:
            payload["flatten_bottom"] = flatten_bottom
        if flatten_bottom_threshold > 0:
            payload["flatten_bottom_threshold"] = flatten_bottom_threshold
        if pivot_to_center_bottom:
            payload["pivot_to_center_bottom"] = pivot_to_center_bottom
        if scale_factor != 1.0:
            payload["scale_factor"] = scale_factor
        if with_animation:
            payload["with_animation"] = with_animation
        if pack_uv:
            payload["pack_uv"] = pack_uv
        if bake:
            payload["bake"] = bake
        if part_names:
            payload["part_names"] = part_names
        if fbx_preset != "blender":
            payload["fbx_preset"] = fbx_preset
        if export_vertex_colors:
            payload["export_vertex_colors"] = export_vertex_colors
        if export_orientation != "default":
            payload["export_orientation"] = export_orientation
        if animate_in_place:
            payload["animate_in_place"] = animate_in_place

        return self.create_task(payload)

    def get_task_status(self, task_id: str) -> Dict[str, Any]:
        """
        查询任务状态

        Returns:
            包含 status, progress, output 等字段的字典
        """
        url = f"{self.base_url}/v2/openapi/task/{task_id}"
        self._log_request("GET", url)

        try:
            response = requests.get(url, headers=self.headers, timeout=30)
            self._log_response(response)

            if response.status_code != 200:
                self._handle_api_error(response, task_id=task_id)

            data = response.json()

            # 格式1: {"code": 0, "data": {"status": ..., "progress": ..., "output": ...}}
            if "code" in data:
                if data.get("code") != 0:
                    raise TripoAPIError(
                        status_code=response.status_code,
                        error_message=data.get("message", "未知错误"),
                        error_code=data.get("code", -1),
                        task_id=task_id
                    )
                task_data = data.get("data", {})

            # 格式2: 扁平结构
            elif "status" in data:
                task_data = data

            # 格式3: 仅含 task_id
            elif "task_id" in data:
                task_data = {"status": "queued", "progress": 0}

            else:
                task_data = {"status": "unknown", "progress": 0}

            result = {
                "task_id": task_id,
                "status": task_data.get("status", "unknown"),
                "progress": task_data.get("progress", 0),
                "output": task_data.get("output", {}),
                "raw": task_data
            }
            print(f"[Tripo API] 状态: {result['status']}, 进度: {result['progress']}%")
            return result

        except TripoAPIError:
            raise
        except Exception as e:
            print(f"[Tripo API] 查询任务错误: {e}")
            raise TripoAPIError(status_code=0, error_message=str(e), error_code=0, task_id=task_id)

    def download_file(self, url: str, suffix: str = ".glb", output_path: str = None) -> str:
        """
        下载文件到本地

        Args:
            url: 文件 URL
            suffix: 文件后缀
            output_path: 输出路径（可选，默认创建临时文件）

        Returns:
            本地文件路径
        """
        if output_path is None:
            fd, output_path = tempfile.mkstemp(suffix=suffix)
            os.close(fd)

        print(f"[Tripo API] >>> GET {url}")
        print(f"[Tripo API]     保存到: {output_path}")

        try:
            response = requests.get(url, stream=True, timeout=300)
            print(f"[Tripo API] <<< HTTP {response.status_code}")
            response.raise_for_status()

            with open(output_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)

            file_size = os.path.getsize(output_path)
            print(f"[Tripo API] 下载完成: {file_size // 1024}KB")
            return output_path

        except Exception as e:
            print(f"[Tripo API] 下载失败: {e}")
            raise TripoAPIError(status_code=0, error_message=f"文件下载失败: {e}", error_code=0)

    def _handle_api_error(self, response, task_id: str = ""):
        """处理 API 错误响应"""
        status_code = response.status_code
        error_msg = ""
        error_code = 0

        try:
            error_data = response.json()
            error_msg = error_data.get("message", "")
            error_code = error_data.get("code", 0)
            if not error_msg:
                error_msg = error_data.get("error", {}).get("message", "") if isinstance(error_data.get("error"), dict) else str(error_data.get("error", ""))
        except Exception:
            error_msg = response.text[:300] if response.text else "未知错误"

        print(f"[Tripo API] HTTP错误 {status_code}: {error_msg}")
        raise TripoAPIError(
            status_code=status_code,
            error_message=error_msg or f"HTTP {status_code}",
            error_code=error_code,
            task_id=task_id
        )
