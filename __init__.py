"""
ComfyUI-Tripo-Leihuo: Tripo3D 雷火网关版 ComfyUI 节点

通过 ai.leihuo.netease.com 代理访问 Tripo API，
支持 v3.1-20260211 等最新模型版本。

使用 V3 Extension 风格 (io.ComfyNode + comfy_entrypoint)
"""

import traceback

print("=" * 70)
print("正在加载 ComfyUI-Tripo-Leihuo 插件 (雷火网关版)...")
print("=" * 70)

from comfy_api.latest import ComfyExtension

try:
    from .nodes import (
        TripoLeihuoTextToModelNode,
        TripoLeihuoImageToModelNode,
        TripoLeihuoMultiviewToModelNode,
        TripoLeihuoTextureNode,
        TripoLeihuoRigNode,
        TripoLeihuoRetargetNode,
        TripoLeihuoConvertNode,
    )

    print(f"[OK] 成功加载节点:")
    print(f"  - TripoLeihuoTextToModelNode      (文字转3D)")
    print(f"  - TripoLeihuoImageToModelNode      (图像转3D)")
    print(f"  - TripoLeihuoMultiviewToModelNode  (多视角转3D)")
    print(f"  - TripoLeihuoTextureNode           (纹理生成)")
    print(f"  - TripoLeihuoRigNode               (绑骨)")
    print(f"  - TripoLeihuoRetargetNode          (动画重定向)")
    print(f"  - TripoLeihuoConvertNode           (模型转换)")
    print(f"  网关: ai.leihuo.netease.com | 支持版本: v3.1, P1, v3.0, v2.5, v2.0, v1.4")
    print("=" * 70)

except Exception as e:
    print(f"[FAIL] 加载 ComfyUI-Tripo-Leihuo 插件时出错: {e}")
    traceback.print_exc()
    print("=" * 70)
    raise


class TripoLeihuoExtension(ComfyExtension):
    """Tripo 雷火网关 ComfyUI 扩展"""

    @classmethod
    async def get_node_list(cls):
        return [
            TripoLeihuoTextToModelNode,
            TripoLeihuoImageToModelNode,
            TripoLeihuoMultiviewToModelNode,
            TripoLeihuoTextureNode,
            TripoLeihuoRigNode,
            TripoLeihuoRetargetNode,
            TripoLeihuoConvertNode,
        ]


async def comfy_entrypoint():
    """ComfyUI 入口点 - V3 Extension 风格"""
    return TripoLeihuoExtension()

__all__ = ['comfy_entrypoint']
