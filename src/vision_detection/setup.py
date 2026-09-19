from setuptools import find_packages, setup
import os
from glob import glob

package_name = 'vision_detection'

setup(
    name=package_name,
    version='0.1.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages', ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        (os.path.join('share', package_name, 'launch'), glob('launch/*.py')),
        (os.path.join('share', package_name, 'config'), glob('config/*.yaml')),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='Robot Home Team',
    maintainer_email='team@robathome.local',
    description='物品识别与目标检测',
    license='Apache-2.0',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            'camera_driver = vision_detection.camera_driver_node:main',
            'object_detector = vision_detection.object_detector_node:main',
            'depth_processor = vision_detection.depth_processor_node:main',
            'object_tracker = vision_detection.object_tracker_node:main',
        ],
    },
)
