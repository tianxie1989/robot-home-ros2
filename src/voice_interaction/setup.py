from setuptools import setup
import os
from glob import glob

package_name = 'voice_interaction'

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
        (os.path.join('share', package_name, 'launch'),
            glob(os.path.join('launch', '*.launch.py'))),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='Robot Home Team',
    maintainer_email='team@robathome.local',
    description='语音交互功能包',
    license='Apache-2.0',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            'tts_node = voice_interaction.tts_node:main',
            'dialog_manager = voice_interaction.dialog_manager_node:main',
            'audio_driver = voice_interaction.asr_node:main',
        ],
    },
)
