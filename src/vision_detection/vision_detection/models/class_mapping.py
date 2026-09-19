"""家居物品类别映射"""

# 家居场景自定义类别
HOME_CLASSES = {
    'toy_block': {'id': 0, 'display_name': '积木玩具', 'category': 'toy'},
    'plush_toy': {'id': 1, 'display_name': '毛绒玩具', 'category': 'toy'},
    'toy_car': {'id': 2, 'display_name': '玩具车', 'category': 'toy'},
    'ball': {'id': 3, 'display_name': '球类', 'category': 'toy'},
    'book': {'id': 4, 'display_name': '书本', 'category': 'item'},
    'clothes': {'id': 5, 'display_name': '衣服', 'category': 'clothing'},
    'shoes': {'id': 6, 'display_name': '鞋子', 'category': 'clothing'},
    'storage_box': {'id': 7, 'display_name': '收纳箱', 'category': 'container'},
    'cup': {'id': 8, 'display_name': '杯子', 'category': 'item'},
    'remote_control': {'id': 9, 'display_name': '遥控器', 'category': 'item'},
}

# 收纳规则：哪些物品应该放入哪个收纳位置
STORAGE_RULES = {
    'toy': {'target': 'storage_box', 'action': 'pick_and_place'},
    'clothing': {'target': 'clothes_basket', 'action': 'fold_and_place'},
    'item': {'target': 'shelf', 'action': 'pick_and_place'},
}

# COCO预训练类别到家居类别的映射
COCO_MAPPING = {
    'sports ball': 'ball',
    'book': 'book',
    'cup': 'cup',
}


def get_class_info(class_name):
    """获取类别信息"""
    return HOME_CLASSES.get(class_name, {'id': -1, 'display_name': class_name, 'category': 'unknown'})


def get_storage_rule(class_name):
    """获取收纳规则"""
    info = get_class_info(class_name)
    category = info.get('category', 'unknown')
    return STORAGE_RULES.get(category, {'target': 'unknown', 'action': 'none'})
