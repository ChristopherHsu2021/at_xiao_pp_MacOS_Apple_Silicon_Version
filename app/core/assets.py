"""素材图片路径解析。

资源文件使用英文文件名，角色配置仍保留中文显示名；这里负责把显示名映射到
稳定的资源 slug，避免打包/运行时遇到非 ASCII 路径差异。
"""

import os
import glob
import re

from app.core import pathutil


ASSET_ALIASES = {
    "桌面图标": "app_icon",
    "撒娇": "uninstall_pleading",
    "呜呜呜": "uninstall_crying",
    "下次见": "uninstall_goodbye",
    "喝酒": "alcohol",
    "喝茶": "tea",
    "喝饮料": "drinks",
    "咖啡": "coffee",
    "奶（果）茶": "milk_fruit_tea",
    "换装": "costumes",
    "工作": "work",
    "居家": "home",
    "准备图": "prep",
    "人物": "person",
    "物品": "item",
    "红茶": "black_tea",
    "绿茶": "green_tea",
    "乌龙茶": "oolong_tea",
    "白兰地": "brandy",
    "二锅头": "er_guo_tou",
    "伏特加": "vodka",
    "黄酒": "huangjiu",
    "金酒": "gin",
    "米酒": "rice_wine",
    "威士忌": "whisky",
    "橙C美式": "orange_c_americano",
    "橙 C 美式": "orange_c_americano",
    "卡布奇诺": "cappuccino",
    "美式（冰）": "iced_americano",
    "拿铁": "latte",
    "生椰拿铁": "coconut_latte",
    "柚C美式": "grapefruit_c_americano",
    "柚 C 美式": "grapefruit_c_americano",
    "多肉葡萄": "grape_tea",
    "桂花酒酿": "osmanthus_rice_wine",
    "荔枝冰酿": "lychee_ice_brew",
    "蜜桃四季春": "peach_sijichun",
    "四季奶青": "sijichun_milk_tea",
    "杨枝甘露": "mango_pomelo_sago",
    "吃饭": "meal",
    "打扫": "cleaning",
    "度假": "vacation",
    "拒绝上传": "upload_rejected",
    "遛狗": "dog_walk",
    "上传成功": "upload_success",
    "是否上传": "upload_confirm",
    "刷手机": "phone_browsing",
    "睡觉": "sleep",
    "左休息": "left_rest",
    "右休息": "right_rest",
    "听歌": "music",
    "运动": "exercise",
    "调酒师": "bartender",
    "服务员": "waiter",
    "歌手": "singer",
    "收银员": "cashier",
    "文员": "clerk",
    "衬衫": "shirt",
    "短袖": "tshirt",
    "夹克": "jacket",
    "卫衣": "hoodie",
}


def _norm(name: str) -> str:
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", (name or "").lower())


def _asset_name(name: str) -> str:
    value = name or ""
    for zh, en in sorted(ASSET_ALIASES.items(), key=lambda item: len(item[0]), reverse=True):
        value = value.replace(zh, en)
    return value


def find_image(name: str, root: str = None) -> str or None:
    """在 root 下递归查找归一化文件名与 name 一致的图片。"""
    if root is None:
        root = pathutil.get_assets_dir()
    target = _norm(_asset_name(name))
    for ext in ("*.png", "*.jpg", "*.jpeg", "*.gif", "*.webp"):
        for p in glob.glob(os.path.join(root, "**", ext), recursive=True):
            if _norm(os.path.splitext(os.path.basename(p))[0]) == target:
                return p
    return None


def find_images(name: str, root: str = None) -> list:
    """返回所有归一化文件名与 name 一致的图片（用于换装多帧）。"""
    if root is None:
        root = pathutil.get_assets_dir()
    target = _norm(_asset_name(name))
    result = []
    for ext in ("*.png", "*.jpg", "*.jpeg", "*.gif", "*.webp"):
        for p in glob.glob(os.path.join(root, "**", ext), recursive=True):
            if _norm(os.path.splitext(os.path.basename(p))[0]) == target:
                result.append(p)
    return sorted(result)


def get_drink_image(category: str, name: str) -> str or None:
    """category: 酒类 / 茶类 / 咖啡 / 奶（果）茶。"""
    if category == "酒类":
        return find_image(name, os.path.join(pathutil.get_assets_dir(), "alcohol"))
    if category == "茶类":
        return find_image(name, os.path.join(pathutil.get_assets_dir(), "tea"))
    # 咖啡 / 奶（果）茶 都在 喝饮料 下
    return find_image(name, os.path.join(pathutil.get_assets_dir(), "drinks"))


def get_costume_images(name: str) -> list:
    """换装为多帧（衬衫1/衬衫2…），按前缀匹配。"""
    root = os.path.join(pathutil.get_assets_dir(), "costumes")
    target = _norm(_asset_name(name))
    result = []
    for ext in ("*.png", "*.jpg", "*.jpeg", "*.gif", "*.webp"):
        for p in glob.glob(os.path.join(root, "**", ext), recursive=True):
            stem = _norm(os.path.splitext(os.path.basename(p))[0])
            if stem == target or (stem.startswith(target) and stem[len(target):].isdigit()):
                result.append(p)
    return sorted(result)


def get_work_final(name: str) -> str or None:
    return find_image(name, os.path.join(pathutil.get_assets_dir(), "work"))


def get_home_final(name: str) -> str or None:
    return find_image(name, os.path.join(pathutil.get_assets_dir(), "home"))


def get_idle_rest_images(side: str) -> list:
    """返回闲置休息图（left/right_*）。"""
    root = pathutil.get_assets_dir()
    prefix = "left_" if side == "left" else "right_"
    result = []
    for ext in ("*.png", "*.jpg", "*.jpeg", "*.gif", "*.webp"):
        for p in glob.glob(os.path.join(root, "**", f"{prefix}*{ext[1:]}"), recursive=True):
            if os.path.basename(p).lower().startswith(prefix):
                result.append(p)
    return sorted(result)


def get_work_prep(name: str):
    """返回 (人物图, 物品图)。"""
    folder = os.path.join(pathutil.get_assets_dir(), "work", "prep")
    person = find_image(f"{name}人物", folder)
    item = find_image(f"{name}物品", folder)
    return person, item


def get_home_prep(name: str):
    folder = os.path.join(pathutil.get_assets_dir(), "home", "prep")
    person = find_image(f"{name}人物", folder)
    item = find_image(f"{name}物品", folder)
    return person, item


def get_music_folder() -> str:
    """用户上传/内置音乐目录。"""
    return pathutil.data_file("music")


def get_library_folder() -> str:
    """用户音乐曲库目录（与卜卜音悦术语对齐，实际等价于 get_music_folder）。"""
    return get_music_folder()


def list_music_files() -> list:
    folder = get_music_folder()
    out = []
    for ext in ("*.mp3", "*.wav", "*.ogg", "*.flac", "*.m4a"):
        out.extend(glob.glob(os.path.join(folder, ext)))
    return sorted(out)


# 支持的音频扩展名（用于拖拽上传时的类型检测）
AUDIO_EXTS = {
    ".mp3", ".wav", ".ogg", ".flac", ".m4a", ".aac", ".wma", ".opus",
    ".ape", ".mid", ".midi", ".mka", ".ac3", ".tta", ".wv",
}


def is_audio_file(path: str) -> bool:
    """判断给定路径是否为音频文件（按扩展名）。"""
    if not path:
        return False
    return os.path.splitext(path)[1].lower() in AUDIO_EXTS
