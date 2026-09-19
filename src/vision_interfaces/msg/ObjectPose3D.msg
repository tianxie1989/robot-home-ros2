# 物体3D位姿 (世界坐标系)
std_msgs/Header header
string object_class
geometry_msgs/Pose pose              # 6DOF位姿
geometry_msgs/Point center           # 中心点
float32 dimensions_x                 # X方向尺寸
float32 dimensions_y                 # Y方向尺寸
float32 dimensions_z                 # Z方向尺寸
float32 confidence                   # 置信度
