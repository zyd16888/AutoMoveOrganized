# Auto Move Organized

基于 Stash 的 Python 插件，在场景被标记为「已整理（organized）」后，把关联的视频文件移动到你指定的媒体库目录，并按照可配置的命名模板重命名；同时可生成 Emby/Kodi 兼容的 NFO、下载场景封面和演员图片，支持可选的 AI 翻译。

## 功能概览

- 自动 / 手动移动 Stash 场景文件到目标根目录 `target_root`
- 使用 `filename_template` 根据场景信息（番号、标题、日期、演员、厂牌、分组等）生成目录结构和文件名
- 仅移动 `organized=true` 的场景（可配置关闭）
- 生成 Emby/Kodi 兼容的 `*.nfo` 文件（可关闭）
- 下载场景封面到视频所在目录，命名为 `<basename>-poster.ext`
- 下载演员头像到全局 `actors` 目录，并可导出演员 NFO
- 可选开启 AI 翻译：把标题 / 简介翻译成简体中文并写入 NFO
- 附带若干辅助脚本（修复封面命名、向 Emby 导入演员图像等）

## 目录结构

- `auto_move_organized.py`：Stash 插件主程序
- `auto_move_organized.yml`：Stash 插件配置（任务 / Hook / UI 设置）
- `ai_translate.py`：调用兼容 OpenAI `chat/completions` 接口做标题 / 简介翻译
- `fix_posters.py`：批量给封面文件添加 `-poster` 后缀
- `fix_posters_match_video.py`：修正已带 `-poster` 但前缀与视频文件名不一致的封面
- `import.py`：扫描 `actors` 目录并把演员图片 + NFO 上传到 Emby
- `actors/`：示例演员图片 / NFO 目录
- `*.json`：示例输入、调试用导出结果（可忽略）

## 环境要求

- Python 3.9+（推荐）
- 已安装并运行中的 Stash
- Python 依赖：
  - `requests`
  - `stashapi`（Stash 提供的 Python 接口库）
- 使用 AI 翻译时：
  - 需要一个兼容 OpenAI `chat/completions` 协议的 API 服务，以及对应的 `base_url` / `api_key` / `model`

## 安装

1. 在 Stash 数据目录下找到或创建 `plugins` 目录。
2. 将 `auto_move_organized.yml` 和 `auto_move_organized.py` 复制到同一目录，例如：

   ```text
   /path/to/stash/plugins/auto_move_organized.yml
   /path/to/stash/plugins/auto_move_organized.py
   ```

3. 确保 Stash 的运行环境可以导入 `requests`、`stashapi` 等依赖。
4. 重启 Stash 或在设置中重新加载插件。

加载完成后，在 Stash 的「设置 → 插件 → Auto Move Organized」中可以看到本插件的配置项。

## 配置说明

`auto_move_organized.yml` 中定义的主要设置会在插件 UI 中可视化展示：

- `target_root`：目标根目录（必填）。所有移动后的视频都放在该目录下面。
- `filename_template`：命名模板（相对 `target_root` 的路径 + 文件名）。
- `move_only_organized`：仅移动 `organized=true` 的场景；关闭后所有场景都可处理。
- `dry_run`：仅模拟，不真正移动 / 下载 / 写入文件，用于先看日志确认结果。
- `write_nfo`：是否在视频旁生成 `*.nfo`。
- `download_poster`：是否为每个视频下载封面（`<basename>-poster.ext`）。
- `download_actor_images`：是否下载演员图片到全局 `actors` 目录。
- `export_actor_nfo`：是否为演员生成 NFO。
- `translate_enable`：是否启用 AI 翻译。
- `translate_title` / `translate_plot`：分别控制是否翻译标题 / 简介。
- `translate_api_base` / `translate_api_key` / `translate_model` / `translate_temperature` / `translate_prompt`：翻译服务的详细配置，对接任意兼容 OpenAI 的 `chat/completions` 接口。

## 命名模板占位符

`filename_template` 使用 Python 的 `str.format` 语法，支持的占位符大致包括（实际以代码中的 `build_template_vars` 为准）：

- `{id}`：scene ID
- `{scene_title}`：场景标题
- `{scene_date}`：完整日期，例如 `2025-01-02`
- `{date_year}` / `{date_month}` / `{date_day}`：年 / 月 / 日
- `{studio}` / `{studio_name}`：片商名称
- `{studio_id}`：片商 ID
- `{code}`：番号 / 自定义代码
- `{director}`：导演
- `{performers}`：演员名（使用 `-` 连接）
- `{first_performer}`：第一个演员
- `{performer_count}`：演员数量
- `{tag_names}` / `{tags}`：标签名称（逗号分隔）
- `{group_name}`：所属分组（系列）
- `{rating}` / `{rating100}`：评分
- `{original_basename}`：原始文件名（含扩展名）
- `{original_name}`：原始文件名（不含扩展名）
- `{ext}`：原始扩展名（不含点）
- `{external_id}`：外部 ID（如 StashDB）

示例：

```text
{studio}/{date_year}/{code}-{scene_title}-{performers}
```

如果模板中未包含扩展名，插件会自动保留原始扩展名。

## 运行方式

- **作为 Task 手动执行**  
  在 Stash 中打开「Tasks → Run Auto Move Organized」，可手动扫描并移动满足条件的场景，进度和日志会写入 Task 输出。

- **作为 Hook 自动执行**  
  `auto_move_organized.yml` 中示例性定义了一个 `Scene.Update.Post` Hook，目前主要用于调试；可根据需要扩展为每次场景更新后自动移动。

- **本地调试**  
  根目录中的 `input.json` / `scene-*.json` / `stash_configuration.json` 为抓取的示例数据，便于在 IDE 中脱离 Stash 调试：

  ```bash
  python auto_move_organized.py < input.json
  ```

  或临时修改 `main()` 中的读取方式为从本地文件加载。

## 辅助脚本

- `fix_posters.py`  
  为媒体库目录中所有图片补上 `-poster` 后缀，防止 Emby 无法识别为影片封面。

  ```bash
  python fix_posters.py /path/to/media/root
  ```

- `fix_posters_match_video.py`  
  当目录中只有一个视频文件时，修复形如 `<something>-poster.ext` 但前缀与视频名不一致的封面文件名。

  ```bash
  python fix_posters_match_video.py /path/to/media/root
  ```

- `import.py`  
  扫描当前目录及子目录中的 `actors` 文件夹，将演员图片和 NFO 上传到 Emby，并更新演员元数据（性别、国家、生日、身高、三围等）以便在 Emby 中展示。

  ```bash
  python import.py
  ```

  运行时会交互式询问 Emby 服务器地址和 API Key。

---

可以根据自己的库结构调整命名模板和 NFO / 翻译相关逻辑，这个仓库主要作为 Stash + Emby/Kodi 媒体库联动的个人工具合集。

自用的命名模板示例：

{studio_name}\{date_year}\{scene_date}.{scene_title}.{performers}\{studio_name}.{scene_date}.{scene_title}.{performers}.{ext}

---