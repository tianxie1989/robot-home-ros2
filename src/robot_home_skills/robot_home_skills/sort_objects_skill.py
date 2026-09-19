"""
物品归类技能
robot_home_skills/robot_home_skills/sort_objects_skill.py

检测场景中的物体，按类别分类并放置到对应位置:
1. 扫描区域检测所有物体
2. 对物体进行分类
3. 按类别逐一放置到指定位置
"""

import time
from typing import Dict, Any, List

from robot_home_skills.skill_base import SkillBase, SkillStatus


# 默认分类规则
DEFAULT_CATEGORIES = {
    'toy_block': {'bin': 'toy_bin', 'position': [-1.5, 2.0, 0.0]},
    'toy_car': {'bin': 'toy_bin', 'position': [-1.5, 2.0, 0.0]},
    'book': {'bin': 'bookshelf', 'position': [2.5, 0.0, 0.6]},
    'clothes': {'bin': 'laundry_basket', 'position': [-2.0, -1.0, 0.0]},
    'cup': {'bin': 'kitchen_counter', 'position': [2.0, -2.0, 0.8]},
}

# 模拟检测到的物体
SIMULATED_OBJECTS = [
    {'name': 'red_block', 'class': 'toy_block', 'position': [0.5, 0.3, 0.0]},
    {'name': 'blue_book', 'class': 'book', 'position': [0.2, 1.0, 0.3]},
    {'name': 'tshirt_1', 'class': 'clothes', 'position': [-0.3, -0.5, 0.0]},
]


class SortObjectsSkill(SkillBase):
    """物品归类技能 - 检测、分类并放置物体到对应位置"""

    def __init__(self):
        super().__init__(
            name='sort_objects',
            description='检测场景中的物体，按类别分类并放置到指定位置',
        )
        self._categories: Dict[str, Dict] = {}
        self._detected_objects: List[Dict] = []
        self._sorted_objects: List[str] = []
        self._failed_objects: List[str] = []

    def _do_execute(self) -> SkillStatus:
        """执行物品归类技能"""
        # 加载分类规则
        self._categories = self._params.get('categories', DEFAULT_CATEGORIES)

        # 阶段1: 扫描并检测物体
        self._update_progress(0.0, '扫描区域中...')
        if not self._scan_and_detect():
            self._error_message = '物体检测失败'
            return SkillStatus.FAILURE

        if not self._detected_objects:
            self._current_step = '未检测到物体'
            return SkillStatus.SUCCESS

        total = len(self._detected_objects)
        self._update_progress(0.15, f'检测到 {total} 个物体')

        # 阶段2: 逐一分类放置
        for i, obj in enumerate(self._detected_objects):
            if self._cancelled:
                return SkillStatus.CANCELLED

            progress = 0.15 + 0.75 * (i / total)
            obj_class = obj.get('class', 'unknown')
            self._update_progress(progress, f'归类: {obj["name"]} ({obj_class})')

            success = self._sort_one_object(obj)
            if success:
                self._sorted_objects.append(obj['name'])
            else:
                self._failed_objects.append(obj['name'])

        # 阶段3: 完成
        self._update_progress(1.0, '物品归类完成')

        if self._failed_objects and not self._sorted_objects:
            self._error_message = '所有物体归类失败'
            return SkillStatus.FAILURE

        return SkillStatus.SUCCESS

    def _scan_and_detect(self) -> bool:
        """扫描区域并检测物体"""
        time.sleep(0.1)
        self._detected_objects = list(SIMULATED_OBJECTS)
        return True

    def _sort_one_object(self, obj: Dict) -> bool:
        """对单个物体进行分类放置"""
        obj_class = obj.get('class', 'unknown')
        category_info = self._categories.get(obj_class)

        if category_info is None:
            # 未知类别，跳过
            return False

        target_position = category_info.get('position', [0.0, 0.0, 0.0])

        # 导航到物体
        if not self._navigate_to(obj['position']):
            return False

        # 抓取
        if not self._pick(obj):
            return False

        # 导航到目标位置
        if not self._navigate_to(target_position):
            return False

        # 放置
        if not self._place(obj):
            return False

        return True

    def _navigate_to(self, position: List[float]) -> bool:
        """导航到目标位置"""
        time.sleep(0.05)
        return True

    def _pick(self, obj: Dict) -> bool:
        """抓取物体"""
        time.sleep(0.05)
        return True

    def _place(self, obj: Dict) -> bool:
        """放置物体"""
        time.sleep(0.05)
        return True

    def _on_cancel(self):
        """取消清理"""
        pass

    def get_result(self) -> Dict[str, Any]:
        """获取执行结果"""
        return {
            'sorted': self._sorted_objects,
            'failed': self._failed_objects,
            'total': len(self._detected_objects),
        }
