#!/usr/bin/env python3
import sys
import json
import requests
import os
import shutil
import time
import argparse
import ast
from pathlib import Path

# Stash插件通信
def read_json_input():
    """读取Stash传入的JSON数据"""
    json_input = sys.stdin.read()
    return json.loads(json_input)

def send_progress(progress, status=""):
    """发送进度到Stash"""
    print(json.dumps({
        "progress": progress,
        "status": status
    }), flush=True)

def log(level, message):
    """发送日志到Stash"""
    print(json.dumps({
        "level": level,
        "message": message
    }), file=sys.stderr, flush=True)

def parse_server_connection(raw):
    """兼容单引号/非标准JSON的server_connection解析"""
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        try:
            parsed = ast.literal_eval(raw)
        except Exception:
            log("error", f"无法解析server_connection: {raw}")
            sys.exit(1)
    if not isinstance(parsed, dict):
        log("error", f"server_connection格式错误: {parsed}")
        
        sys.exit(1)
    return parsed

class StashAPI:
    def __init__(self, url, api_key=None):
        self.url = url
        self.headers = {"Content-Type": "application/json"}
        if api_key:
            self.headers["ApiKey"] = api_key
    
    def call_gql(self, query, variables=None):
        """调用GraphQL API"""
        json_data = {"query": query}
        if variables:
            json_data["variables"] = variables
        
        try:
            response = requests.post(
                f"{self.url}/graphql",
                json=json_data,
                headers=self.headers
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            log("error", f"API调用失败: {str(e)}")
            return None
    
    def scan_library(self):
        """扫描媒体库"""
        mutation = """
        mutation MetadataScan {
            metadataScan(input: {})
        }
        """
        result = self.call_gql(mutation)
        log("info", "已触发媒体库扫描")
        return result
    
    def get_scenes_in_path(self, path, organized_filter=False):
        """获取指定路径下的场景"""
        query = """
        query FindScenes($path: String!, $organized: Boolean) {
            findScenes(
                scene_filter: {
                    path: { value: $path, modifier: INCLUDES }
                    organized: $organized
                }
                filter: { per_page: -1 }
            ) {
                scenes {
                    id
                    title
                    path
                    studio { id name }
                    performers { id name }
                    organized
                    details
                    created_at
                }
            }
        }
        """
        result = self.call_gql(query, {"path": path, "organized": organized_filter})
        if result and "data" in result:
            return result["data"]["findScenes"]["scenes"]
        return []
    
    def identify_scene(self, scene_id):
        """刮削场景"""
        query = """
        query ScrapeSingleScene($id: ID!) {
            scrapeSingleScene(source: { scene_id: $id }) {
                ... on ScrapedScene {
                    title
                    details
                    studio { name }
                    performers { name }
                }
            }
        }
        """
        result = self.call_gql(query, {"id": scene_id})
        log("info", f"已刮削场景 ID: {scene_id}")
        return result
    
    def update_scene(self, scene_id, organized=True):
        """更新场景状态"""
        mutation = """
        mutation SceneUpdate($id: ID!, $organized: Boolean!) {
            sceneUpdate(input: {
                id: $id
                organized: $organized
            }) {
                id
            }
        }
        """
        result = self.call_gql(mutation, {"id": scene_id, "organized": organized})
        return result

class AutoMover:
    def __init__(self, stash_api, config):
        self.api = stash_api
        self.config = config
        self.download_path = config.get("downloadPath", "")
        self.target_path = config.get("targetPath", "")
        self.check_interval = int(config.get("checkInterval", 300))
        self.use_organized_flag = config.get("useOrganizedFlag", True)
        self.require_studio = config.get("requireStudio", True)
        self.require_performers = config.get("requirePerformers", False)
        self.auto_scan = config.get("autoScan", True)
        self.auto_identify = config.get("autoIdentify", True)
        self.move_mode = config.get("moveMode", "move")
    
    def is_scraped(self, scene):
        """判断场景是否已刮削"""
        # 优先使用organized标记
        if self.use_organized_flag:
            return scene.get("organized", False)
        
        # 否则使用元数据判断
        has_studio = scene.get("studio") is not None
        has_performers = len(scene.get("performers", [])) > 0
        has_details = bool(scene.get("details") or scene.get("title"))
        
        if self.require_studio and not has_studio:
            return False
        if self.require_performers and not has_performers:
            return False
        
        return has_details or has_studio or has_performers
    
    def move_file(self, source_path, scene_id):
        """移动文件"""
        if not os.path.exists(source_path):
            log("warning", f"源文件不存在: {source_path}")
            return False
        
        filename = os.path.basename(source_path)
        target_file = os.path.join(self.target_path, filename)
        
        # 如果目标文件已存在，添加序号
        if os.path.exists(target_file):
            base, ext = os.path.splitext(filename)
            counter = 1
            while os.path.exists(target_file):
                target_file = os.path.join(
                    self.target_path, 
                    f"{base}_{counter}{ext}"
                )
                counter += 1
        
        try:
            # 确保目标目录存在
            os.makedirs(self.target_path, exist_ok=True)
            
            if self.move_mode == "copy":
                shutil.copy2(source_path, target_file)
                log("info", f"已复制: {filename} -> {target_file}")
            elif self.move_mode == "hardlink":
                os.link(source_path, target_file)
                log("info", f"已创建硬链接: {filename} -> {target_file}")
            else:  # move
                shutil.move(source_path, target_file)
                log("info", f"已移动: {filename} -> {target_file}")
            
            # 如果使用organized标记，移动后重置为false(因为文件路径变了)
            # 否则标记为true表示已处理
            if self.use_organized_flag:
                self.api.update_scene(scene_id, organized=False)
            else:
                self.api.update_scene(scene_id, organized=True)
            return True
            
        except Exception as e:
            log("error", f"移动文件失败 {filename}: {str(e)}")
            return False
    
    def scan_only(self):
        """仅扫描新文件"""
        if self.auto_scan:
            self.api.scan_library()
            log("info", "扫描完成")
    
    def move_only(self):
        """仅移动已刮削的文件"""
        # 如果使用organized标记,查询organized=true的场景
        # 否则查询所有场景再用is_scraped判断
        if self.use_organized_flag:
            scenes = self.api.get_scenes_in_path(self.download_path, organized_filter=True)
        else:
            scenes = self.api.get_scenes_in_path(self.download_path, organized_filter=False)
            scenes = [s for s in scenes if self.is_scraped(s)]
        
        moved_count = 0
        for scene in scenes:
            if self.move_file(scene["path"], scene["id"]):
                moved_count += 1
        
        log("info", f"共移动 {moved_count} 个文件")
        return moved_count
    
    def check_and_move(self):
        """检查并移动"""
        send_progress(0.1, "开始扫描...")
        
        if self.auto_scan:
            self.api.scan_library()
            time.sleep(10)  # 等待扫描完成
        
        send_progress(0.3, "获取场景列表...")
        # 获取未处理的场景(organized=false)
        scenes = self.api.get_scenes_in_path(self.download_path, organized_filter=False)
        
        if not scenes:
            log("info", "没有发现新场景")
            return
        
        log("info", f"发现 {len(scenes)} 个场景")
        
        # 刮削未刮削的场景
        if self.auto_identify:
            send_progress(0.4, "开始刮削...")
            for i, scene in enumerate(scenes):
                # 如果使用organized标记,所有organized=false都需要刮削
                # 否则用is_scraped判断
                need_scrape = self.use_organized_flag or not self.is_scraped(scene)
                
                if need_scrape:
                    self.api.identify_scene(scene["id"])
                    time.sleep(2)  # 避免请求过快
                    progress = 0.4 + (0.3 * (i + 1) / len(scenes))
                    send_progress(progress, f"刮削中 {i+1}/{len(scenes)}")
            
            time.sleep(5)  # 等待刮削完成
            
            # 重新获取场景,查看哪些已标记为organized
            if self.use_organized_flag:
                scenes = self.api.get_scenes_in_path(self.download_path, organized_filter=True)
            else:
                scenes = self.api.get_scenes_in_path(self.download_path, organized_filter=False)
                scenes = [s for s in scenes if self.is_scraped(s)]
        
        # 移动已刮削的场景
        send_progress(0.7, "开始移动文件...")
        moved_count = 0
        for i, scene in enumerate(scenes):
            if self.move_file(scene["path"], scene["id"]):
                moved_count += 1
            progress = 0.7 + (0.3 * (i + 1) / len(scenes))
            send_progress(progress, f"处理中 {i+1}/{len(scenes)}")
        
        send_progress(1.0, f"完成! 移动了 {moved_count} 个文件")
        log("info", f"共移动 {moved_count} 个文件")
    
    def auto_monitor(self):
        """自动监控模式"""
        log("info", "启动自动监控模式...")
        log("info", f"检查间隔: {self.check_interval}秒")
        
        cycle = 0
        while True:
            try:
                cycle += 1
                log("info", f"第 {cycle} 次检查")
                self.check_and_move()
                log("info", f"等待 {self.check_interval} 秒...")
                time.sleep(self.check_interval)
            except KeyboardInterrupt:
                log("info", "停止监控")
                break
            except Exception as e:
                log("error", f"监控出错: {str(e)}")
                time.sleep(60)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("server_connection", help="Stash服务器连接信息")
    parser.add_argument("--mode", default="check_and_move", help="运行模式")
    args = parser.parse_args()
    
    # 读取配置
    input_data = read_json_input()
    server_connection = parse_server_connection(args.server_connection)
    
    stash_url = server_connection.get("Scheme", "http") + "://" + \
                server_connection.get("Host", "localhost") + ":" + \
                str(server_connection.get("Port", 9999))
    
    api_key = server_connection.get("ApiKey")
    config = input_data.get("server_connection", {}).get("PluginConfig", {})
    
    # 验证配置
    if not config.get("downloadPath") or not config.get("targetPath"):
        log("error", "请先配置下载目录和目标目录")
        sys.exit(1)
    
    # 初始化
    stash_api = StashAPI(stash_url, api_key)
    mover = AutoMover(stash_api, config)
    
    # 执行对应模式
    mode = args.mode
    if mode == "scan_only":
        mover.scan_only()
    elif mode == "move_only":
        mover.move_only()
    elif mode == "auto_monitor":
        mover.auto_monitor()
    else:  # check_and_move
        mover.check_and_move()

if __name__ == "__main__":
    main()
