# ComfyUI-Tripo-Leihuo

Tripo3D 3D模型生成 ComfyUI 节点 — **雷火网关版**

通过 `ai.leihuo.netease.com` 代理访问 Tripo API，支持 **v3.1-20260211** 等最新模型版本。

## 与内置 Tripo 节点的区别

| 特性 | 内置 Tripo 节点 | 本插件 (Leihuo) |
|------|----------------|-----------------|
| API 通道 | comfy.org 代理 → Tripo 官方 | ai.leihuo.netease.com 雷火网关 |
| 最新模型版本 | v3.0-20250812 | **v3.1-20260211** |
| P1 低多边形 | ❌ | ✅ P1-20260311 |
| 认证方式 | comfy.org 账号 | 雷火 API Token |
| 受 ComfyUI 更新影响 | ✅ | ❌ |

## 节点列表

所有节点位于 `leihuo/3d/Tripo` 分类下：

| 节点 | 功能 | 说明 |
|------|------|------|
| **Tripo 文字转3D (雷火)** | text_to_model | 文字描述生成3D模型 |
| **Tripo 图像转3D (雷火)** | image_to_model | 单张图像生成3D模型 |
| **Tripo 多视角转3D (雷火)** | multiview_to_model | 最多4张视角图生成3D模型 |
| **Tripo 纹理生成 (雷火)** | texture_model | 为已有模型生成纹理 |
| **Tripo 绑骨 (雷火)** | rig_model | 为模型添加骨骼绑定 |
| **Tripo 动画重定向 (雷火)** | retarget_animation | 为绑骨模型应用预设动画 |
| **Tripo 模型转换 (雷火)** | convert_model | 转换模型格式（GLTF/USDZ/FBX/OBJ/STL/3MF）|

## 支持的模型版本

- `v3.1-20260211` — 最新标准版（默认）
- `P1-20260311` — 低多边形优化版
- `v3.0-20250812`
- `v2.5-20250123`
- `v2.0-20240919`
- `v1.4-20240625`

## 安装

### 方式一：直接克隆到 ComfyUI custom_nodes 目录

```bash
cd ComfyUI/custom_nodes
git clone <repo-url> ComfyUI-Tripo-Leihuo
```

### 方式二：符号链接

```bash
# 克隆到任意位置
git clone <repo-url> /path/to/ComfyUI-Tripo-Leihuo

# 在 ComfyUI 的 custom_nodes 目录创建符号链接
mklink /D "ComfyUI\custom_nodes\ComfyUI-Tripo-Leihuo" "/path/to/ComfyUI-Tripo-Leihuo"
```

## 配置

编辑插件目录下的 `config.json`：

```json
{
    "api_token": "你的雷火API密钥",
    "base_url": "https://ai.leihuo.netease.com"
}
```

也可以在每个节点的 `api_key` 参数中直接输入密钥（优先级高于 config.json）。

## 工作流示例

### 多视角转3D（核心功能）

1. 准备最多4张不同视角的图像（正面必填）
2. 连接到 **Tripo 多视角转3D (雷火)** 节点
3. 选择模型版本 `v3.1-20260211`
4. 输出：GLB 模型文件 + 任务ID + 预览图

### 图像转3D + 绑骨 + 动画

```
图像 → [图像转3D] → task_id → [绑骨] → task_id → [动画重定向] → 模型文件
```

## 依赖

- `torch`（ComfyUI 自带）
- `Pillow`（ComfyUI 自带）
- `numpy`（ComfyUI 自带）
- `requests`（HTTP 请求）

无需额外安装依赖。

## License

MIT
