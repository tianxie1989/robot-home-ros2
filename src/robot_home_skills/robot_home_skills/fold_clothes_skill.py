"""
叠衣服技能
robot_home_skills/robot_home_skills/fold_clothes_skill.py

检测衣物并执行折叠动作序列:
1. 检测衣物位置和类型
2. 抓取并展平衣物
3. 根据衣物类型执行折叠步骤
4. 放置折叠好的衣物
"""

import time
from typing import Dict, Any, List, Optional

from robot_home_skills.skill_base import SkillBase, SkillStatus


# 衣物类型及其折叠步骤
FOLD_STEPS = {
    'tshirt': [
        {'action': 'flatten', 'description': '展平T恤'},
        {'action': 'fold_left', 'description': '折叠左侧'},
        {'action': 'fold_right', 'description': '折叠右侧'},
        {'action': 'fold_bottom', 'description': '向上折叠下摆'},
    ],
    'pants': [
        {'action': 'flatten', 'description': '展平裤子'},
        {'action': 'fold_half', 'description': '对折'},
        {'action': 'fold_third', 'description': '三折'},
    ],
    'sock': [
        {'action': 'pair', 'description': '配对袜子'},
        {'action': 'roll', 'description': '卷起'},
    ],
    'towel': [
        {'action': 'flatten', 'description': '展平毛巾'},
        {'action': 'fold_third', 'description': '三折'},
        {'action': 'fold_half', 'description': '对折'},
    ],
}

# 模拟检测到的衣物
SIMULATED_CLOTHES = [
    {'name': 'tshirt_white', 'class': 'tshirt', 'position': [0.3, 0.5, 0.3]},
]


class FoldClothesSkill(SkillBase):
    """叠衣服技能 - 检测衣物并执行折叠动作序列"""

    def __init__(self):
        super().__init__(
            name='fold_clothes',
            description='检测衣物并执行折叠动作序列，将衣物叠放整齐',
        )
        self._detected_clothes: List[Dict] = []
        self._folded_clothes: List[str] = []
        self._failed_clothes: List[str] = []
        self._place_position: List[float] = [-1.0, 0.5, 0.5]

    def _do_execute(self) -> SkillStatus:
        """执行叠衣服技能"""
        # 阶段1: 检测衣物
        self._update_progress(0.0, '检测衣物中...')
        if not self._detect_clothes():
            self._error_message = '衣物检测失败'
            return SkillStatus.FAILURE

        if not self._detected_clothes:
            self._current_step = '未检测到衣物'
            return SkillStatus.SUCCESS

        total = len(self._detected_clothes)
        self._update_progress(0.1, f'检测到 {total} 件衣物')

        # 阶段2: 逐一折叠
        for i, cloth in enumerate(self._detected_clothes):
            if self._cancelled:
                return SkillStatus.CANCELLED

            progress = 0.1 + 0.8 * (i / total)
            cloth_class = cloth.get('class', 'unknown')
            self._update_progress(progress, f'折叠: {cloth["name"]} ({cloth_class})')

            success = self._fold_one_cloth(cloth)
            if success:
                self._folded_clothes.append(cloth['name'])
            else:
                self._failed_clothes.append(cloth['name'])

        # 阶段3: 完成
        self._update_progress(1.0, '叠衣服完成')

        if self._failed_clothes and not self._folded_clothes:
            self._error_message = '所有衣物折叠失败'
            return SkillStatus.FAILURE

        return SkillStatus.SUCCESS

    def _detect_clothes(self) -> bool:
        """检测衣物"""
        time.sleep(0.1)
        target_class = self._params.get('clothes_class', '')
        if target_class:
            self._detected_clothes = [
                c for c in SIMULATED_CLOTHES if c['class'] == target_class
            ]
        else:
            self._detected_clothes = list(SIMULATED_CLOTHES)
        return True

    def _fold_one_cloth(self, cloth: Dict) -> bool:
        """折叠单件衣物"""
        cloth_class = cloth.get('class', 'unknown')
        steps = FOLD_STEPS.get(cloth_class)

        if steps is None:
            # 未知衣物类型，使用通用步骤
            steps = FOLD_STEPS.get('tshirt')

        # 导航到衣物位置
        if not self._navigate_to(cloth['position']):
            return False

        # 抓取
        if not self._pick(cloth):
            return False

        # 导航到折叠台
        fold_table_pos = self._params.get('fold_table', [0.0, 0.0, 0.5])
        if not self._navigate_to(fold_table_pos):
            return False

        # 放置并执行折叠步骤
        if not self._place_for_folding():
            return False

        for step in steps:
            if self._cancelled:
                return False
            action = step['action']
            if not self._execute_fold_step(action):
                return False

        # 抓取折叠好的衣物
        if not self._pick_folded():
            return False

        # 放置到目标位置
        if not self._navigate_to(self._place_position):
            return False

        if not self._place_folded():
            return False

        return True

    def _navigate_to(self, position: List[float]) -> bool:
        """导航到目标位置"""
        time.sleep(0.05)
        return True

    def _pick(self, cloth: Dict) -> bool:
        """抓取衣物"""
        time.sleep(0.05)
        return True

    def _place_for_folding(self) -> bool:
        """放置在折叠台上"""
        time.sleep(0.05)
        return True

    def _execute_fold_step(self, action: str) -> bool:
        """执行单个折叠步骤"""
        time.sleep(0.05)
        return True

    def _pick_folded(self) -> bool:
        """抓取折叠好的衣物"""
        time.sleep(0.05)
        return True

    def _place_folded(self) -> bool:
        """放置折叠好的衣物"""
        time.sleep(0.05)
        return True

    def _on_cancel(self):
        """取消清理"""
        pass

    def get_result(self) -> Dict[str, Any]:
        """获取执行结果"""
        return {
            'folded': self._folded_clothes,
            'failed': self._failed_clothes,
            'total': len(self._detected_clothes),
        }
