"""
捡玩具技能
robot_home_skills/robot_home_skills/pick_toy_skill.py

完整的捡玩具技能实现演示:
1. 检测地面上的玩具
2. 导航到玩具位置
3. 抓取玩具
4. 导航到收纳箱
5. 放入收纳箱
6. 重复直到所有玩具收好
"""

import time
from typing import Dict, Any, List, Optional

from robot_home_skills.skill_base import SkillBase, SkillStatus


# 模拟的玩具检测数据
SIMULATED_TOYS = [
    {'name': 'toy_block_red', 'position': [1.0, 0.5, 0.0], 'class': 'toy_block'},
    {'name': 'toy_block_blue', 'position': [-0.5, 1.2, 0.0], 'class': 'toy_block'},
    {'name': 'toy_car', 'position': [0.8, -0.3, 0.0], 'class': 'toy_car'},
]

# 收纳箱位置
STORAGE_BIN_POSITION = [-1.5, 2.0, 0.0]


class PickToySkill(SkillBase):
    """捡玩具技能 - 检测、导航、抓取并收纳玩具"""

    def __init__(self):
        super().__init__(
            name='pick_toy',
            description='检测地面上的玩具，逐一抓取并放入收纳箱',
        )
        self._detected_toys: List[Dict] = []
        self._picked_toys: List[str] = []
        self._failed_toys: List[str] = []
        self._current_target: Optional[Dict] = None

    def _do_execute(self) -> SkillStatus:
        """执行捡玩具技能"""
        # 阶段1: 检测玩具
        self._update_progress(0.0, '检测玩具中...')
        if not self._detect_toys():
            self._error_message = '玩具检测失败'
            return SkillStatus.FAILURE

        if not self._detected_toys:
            self._current_step = '未检测到玩具'
            return SkillStatus.SUCCESS

        total = len(self._detected_toys)
        self._update_progress(0.1, f'检测到 {total} 个玩具')

        # 阶段2: 逐一抓取
        for i, toy in enumerate(self._detected_toys):
            if self._cancelled:
                return SkillStatus.CANCELLED

            self._current_target = toy
            progress = 0.1 + 0.8 * (i / total)
            self._update_progress(progress, f'正在抓取: {toy["name"]}')

            success = self._pick_and_store(toy)
            if success:
                self._picked_toys.append(toy['name'])
            else:
                self._failed_toys.append(toy['name'])

        # 阶段3: 完成
        self._update_progress(1.0, '捡玩具完成')

        if self._failed_toys:
            self._error_message = (
                f'成功: {len(self._picked_toys)}, '
                f'失败: {len(self._failed_toys)}'
            )
            return SkillStatus.FAILURE if not self._picked_toys else SkillStatus.SUCCESS

        return SkillStatus.SUCCESS

    def _detect_toys(self) -> bool:
        """
        检测地面上的玩具

        在实际部署中，这会调用视觉检测服务。
        当前使用模拟数据演示流程。
        """
        # 模拟检测延迟
        time.sleep(0.1)

        # 使用模拟数据
        target_class = self._params.get('target_class', '')
        if target_class:
            self._detected_toys = [
                t for t in SIMULATED_TOYS if t['class'] == target_class
            ]
        else:
            self._detected_toys = list(SIMULATED_TOYS)

        return True

    def _navigate_to(self, position: List[float]) -> bool:
        """
        导航到目标位置

        在实际部署中，这会调用 Nav2 导航。
        """
        time.sleep(0.1)  # 模拟导航时间
        return True

    def _pick_object(self, toy: Dict) -> bool:
        """
        抓取物体

        在实际部署中，这会调用机械臂控制。
        """
        time.sleep(0.1)  # 模拟抓取时间
        return True

    def _place_in_bin(self) -> bool:
        """
        将物体放入收纳箱

        在实际部署中，这会调用机械臂控制。
        """
        time.sleep(0.1)  # 模拟放置时间
        return True

    def _pick_and_store(self, toy: Dict) -> bool:
        """执行完整的抓取-收纳流程"""
        # 导航到玩具
        if not self._navigate_to(toy['position']):
            return False

        # 抓取
        if not self._pick_object(toy):
            return False

        # 导航到收纳箱
        if not self._navigate_to(STORAGE_BIN_POSITION):
            return False

        # 放入
        if not self._place_in_bin():
            return False

        return True

    def _on_cancel(self):
        """取消时的清理"""
        self._current_target = None

    def get_result(self) -> Dict[str, Any]:
        """获取执行结果详情"""
        return {
            'picked': self._picked_toys,
            'failed': self._failed_toys,
            'total_detected': len(self._detected_toys),
        }
