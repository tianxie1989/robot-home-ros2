from setuptools import setup
import os
from glob import glob

package_name = 'ai_training_bridge'

setup(
    name=package_name,
    version='0.1.0',
    packages=[package_name],
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        (os.path.join('share', package_name, 'config'),
            glob(os.path.join('config', '*.yaml'))),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='Robot Home Team',
    maintainer_email='team@robathome.local',
    description='AI训练服务器通信桥接包',
    license='Apache-2.0',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            'model_sync = ai_training_bridge.model_sync_node:main',
            'data_collector = ai_training_bridge.data_collector_node:main',
        ],
    },
)
