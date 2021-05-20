from setuptools import setup, find_packages
from glob import glob

package_name = 'stretch_core'

setup(
    name=package_name,
    version='0.2.0',
    packages=find_packages(),
    data_files=[
        ('share/ament_index/resource_index/packages', ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        ('share/' + package_name + '/launch', glob('launch/*.launch.py')),
        ('share/' + package_name + '/launch', ['launch/stretch_ekf.yaml']),
        ('share/' + package_name + '/config', glob('config/*')),
        ('share/' + package_name + '/rviz', glob('rviz/*.rviz')),
    ],
    install_requires=['setuptools'],
    url='',
    license='',
    author='Hello Robot Inc.',
    author_email='support@hello-robot.com',
    description='The stretch_core package',
    entry_points={
        'console_scripts': [
            'send_traj = stretch_core.send_traj:main',
            'd435i_accel_correction = stretch_core.d435i_accel_correction:main',
            'd435i_configure = stretch_core.d435i_configure:main',
            'd435i_frustum_visualizer = stretch_core.d435i_frustum_visualizer:main',
            'detect_aruco_markers = stretch_core.detect_aruco_markers:main',
            'keyboard = stretch_core.keyboard:main',
            'keyboard_teleop = stretch_core.keyboard_teleop:main',
            'plot_traj = stretch_core.plot_traj:main',
            'plot_planned = stretch_core.plot_planned:main',
            'stretch_driver = stretch_core.stretch_driver:main',
            'stop_all_trajectories = stretch_core.stop_all_trajectories:main',
        ],
    },
)
