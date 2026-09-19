# 检测到的单个物体
std_msgs/Header header

# 物体类别
string class_name           # 类别名 (如: toy_block, plush_toy, clothes)
int32 class_id              # 类别ID
float32 confidence          # 置信度 0.0~1.0

# 2D边界框 (像素坐标)
int32 bbox_x                # 左上角x
int32 bbox_y                # 左上角y
int32 bbox_width            # 宽度
int32 bbox_height           # 高度

# 3D位置 (相机坐标系, 米)
geometry_msgs/Point position_3d

# 物体属性
string color                 # 主要颜色
float32 estimated_size       # 估计尺寸(米)
