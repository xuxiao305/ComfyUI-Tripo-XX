"""
Tripo3D ComfyUI Nodes — Leihuo Gateway Edition
Tripo3D 3D模型生成 ComfyUI 节点 — 雷火网关版

通过 ai.leihuo.netease.com 代理访问 Tripo API，
支持 v3.1-20260211 等最新模型版本。

节点列表：
- TripoLeihuoTextToModelNode:  文字生成3D模型
- TripoLeihuoImageToModelNode:  单图生成3D模型
- TripoLeihuoMultiviewToModelNode: 多视角图生成3D模型
- TripoLeihuoTextureNode:       为模型生成纹理
- TripoLeihuoRigNode:           绑骨
- TripoLeihuoRetargetNode:      动画重定向
- TripoLeihuoConvertNode:       模型格式转换
- TripoLeihuoMeshSegmentationNode: 网格分割（模型拆分）
- TripoLeihuoMeshCompletionNode:   网格补全（配合分割使用）
"""

import os
import asyncio
import datetime
import torch
import numpy as np
from PIL import Image
from io import BytesIO
from typing import Optional

import folder_paths

from comfy_api.latest import ComfyExtension, io, Input, ComfyAPI
from comfy_api.latest._util import File3D

from .tripo_api import TripoAPIClient, TripoAPIError, load_tripo_config


# =============================================================================
# 通用工具函数
# =============================================================================

# 支持的模型版本（含最新 v3.1）
MODEL_VERSIONS = [
    "v3.1-20260211",
    "P1-20260311",
    "v3.0-20250812",
    "v2.5-20250123",
    "v2.0-20240919",
    "v1.4-20240625",
]

# 预设动画列表
ANIMATION_PRESETS = [
    "preset:idle",
    "preset:walk",
    "preset:run",
    "preset:dive",
    "preset:climb",
    "preset:jump",
    "preset:slash",
    "preset:shoot",
    "preset:hurt",
    "preset:fall",
    "preset:turn",
    "preset:quadruped:walk",
    "preset:hexapod:walk",
    "preset:octopod:walk",
    "preset:serpentine:march",
    "preset:aquatic:march",
]

# 转换格式列表
CONVERT_FORMATS = ["GLTF", "USDZ", "FBX", "OBJ", "STL", "3MF"]


def image_tensor_to_jpeg_bytes(image_tensor, quality: int = 95) -> bytes:
    """
    将 ComfyUI 图像张量转换为 JPEG 字节数据

    Args:
        image_tensor: torch.Tensor [B, H, W, C], 0-1范围
        quality: JPEG 压缩质量

    Returns:
        JPEG 字节数据
    """
    img = image_tensor[0]  # [H, W, C]

    if img.dtype == torch.bfloat16:
        img = img.float()

    if img.dtype == torch.float32 or img.dtype == torch.float16:
        img_np = (img.cpu().numpy() * 255).astype(np.uint8)
    else:
        img_np = img.cpu().numpy().astype(np.uint8)

    # RGBA → RGB
    if img_np.shape[2] == 4:
        pil_img = Image.fromarray(img_np, 'RGBA').convert('RGB')
    else:
        pil_img = Image.fromarray(img_np)

    buffer = BytesIO()
    pil_img.save(buffer, format="JPEG", quality=quality)
    return buffer.getvalue()


def image_url_to_tensor(image_url: str) -> Optional[torch.Tensor]:
    """
    从 URL 下载图像并转为 ComfyUI 张量
    """
    try:
        import requests
        response = requests.get(image_url, timeout=60)
        response.raise_for_status()
        pil_img = Image.open(BytesIO(response.content)).convert('RGB')
        img_np = np.array(pil_img).astype(np.float32) / 255.0
        tensor = torch.from_numpy(img_np).unsqueeze(0)  # [1, H, W, C]
        return tensor
    except Exception as e:
        print(f"[Tripo Leihuo] 下载预览图失败: {e}")
        return None


def get_client_and_config(api_key_override: str = ""):
    """获取配置并创建 API 客户端"""
    config_path = os.path.join(os.path.dirname(__file__), 'config.json')
    try:
        config = load_tripo_config(config_path)
    except Exception as e:
        print(f"[Tripo Leihuo] 加载配置失败: {e}")
        config = {"api_token": "", "base_url": "https://ai.leihuo.netease.com"}

    token = api_key_override if api_key_override else config.get('api_token', '')
    base_url = config.get('base_url', 'https://ai.leihuo.netease.com')

    if not token:
        raise RuntimeError(
            "Tripo API token 未配置，请在 config.json 中设置 api_token "
            "或在节点参数中提供 API密钥"
        )

    return TripoAPIClient(token, base_url)


async def poll_task_until_done(client: TripoAPIClient, task_id: str, max_wait: int = 600, poll_interval: int = 5):
    """
    轮询任务直到完成

    Args:
        client: TripoAPIClient 实例
        task_id: 任务 ID
        max_wait: 最大等待秒数
        poll_interval: 轮询间隔秒数

    Returns:
        status_info dict (包含 output 等)

    Raises:
        RuntimeError: 任务失败、被拒或超时
    """
    api = ComfyAPI()
    elapsed_time = 0
    last_progress = -1

    while elapsed_time < max_wait:
        await asyncio.sleep(poll_interval)
        elapsed_time += poll_interval

        status_info = client.get_task_status(task_id)
        status = status_info.get("status", "unknown")
        progress = status_info.get("progress", 0)

        # 同步进度到 ComfyUI 进度条
        await api.execution.set_progress(value=progress, max_value=100)

        if progress != last_progress:
            print(f"[Tripo Leihuo] 进度: {progress}% (状态: {status})")
            last_progress = progress

        if status == "success":
            output = status_info.get("output", {})
            print(f"[Tripo Leihuo] 生成成功！输出: {list(output.keys())}")
            return status_info

        elif status == "failed":
            raise RuntimeError(
                f"3D模型生成失败（任务ID: {task_id}）。"
                "请检查输入或联系管理员。"
            )
        elif status == "banned":
            raise RuntimeError(f"任务被拒绝：内容违反使用政策（任务ID: {task_id}）")
        elif status == "expired":
            raise RuntimeError(f"任务已过期（任务ID: {task_id}），请重试。")
        elif status == "cancelled":
            raise RuntimeError(f"任务已取消（任务ID: {task_id}）")

    raise RuntimeError(f"3D模型生成超时（等待超过 {max_wait} 秒，任务ID: {task_id}）")


def download_model_output(status_info: dict, client: TripoAPIClient, file_ext: str = ".glb") -> str:
    """
    从任务结果下载模型文件

    Args:
        status_info: poll_task_until_done 的返回值
        client: TripoAPIClient 实例
        file_ext: 文件后缀 (.glb 或 .fbx)

    Returns:
        本地文件路径
    """
    output = status_info.get("output", {})
    model_url = output.get("pbr_model") or output.get("model") or output.get("base_model") or ""

    if not model_url:
        print(f"[Tripo Leihuo] 警告：未找到模型 URL，完整输出: {output}")
        raise RuntimeError(f"无法获取3D模型下载链接")

    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = folder_paths.get_output_directory()
    model_filename = f"tripo_{timestamp}{file_ext}"
    model_path = os.path.join(output_dir, model_filename)

    print(f"[Tripo Leihuo] 下载3D模型文件...")
    client.download_file(model_url, suffix=file_ext, output_path=model_path)

    return model_path


# =============================================================================
# 节点定义
# =============================================================================

class TripoLeihuoTextToModelNode(io.ComfyNode):
    """Tripo 文字生成3D模型 — 雷火网关版"""

    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="TripoLeihuoTextToModelNode",
            category="leihuo/3d/Tripo",
            display_name="Tripo 文字转3D (雷火)",
            description="使用 Tripo API 通过文字生成 3D 模型，走雷火网关，支持 v3.1",
            inputs=[
                io.String.Input("prompt", multiline=True, tooltip="描述要生成的3D模型的文字提示"),
                io.String.Input("negative_prompt", multiline=True, optional=True, tooltip="反向提示词"),
                io.Combo.Input(
                    "model_version",
                    options=MODEL_VERSIONS,
                    default="v3.1-20260211",
                    tooltip="3D生成模型版本，v3.1 为最新标准版"
                ),
                io.Combo.Input(
                    "style",
                    options=["None", "person", "animal", "building", "vehicle", "prop", "furniture", "other"],
                    default="None",
                    optional=True,
                    tooltip="生成风格"
                ),
                io.Boolean.Input("texture", default=True, tooltip="是否生成纹理贴图"),
                io.Boolean.Input("pbr", default=True, tooltip="是否使用 PBR 物理渲染材质"),
                io.Int.Input("image_seed", default=-1, min=-1, max=2147483647, optional=True, advanced=True, tooltip="图像种子(-1=随机)"),
                io.Int.Input("model_seed", default=-1, min=-1, max=2147483647, optional=True, advanced=True, tooltip="模型种子(-1=随机)"),
                io.Int.Input("texture_seed", default=-1, min=-1, max=2147483647, optional=True, advanced=True, tooltip="纹理种子(-1=随机)"),
                io.Combo.Input("texture_quality", default="standard", options=["standard", "detailed"], optional=True, advanced=True, tooltip="纹理质量"),
                io.Int.Input("face_limit", default=0, min=0, max=2000000, optional=True, advanced=True, tooltip="面数限制(0=自动)"),
                io.Boolean.Input("quad", default=False, optional=True, advanced=True, tooltip="输出四边面网格"),
                io.Boolean.Input("generate_parts", default=False, optional=True, advanced=True, tooltip="生成分部件模型（需关闭 texture 和 pbr）"),
                io.Combo.Input("geometry_quality", default="standard", options=["standard", "detailed"], optional=True, advanced=True, tooltip="几何精度"),
                io.String.Input(
                    "api_key",
                    default="",
                    multiline=False,
                    tooltip="可选，覆盖 config.json 中的 api_token",
                    extra_dict={"password": True}
                ),
            ],
            outputs=[
                io.String.Output("model_path", tooltip="3D模型文件本地路径"),
                io.String.Output("task_id", tooltip="Tripo 任务 ID"),
                io.Image.Output("preview", tooltip="3D模型预览图"),
                io.File3DGLB.Output("GLB", tooltip="3D模型（GLB格式，支持3D预览）"),
            ],
        )

    @classmethod
    async def execute(
        cls,
        prompt: str,
        negative_prompt: str = "",
        model_version: str = "v3.1-20260211",
        style: str = "None",
        texture: bool = True,
        pbr: bool = True,
        image_seed: int = -1,
        model_seed: int = -1,
        texture_seed: int = -1,
        texture_quality: str = "standard",
        face_limit: int = 0,
        quad: bool = False,
        generate_parts: bool = False,
        geometry_quality: str = "standard",
        api_key: str = "",
    ) -> io.NodeOutput:
        if not prompt:
            raise RuntimeError("Prompt 不能为空")

        client = get_client_and_config(api_key)

        print(f"\n[Tripo Leihuo] 文字转3D | 版本: {model_version}")
        style_val = None if style == "None" else style

        # generate_parts 兼容性检查
        if generate_parts:
            if texture or pbr:
                print(f"[Tripo Leihuo] 警告：generate_parts 不兼容 texture/pbr，已自动关闭")
                texture = False
                pbr = False
            if quad:
                print(f"[Tripo Leihuo] 警告：generate_parts 不兼容 quad，已自动关闭")
                quad = False

        task_id = client.create_text_to_model_task(
            prompt=prompt,
            negative_prompt=negative_prompt,
            model_version=model_version,
            texture=texture,
            pbr=pbr,
            face_limit=face_limit,
            image_seed=image_seed,
            model_seed=model_seed,
            texture_seed=texture_seed,
            texture_quality=texture_quality,
            geometry_quality=geometry_quality,
            style=style_val or "",
            auto_size=True,
            quad=quad,
            generate_parts=generate_parts,
        )

        status_info = await poll_task_until_done(client, task_id)
        model_path = download_model_output(status_info, client)

        # 预览图
        preview_url = status_info.get("output", {}).get("rendered_image", "")
        preview_tensor = image_url_to_tensor(preview_url) if preview_url else None
        if preview_tensor is None:
            preview_tensor = torch.ones(1, 64, 64, 3) * 0.5

        print(f"[Tripo Leihuo] 完成！模型: {model_path}")
        glb_file = File3D(model_path, "glb")
        return io.NodeOutput(model_path, task_id, preview_tensor, glb_file)


class TripoLeihuoImageToModelNode(io.ComfyNode):
    """Tripo 单图生成3D模型 — 雷火网关版"""

    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="TripoLeihuoImageToModelNode",
            category="leihuo/3d/Tripo",
            display_name="Tripo 图像转3D (雷火)",
            description="使用 Tripo API 通过单张图像生成 3D 模型，走雷火网关，支持 v3.1",
            inputs=[
                io.Image.Input("image", tooltip="参考图像"),
                io.Combo.Input(
                    "model_version",
                    options=MODEL_VERSIONS,
                    default="v3.1-20260211",
                    tooltip="3D生成模型版本，v3.1 为最新标准版"
                ),
                io.Boolean.Input("texture", default=True, tooltip="是否生成纹理贴图"),
                io.Boolean.Input("pbr", default=True, tooltip="是否使用 PBR 物理渲染材质"),
                io.Int.Input("model_seed", default=-1, min=-1, max=2147483647, optional=True, advanced=True, tooltip="模型种子(-1=随机)"),
                io.Int.Input("texture_seed", default=-1, min=-1, max=2147483647, optional=True, advanced=True, tooltip="纹理种子(-1=随机)"),
                io.Combo.Input("texture_quality", default="standard", options=["standard", "detailed"], optional=True, advanced=True, tooltip="纹理质量"),
                io.Combo.Input("texture_alignment", default="original_image", options=["original_image", "geometry"], optional=True, advanced=True, tooltip="纹理对齐"),
                io.Int.Input("face_limit", default=0, min=0, max=500000, optional=True, advanced=True, tooltip="面数限制(0=自动)"),
                io.Boolean.Input("quad", default=False, optional=True, advanced=True, tooltip="输出四边面网格"),
                io.Boolean.Input("generate_parts", default=False, optional=True, advanced=True, tooltip="生成分部件模型（需关闭 texture 和 pbr）"),
                io.Combo.Input("geometry_quality", default="standard", options=["standard", "detailed"], optional=True, advanced=True, tooltip="几何精度"),
                io.Boolean.Input("auto_size", default=False, optional=True, advanced=True, tooltip="自动缩放到真实世界尺寸"),
                io.Boolean.Input("align_image", default=False, optional=True, advanced=True, tooltip="对齐图像方向"),
                io.String.Input(
                    "api_key",
                    default="",
                    multiline=False,
                    tooltip="可选，覆盖 config.json 中的 api_token",
                    extra_dict={"password": True}
                ),
            ],
            outputs=[
                io.String.Output("model_path", tooltip="3D模型文件本地路径"),
                io.String.Output("task_id", tooltip="Tripo 任务 ID"),
                io.Image.Output("preview", tooltip="3D模型预览图"),
                io.File3DGLB.Output("GLB", tooltip="3D模型（GLB格式，支持3D预览）"),
            ],
        )

    @classmethod
    async def execute(
        cls,
        image,
        model_version: str = "v3.1-20260211",
        texture: bool = True,
        pbr: bool = True,
        model_seed: int = -1,
        texture_seed: int = -1,
        texture_quality: str = "standard",
        texture_alignment: str = "original_image",
        face_limit: int = 0,
        quad: bool = False,
        generate_parts: bool = False,
        geometry_quality: str = "standard",
        auto_size: bool = False,
        align_image: bool = False,
        api_key: str = "",
    ) -> io.NodeOutput:
        if image is None:
            raise RuntimeError("图像不能为空")

        client = get_client_and_config(api_key)

        print(f"\n[Tripo Leihuo] 图像转3D | 版本: {model_version}")

        # 上传图片
        jpeg_bytes = image_tensor_to_jpeg_bytes(image)
        print(f"[Tripo Leihuo] 图片大小: {len(jpeg_bytes) // 1024}KB")
        file_token = client.upload_image(jpeg_bytes)

        # 提交任务
        # generate_parts 兼容性检查
        if generate_parts:
            if texture or pbr:
                print(f"[Tripo Leihuo] 警告：generate_parts 不兼容 texture/pbr，已自动关闭")
                texture = False
                pbr = False
            if quad:
                print(f"[Tripo Leihuo] 警告：generate_parts 不兼容 quad，已自动关闭")
                quad = False

        task_id = client.create_image_to_model_task(
            file_token=file_token,
            model_version=model_version,
            texture=texture,
            pbr=pbr,
            face_limit=face_limit,
            model_seed=model_seed,
            texture_seed=texture_seed,
            texture_quality=texture_quality,
            texture_alignment=texture_alignment,
            auto_size=auto_size,
            orientation="align_image" if align_image else "default",
            quad=quad,
            geometry_quality=geometry_quality,
            generate_parts=generate_parts,
        )

        status_info = await poll_task_until_done(client, task_id)
        model_path = download_model_output(status_info, client)

        preview_url = status_info.get("output", {}).get("rendered_image", "")
        preview_tensor = image_url_to_tensor(preview_url) if preview_url else None
        if preview_tensor is None:
            preview_tensor = torch.ones(1, 64, 64, 3) * 0.5

        print(f"[Tripo Leihuo] 完成！模型: {model_path}")
        glb_file = File3D(model_path, "glb")
        return io.NodeOutput(model_path, task_id, preview_tensor, glb_file)


class TripoLeihuoMultiviewToModelNode(io.ComfyNode):
    """Tripo 多视角图生成3D模型 — 雷火网关版（核心节点）"""

    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="TripoLeihuoMultiviewToModelNode",
            category="leihuo/3d/Tripo",
            display_name="Tripo 多视角转3D (雷火)",
            description="使用 Tripo API 通过最多4张视角图（前/左/后/右）生成 3D 模型，走雷火网关，支持 v3.1",
            inputs=[
                io.Image.Input("image_front", tooltip="正面图像（必填）"),
                io.Image.Input("image_left", optional=True, tooltip="左侧图像（可选）"),
                io.Image.Input("image_back", optional=True, tooltip="背面图像（可选）"),
                io.Image.Input("image_right", optional=True, tooltip="右侧图像（可选）"),
                io.Combo.Input(
                    "model_version",
                    options=MODEL_VERSIONS,
                    default="v3.1-20260211",
                    tooltip="3D生成模型版本，v3.1 为最新标准版"
                ),
                io.Boolean.Input("orthographic_projection", default=False, tooltip="是否使用正交投影（适合无透视的参考图）"),
                io.Boolean.Input("texture", default=True, tooltip="是否生成纹理贴图"),
                io.Boolean.Input("pbr", default=True, tooltip="是否使用 PBR 物理渲染材质"),
                io.Int.Input("model_seed", default=-1, min=-1, max=2147483647, optional=True, advanced=True, tooltip="模型种子(-1=随机)"),
                io.Int.Input("texture_seed", default=-1, min=-1, max=2147483647, optional=True, advanced=True, tooltip="纹理种子(-1=随机)"),
                io.Combo.Input("texture_quality", default="standard", options=["standard", "detailed"], optional=True, advanced=True, tooltip="纹理质量"),
                io.Combo.Input("texture_alignment", default="original_image", options=["original_image", "geometry"], optional=True, advanced=True, tooltip="纹理对齐"),
                io.Int.Input("face_limit", default=0, min=0, max=500000, optional=True, advanced=True, tooltip="面数限制(0=自动)"),
                io.Boolean.Input("quad", default=False, optional=True, advanced=True, tooltip="输出四边面网格"),
                io.Combo.Input("geometry_quality", default="standard", options=["standard", "detailed"], optional=True, advanced=True, tooltip="几何精度"),
                io.Boolean.Input("auto_size", default=False, optional=True, advanced=True, tooltip="自动缩放到真实世界尺寸"),
                io.Boolean.Input("align_image", default=False, optional=True, advanced=True, tooltip="对齐图像方向"),
                io.String.Input(
                    "api_key",
                    default="",
                    multiline=False,
                    tooltip="可选，覆盖 config.json 中的 api_token",
                    extra_dict={"password": True}
                ),
            ],
            outputs=[
                io.String.Output("model_path", tooltip="3D模型文件本地路径"),
                io.String.Output("task_id", tooltip="Tripo 任务 ID"),
                io.Image.Output("preview", tooltip="3D模型预览图"),
                io.File3DGLB.Output("GLB", tooltip="3D模型（GLB格式，支持3D预览）"),
            ],
        )

    @classmethod
    async def execute(
        cls,
        image_front,
        image_left=None,
        image_back=None,
        image_right=None,
        model_version: str = "v3.1-20260211",
        orthographic_projection: bool = False,
        texture: bool = True,
        pbr: bool = True,
        model_seed: int = -1,
        texture_seed: int = -1,
        texture_quality: str = "standard",
        texture_alignment: str = "original_image",
        face_limit: int = 0,
        quad: bool = False,
        geometry_quality: str = "standard",
        auto_size: bool = False,
        align_image: bool = False,
        api_key: str = "",
    ) -> io.NodeOutput:
        if image_front is None:
            raise RuntimeError("正面图像（image_front）不能为空")

        if image_left is None and image_back is None and image_right is None:
            raise RuntimeError("至少需要提供一张侧面或背面图像")

        client = get_client_and_config(api_key)

        print(f"\n{'='*60}")
        print(f"[Tripo Leihuo] 多视角转3D | 版本: {model_version}")
        print(f"[Tripo Leihuo] 输入: front={'✓' if image_front is not None else '✗'} "
              f"left={'✓' if image_left is not None else '✗'} "
              f"back={'✓' if image_back is not None else '✗'} "
              f"right={'✓' if image_right is not None else '✗'}")
        print(f"[Tripo Leihuo] 正交投影: {orthographic_projection}")
        print(f"{'='*60}")

        # 依次上传各视角图片
        file_tokens = []
        for name, img in [("front", image_front), ("left", image_left), ("back", image_back), ("right", image_right)]:
            if img is not None:
                jpeg_bytes = image_tensor_to_jpeg_bytes(img)
                print(f"[Tripo Leihuo] 上传 {name} 图: {len(jpeg_bytes) // 1024}KB")
                token = client.upload_image(jpeg_bytes)
                file_tokens.append(token)
            else:
                file_tokens.append(None)
                print(f"[Tripo Leihuo] {name} 图: 未提供")

        # 提交 multiview 任务
        task_id = client.create_multiview_to_model_task(
            file_tokens=file_tokens,
            model_version=model_version,
            orthographic_projection=orthographic_projection,
            texture=texture,
            pbr=pbr,
            face_limit=face_limit,
            model_seed=model_seed,
            texture_seed=texture_seed,
            texture_quality=texture_quality,
            texture_alignment=texture_alignment,
            auto_size=auto_size,
            orientation="align_image" if align_image else "default",
            quad=quad,
            geometry_quality=geometry_quality,
        )

        print(f"[Tripo Leihuo] 多视角任务已提交: {task_id}")

        status_info = await poll_task_until_done(client, task_id)
        model_path = download_model_output(status_info, client)

        preview_url = status_info.get("output", {}).get("rendered_image", "")
        preview_tensor = image_url_to_tensor(preview_url) if preview_url else None
        if preview_tensor is None:
            preview_tensor = torch.ones(1, 64, 64, 3) * 0.5

        print(f"[Tripo Leihuo] 完成！模型: {model_path}")
        glb_file = File3D(model_path, "glb")
        return io.NodeOutput(model_path, task_id, preview_tensor, glb_file)


class TripoLeihuoTextureNode(io.ComfyNode):
    """Tripo 为模型生成纹理 — 雷火网关版"""

    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="TripoLeihuoTextureNode",
            category="leihuo/3d/Tripo",
            display_name="Tripo 纹理生成 (雷火)",
            description="为已有 3D 模型生成纹理贴图",
            inputs=[
                io.String.Input("task_id", tooltip="Tripo 任务 ID（来自生成节点）"),
                io.Boolean.Input("texture", default=True, tooltip="是否生成纹理贴图"),
                io.Boolean.Input("pbr", default=True, tooltip="是否使用 PBR 物理渲染材质"),
                io.Int.Input("texture_seed", default=-1, min=-1, max=2147483647, optional=True, advanced=True, tooltip="纹理种子(-1=随机)"),
                io.Combo.Input("texture_quality", default="standard", options=["standard", "detailed"], optional=True, advanced=True, tooltip="纹理质量"),
                io.Combo.Input("texture_alignment", default="original_image", options=["original_image", "geometry"], optional=True, advanced=True, tooltip="纹理对齐"),
                io.String.Input(
                    "api_key",
                    default="",
                    multiline=False,
                    tooltip="可选，覆盖 config.json 中的 api_token",
                    extra_dict={"password": True}
                ),
            ],
            outputs=[
                io.String.Output("model_path", tooltip="3D模型文件本地路径"),
                io.String.Output("task_id", tooltip="Tripo 任务 ID"),
                io.Image.Output("preview", tooltip="3D模型预览图"),
                io.File3DGLB.Output("GLB", tooltip="3D模型（GLB格式，支持3D预览）"),
            ],
        )

    @classmethod
    async def execute(
        cls,
        task_id: str,
        texture: bool = True,
        pbr: bool = True,
        texture_seed: int = -1,
        texture_quality: str = "standard",
        texture_alignment: str = "original_image",
        api_key: str = "",
    ) -> io.NodeOutput:
        if not task_id:
            raise RuntimeError("task_id 不能为空")

        client = get_client_and_config(api_key)

        print(f"\n[Tripo Leihuo] 纹理生成 | 任务ID: {task_id}")

        new_task_id = client.create_texture_task(
            original_model_task_id=task_id,
            texture=texture,
            pbr=pbr,
            texture_seed=texture_seed,
            texture_quality=texture_quality,
            texture_alignment=texture_alignment,
        )

        status_info = await poll_task_until_done(client, new_task_id)
        model_path = download_model_output(status_info, client)

        preview_url = status_info.get("output", {}).get("rendered_image", "")
        preview_tensor = image_url_to_tensor(preview_url) if preview_url else None
        if preview_tensor is None:
            preview_tensor = torch.ones(1, 64, 64, 3) * 0.5

        print(f"[Tripo Leihuo] 完成！模型: {model_path}")
        glb_file = File3D(model_path, "glb")
        return io.NodeOutput(model_path, new_task_id, preview_tensor, glb_file)


class TripoLeihuoRigNode(io.ComfyNode):
    """Tripo 绑骨 — 雷火网关版"""

    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="TripoLeihuoRigNode",
            category="leihuo/3d/Tripo",
            display_name="Tripo 绑骨 (雷火)",
            description="为 3D 模型添加骨骼绑定",
            inputs=[
                io.String.Input("task_id", tooltip="Tripo 任务 ID（来自生成节点）"),
                io.String.Input(
                    "api_key",
                    default="",
                    multiline=False,
                    tooltip="可选，覆盖 config.json 中的 api_token",
                    extra_dict={"password": True}
                ),
            ],
            outputs=[
                io.String.Output("model_path", tooltip="3D模型文件本地路径"),
                io.String.Output("task_id", tooltip="绑骨任务 ID"),
                io.Image.Output("preview", tooltip="3D模型预览图"),
                io.File3DGLB.Output("GLB", tooltip="3D模型（GLB格式，支持3D预览）"),
            ],
        )

    @classmethod
    async def execute(cls, task_id: str, api_key: str = "") -> io.NodeOutput:
        if not task_id:
            raise RuntimeError("task_id 不能为空")

        client = get_client_and_config(api_key)

        print(f"\n[Tripo Leihuo] 绑骨 | 任务ID: {task_id}")

        rig_task_id = client.create_rig_task(original_model_task_id=task_id)

        status_info = await poll_task_until_done(client, rig_task_id, max_wait=300)
        model_path = download_model_output(status_info, client)

        preview_url = status_info.get("output", {}).get("rendered_image", "")
        preview_tensor = image_url_to_tensor(preview_url) if preview_url else None
        if preview_tensor is None:
            preview_tensor = torch.ones(1, 64, 64, 3) * 0.5

        print(f"[Tripo Leihuo] 完成！模型: {model_path}")
        glb_file = File3D(model_path, "glb")
        return io.NodeOutput(model_path, rig_task_id, preview_tensor, glb_file)


class TripoLeihuoRetargetNode(io.ComfyNode):
    """Tripo 动画重定向 — 雷火网关版"""

    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="TripoLeihuoRetargetNode",
            category="leihuo/3d/Tripo",
            display_name="Tripo 动画重定向 (雷火)",
            description="为绑骨模型应用预设动画",
            inputs=[
                io.String.Input("task_id", tooltip="绑骨任务 ID（来自绑骨节点）"),
                io.Combo.Input("animation", options=ANIMATION_PRESETS, default="preset:idle", tooltip="预设动画"),
                io.String.Input(
                    "api_key",
                    default="",
                    multiline=False,
                    tooltip="可选，覆盖 config.json 中的 api_token",
                    extra_dict={"password": True}
                ),
            ],
            outputs=[
                io.String.Output("model_path", tooltip="3D模型文件本地路径"),
                io.String.Output("task_id", tooltip="重定向任务 ID"),
                io.Image.Output("preview", tooltip="3D模型预览图"),
                io.File3DGLB.Output("GLB", tooltip="3D模型（GLB格式，支持3D预览）"),
            ],
        )

    @classmethod
    async def execute(cls, task_id: str, animation: str = "preset:idle", api_key: str = "") -> io.NodeOutput:
        if not task_id:
            raise RuntimeError("task_id 不能为空")

        client = get_client_and_config(api_key)

        print(f"\n[Tripo Leihuo] 动画重定向 | 任务ID: {task_id}, 动画: {animation}")

        retarget_task_id = client.create_retarget_task(
            original_model_task_id=task_id,
            animation=animation,
        )

        status_info = await poll_task_until_done(client, retarget_task_id, max_wait=120)
        model_path = download_model_output(status_info, client)

        preview_url = status_info.get("output", {}).get("rendered_image", "")
        preview_tensor = image_url_to_tensor(preview_url) if preview_url else None
        if preview_tensor is None:
            preview_tensor = torch.ones(1, 64, 64, 3) * 0.5

        print(f"[Tripo Leihuo] 完成！模型: {model_path}")
        glb_file = File3D(model_path, "glb")
        return io.NodeOutput(model_path, retarget_task_id, preview_tensor, glb_file)


class TripoLeihuoConvertNode(io.ComfyNode):
    """Tripo 模型格式转换 — 雷火网关版"""

    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="TripoLeihuoConvertNode",
            category="leihuo/3d/Tripo",
            display_name="Tripo 模型转换 (雷火)",
            description="转换3D模型格式（GLTF/USDZ/FBX/OBJ/STL/3MF）",
            inputs=[
                io.String.Input("task_id", tooltip="Tripo 任务 ID"),
                io.Combo.Input("format", options=CONVERT_FORMATS, default="GLTF", tooltip="输出格式"),
                io.Boolean.Input("quad", default=False, optional=True, advanced=True, tooltip="输出四边面网格"),
                io.Int.Input("face_limit", default=0, min=0, max=2000000, optional=True, advanced=True, tooltip="面数限制(0=自动)"),
                io.Int.Input("texture_size", default=4096, min=128, max=4096, optional=True, advanced=True, tooltip="纹理尺寸"),
                io.Combo.Input(
                    "texture_format",
                    options=["BMP", "DPX", "HDR", "JPEG", "OPEN_EXR", "PNG", "TARGA", "TIFF", "WEBP"],
                    default="JPEG",
                    optional=True,
                    advanced=True,
                    tooltip="纹理格式"
                ),
                io.Boolean.Input("force_symmetry", default=False, optional=True, advanced=True, tooltip="强制对称"),
                io.Boolean.Input("flatten_bottom", default=False, optional=True, advanced=True, tooltip="展平底面"),
                io.Float.Input("flatten_bottom_threshold", default=0.0, min=0.0, max=1.0, optional=True, advanced=True, tooltip="展平阈值"),
                io.Boolean.Input("pivot_to_center_bottom", default=False, optional=True, advanced=True, tooltip="轴心移至底部中心"),
                io.Float.Input("scale_factor", default=1.0, min=0.0, optional=True, advanced=True, tooltip="缩放因子"),
                io.Boolean.Input("with_animation", default=False, optional=True, advanced=True, tooltip="包含动画"),
                io.Boolean.Input("pack_uv", default=False, optional=True, advanced=True, tooltip="打包UV"),
                io.String.Input("part_names", default="", multiline=False, optional=True, advanced=True, tooltip="部件名称（逗号分隔）"),
                io.Combo.Input("fbx_preset", options=["blender", "mixamo", "3dsmax"], default="blender", optional=True, advanced=True, tooltip="FBX预设"),
                io.Boolean.Input("export_vertex_colors", default=False, optional=True, advanced=True, tooltip="导出顶点色"),
                io.String.Input(
                    "api_key",
                    default="",
                    multiline=False,
                    tooltip="可选，覆盖 config.json 中的 api_token",
                    extra_dict={"password": True}
                ),
            ],
            outputs=[
                io.String.Output("model_path", tooltip="3D模型文件本地路径"),
                io.String.Output("task_id", tooltip="转换任务 ID"),
                io.File3DGLB.Output("GLB", tooltip="3D模型（GLB格式，支持3D预览）"),
            ],
        )

    @classmethod
    async def execute(
        cls,
        task_id: str,
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
        part_names: str = "",
        fbx_preset: str = "blender",
        export_vertex_colors: bool = False,
        api_key: str = "",
    ) -> io.NodeOutput:
        if not task_id:
            raise RuntimeError("task_id 不能为空")

        client = get_client_and_config(api_key)

        # 解析 part_names
        part_names_list = None
        if part_names and part_names.strip():
            part_names_list = [n.strip() for n in part_names.split(',') if n.strip()]

        print(f"\n[Tripo Leihuo] 模型转换 | 任务ID: {task_id}, 格式: {format}")

        convert_task_id = client.create_convert_task(
            original_model_task_id=task_id,
            format=format,
            quad=quad,
            face_limit=face_limit,
            texture_size=texture_size,
            texture_format=texture_format,
            force_symmetry=force_symmetry,
            flatten_bottom=flatten_bottom,
            flatten_bottom_threshold=flatten_bottom_threshold,
            pivot_to_center_bottom=pivot_to_center_bottom,
            scale_factor=scale_factor,
            with_animation=with_animation,
            pack_uv=pack_uv,
            part_names=part_names_list,
            fbx_preset=fbx_preset,
            export_vertex_colors=export_vertex_colors,
        )

        status_info = await poll_task_until_done(client, convert_task_id, max_wait=120)

        # 根据格式确定文件后缀
        ext_map = {"GLTF": ".glb", "USDZ": ".usdz", "FBX": ".fbx", "OBJ": ".obj", "STL": ".stl", "3MF": ".3mf"}
        file_ext = ext_map.get(format, ".glb")

        output = status_info.get("output", {})
        model_url = output.get("model") or output.get("pbr_model") or output.get("base_model") or ""

        if not model_url:
            raise RuntimeError(f"无法获取转换后的模型下载链接")

        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        output_dir = folder_paths.get_output_directory()
        model_filename = f"tripo_convert_{timestamp}{file_ext}"
        model_path = os.path.join(output_dir, model_filename)
        client.download_file(model_url, suffix=file_ext, output_path=model_path)

        print(f"[Tripo Leihuo] 完成！模型: {model_path}")
        glb_file = File3D(model_path, file_ext.lstrip("."))
        return io.NodeOutput(model_path, convert_task_id, glb_file)


class TripoLeihuoMeshSegmentationNode(io.ComfyNode):
    """Tripo 网格分割（模型拆分）— 雷火网关版"""

    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="TripoLeihuoMeshSegmentationNode",
            category="leihuo/3d/Tripo",
            display_name="Tripo 网格分割 (雷火)",
            description="将3D模型自动分割为多个部件，导入Blender等软件后可在collection区域看到部件名称",
            inputs=[
                io.String.Input("task_id", force_input=True, optional=True, tooltip="Tripo 任务 ID（来自生成/纹理/转换节点）"),
                io.String.Input(
                    "api_key",
                    default="",
                    multiline=False,
                    tooltip="可选，覆盖 config.json 中的 api_token",
                    extra_dict={"password": True}
                ),
            ],
            outputs=[
                io.String.Output("model_path", tooltip="分割后的3D模型文件本地路径"),
                io.String.Output("task_id", tooltip="分割任务 ID"),
                io.String.Output("part_names", tooltip="部件名称列表（逗号分隔，可用于后续补全/转换节点）"),
                io.Image.Output("preview", tooltip="3D模型预览图"),
                io.File3DGLB.Output("GLB", tooltip="3D模型（GLB格式，支持3D预览）"),
            ],
        )

    @classmethod
    async def execute(cls, task_id: str, api_key: str = "") -> io.NodeOutput:
        if not task_id:
            raise RuntimeError("task_id 不能为空")

        client = get_client_and_config(api_key)

        print(f"\n[Tripo Leihuo] 网格分割 | 上游任务ID: {task_id}")

        seg_task_id = client.create_mesh_segmentation_task(
            original_model_task_id=task_id,
        )

        status_info = await poll_task_until_done(client, seg_task_id, max_wait=600)
        model_path = download_model_output(status_info, client)

        # 提取部件名称列表
        output = status_info.get("output", {})
        part_names_list = output.get("part_names", [])
        if isinstance(part_names_list, list) and len(part_names_list) > 0:
            part_names_str = ",".join(part_names_list)
        else:
            part_names_str = ""
            print(f"[Tripo Leihuo] 警告：未获取到部件名称列表，完整输出: {output}")

        print(f"[Tripo Leihuo] 分割完成！部件: {part_names_str or '(未返回)'}")

        preview_url = output.get("rendered_image", "")
        preview_tensor = image_url_to_tensor(preview_url) if preview_url else None
        if preview_tensor is None:
            preview_tensor = torch.ones(1, 64, 64, 3) * 0.5

        glb_file = File3D(model_path, "glb")
        return io.NodeOutput(model_path, seg_task_id, part_names_str, preview_tensor, glb_file)


class TripoLeihuoMeshCompletionNode(io.ComfyNode):
    """Tripo 网格补全 — 雷火网关版"""

    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="TripoLeihuoMeshCompletionNode",
            category="leihuo/3d/Tripo",
            display_name="Tripo 网格补全 (雷火)",
            description="对分割后的模型部件进行几何补全，补全被其他部件遮挡的区域",
            inputs=[
                io.String.Input("task_id", force_input=True, optional=True, tooltip="网格分割任务的 task_id（来自 Tripo 网格分割节点）"),
                io.String.Input("part_names", default="", multiline=False, force_input=True, optional=True, tooltip="要补全的部件名称（逗号分隔，留空=全部部件）"),
                io.String.Input(
                    "api_key",
                    default="",
                    multiline=False,
                    tooltip="可选，覆盖 config.json 中的 api_token",
                    extra_dict={"password": True}
                ),
            ],
            outputs=[
                io.String.Output("model_path", tooltip="补全后的3D模型文件本地路径"),
                io.String.Output("task_id", tooltip="补全任务 ID"),
                io.Image.Output("preview", tooltip="3D模型预览图"),
                io.File3DGLB.Output("GLB", tooltip="3D模型（GLB格式，支持3D预览）"),
            ],
        )

    @classmethod
    async def execute(cls, task_id: str, part_names: str = "", api_key: str = "") -> io.NodeOutput:
        if not task_id:
            raise RuntimeError("task_id 不能为空（需要网格分割任务的 task_id）")

        client = get_client_and_config(api_key)

        # 解析 part_names
        part_names_list = None
        if part_names and part_names.strip():
            part_names_list = [n.strip() for n in part_names.split(',') if n.strip()]

        print(f"\n[Tripo Leihuo] 网格补全 | 分割任务ID: {task_id}")
        if part_names_list:
            print(f"[Tripo Leihuo] 指定部件: {part_names_list}")
        else:
            print(f"[Tripo Leihuo] 补全全部部件")

        completion_task_id = client.create_mesh_completion_task(
            original_model_task_id=task_id,
            part_names=part_names_list,
        )

        status_info = await poll_task_until_done(client, completion_task_id, max_wait=300)
        model_path = download_model_output(status_info, client)

        preview_url = status_info.get("output", {}).get("rendered_image", "")
        preview_tensor = image_url_to_tensor(preview_url) if preview_url else None
        if preview_tensor is None:
            preview_tensor = torch.ones(1, 64, 64, 3) * 0.5

        print(f"[Tripo Leihuo] 补全完成！模型: {model_path}")
        glb_file = File3D(model_path, "glb")
        return io.NodeOutput(model_path, completion_task_id, preview_tensor, glb_file)
